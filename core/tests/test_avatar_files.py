from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from core.exceptions import DomainError
from core.file_processing.detection import identify_allowed_image
from core.file_processing.images import ProcessedAvatar, process_avatar
from core.file_processing.limits import read_bounded_upload
from core.file_storage.keys import new_avatar_key, require_deletable_avatar_key
from core.models import Event, MemberPublicProfile
from core.tests.helpers import create_member


def image_upload(*, mode="RGB", size=(800, 600), fmt="PNG"):
    from PIL import Image

    buffer = BytesIO()
    color = (255, 0, 0, 128) if mode == "RGBA" else "red"
    Image.new(mode, size, color).save(buffer, fmt)
    return SimpleUploadedFile("private-person-name.png", buffer.getvalue(), content_type="image/png")


class AvatarFileProcessingTests(SimpleTestCase):
    @patch("core.file_processing.images.identify_allowed_image", return_value="png")
    @patch("PIL.Image.open")
    def test_pixel_limit_is_checked_before_full_decode(self, image_open, _identify):
        source = Mock()
        source.size = (6000, 5000)
        image_open.return_value.__enter__.return_value = source

        with self.assertRaisesMessage(DomainError, "像素总量超过限制"):
            process_avatar(SimpleUploadedFile("small.png", b"small compressed image"))

        source.load.assert_not_called()

    @patch("core.file_processing.images.identify_allowed_image", return_value="png")
    def test_image_is_cropped_and_reencoded_as_metadata_free_webp(self, _identify):
        from PIL import Image

        output = process_avatar(image_upload())
        self.assertEqual(output.content_type, "image/webp")
        self.assertEqual(len(output.sha256), 64)
        with Image.open(BytesIO(output.content)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (512, 512))
            self.assertNotIn("exif", image.info)
            self.assertNotIn("icc_profile", image.info)

    @patch("core.file_processing.images.identify_allowed_image", return_value="png")
    def test_transparency_is_preserved(self, _identify):
        from PIL import Image

        output = process_avatar(image_upload(mode="RGBA"))
        with Image.open(BytesIO(output.content)) as image:
            self.assertIn("A", image.getbands())

    @override_settings(AVATAR_MAX_UPLOAD_BYTES=4)
    def test_bounded_upload_rejects_oversized_content(self):
        with self.assertRaises(DomainError):
            read_bounded_upload(SimpleUploadedFile("x.png", b"12345"), max_bytes=4)

    def test_bounded_upload_rejects_empty_content(self):
        with self.assertRaises(DomainError):
            read_bounded_upload(SimpleUploadedFile("x.png", b""), max_bytes=10)

    @patch("core.file_processing.detection._detector")
    def test_detection_rejects_non_image_label(self, detector):
        detector.return_value.identify_bytes.return_value.output.label = "svg"
        with self.assertRaises(DomainError):
            identify_allowed_image(b"<svg/>")


class AvatarKeyBoundaryTests(SimpleTestCase):
    def test_random_key_contains_lifecycle_and_world_but_not_hash(self):
        key = new_avatar_key("realworld")
        self.assertTrue(key.startswith("realworld/runtime/current-assets/avatars/"))
        self.assertTrue(key.endswith(".webp"))

    def test_delete_validation_rejects_other_world_and_permanent_prefix(self):
        key = new_avatar_key("realworld")
        with self.assertRaises(DomainError):
            require_deletable_avatar_key(key, world_id="simulation0001")
        with self.assertRaises(DomainError):
            require_deletable_avatar_key(
                "realworld/runtime/permanent-attachments/file.webp",
                world_id="realworld",
            )

    def test_reusable_processing_does_not_import_profile_model(self):
        root = Path(__file__).resolve().parents[1] / "file_processing"
        source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        self.assertNotIn("MemberPublicProfile", source)

    def test_avatar_gateway_has_no_permanent_delete_api(self):
        from core.file_storage.gateway import AvatarStorageGateway

        self.assertFalse(hasattr(AvatarStorageGateway, "delete_permanent"))

    def test_delete_validation_rejects_path_traversal(self):
        with self.assertRaises(DomainError):
            require_deletable_avatar_key(
                "realworld/runtime/current-assets/avatars/../secret",
                world_id="realworld",
            )


class MemberPublicProfileAvatarModelTests(TestCase):
    def test_partial_avatar_metadata_is_invalid(self):
        profile = MemberPublicProfile(avatar_key="realworld/runtime/current-assets/avatars/x.webp")
        with self.assertRaises(ValidationError):
            profile.clean()


class _FakeGateway:
    def __init__(self, *, fail_save=False, fail_delete=False):
        self.fail_save = fail_save
        self.fail_delete = fail_delete
        self.saved = []
        self.deleted = []

    def save_processed(self, *, world_id, content):
        if self.fail_save:
            raise OSError("storage down")
        key = f"{world_id}/runtime/current-assets/avatars/new.webp"
        self.saved.append((key, content))
        return key

    def delete_current(self, key, *, world_id):
        if self.fail_delete:
            raise OSError("delete down")
        self.deleted.append((key, world_id))


class AvatarServiceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.member = create_member(member_no="mem-avatar-service")
        self.processed = ProcessedAvatar(b"webp", "image/webp", "c" * 64, 4)

    @patch("core.avatar_services.process_avatar")
    def test_replacement_commits_new_reference_then_deletes_old(self, process):
        from core.avatar_services import replace_own_avatar

        process.return_value = self.processed
        MemberPublicProfile.objects.create(
            member=self.member,
            avatar_key="realworld/runtime/current-assets/avatars/old.webp",
            avatar_sha256="b" * 64,
            avatar_size=3,
        )
        gateway = _FakeGateway()
        profile = replace_own_avatar(
            member=self.member,
            world_id="realworld",
            upload=SimpleUploadedFile("private.png", b"source"),
            gateway=gateway,
        )
        self.assertTrue(profile.avatar_key.endswith("new.webp"))
        self.assertEqual(gateway.deleted, [("realworld/runtime/current-assets/avatars/old.webp", "realworld")])

    @patch("core.avatar_services.process_avatar")
    def test_storage_failure_preserves_existing_avatar(self, process):
        from core.avatar_services import replace_own_avatar

        process.return_value = self.processed
        profile = MemberPublicProfile.objects.create(
            member=self.member,
            avatar_key="realworld/runtime/current-assets/avatars/old.webp",
            avatar_sha256="b" * 64,
            avatar_size=3,
        )
        with self.assertRaises(DomainError):
            replace_own_avatar(
                member=self.member,
                world_id="realworld",
                upload=SimpleUploadedFile("private.png", b"source"),
                gateway=_FakeGateway(fail_save=True),
            )
        profile.refresh_from_db()
        self.assertTrue(profile.avatar_key.endswith("old.webp"))

    @patch("core.avatar_services.member_has_permission", return_value=False)
    def test_administrator_removal_fails_closed_without_permission(self, _permission):
        from core.avatar_services import remove_avatar_as_administrator

        target = create_member(member_no="mem-avatar-target")
        with self.assertRaises(DomainError):
            remove_avatar_as_administrator(
                actor=self.member,
                target=target,
                world_id="realworld",
                gateway=_FakeGateway(),
            )

    @patch("core.avatar_services.member_has_permission", return_value=True)
    def test_authorized_administrator_removal_records_current_state(self, _permission):
        from core.avatar_services import remove_avatar_as_administrator

        target = create_member(member_no="mem-avatar-target-authorized")
        profile = MemberPublicProfile.objects.create(
            member=target,
            avatar_key="realworld/runtime/current-assets/avatars/bad.webp",
            avatar_sha256="d" * 64,
            avatar_size=3,
        )
        gateway = _FakeGateway()
        remove_avatar_as_administrator(
            actor=self.member,
            target=target,
            world_id="realworld",
            gateway=gateway,
        )
        profile.refresh_from_db()
        self.assertEqual(profile.avatar_key, "")
        self.assertIsNotNone(profile.avatar_updated_at)
        self.assertEqual(gateway.deleted, [("realworld/runtime/current-assets/avatars/bad.webp", "realworld")])
        event = Event.objects.get(payload__action="member_avatar_removed")
        self.assertEqual(event.payload["actor_member_no"], self.member.member_no)
        self.assertEqual(event.payload["target_member_no"], target.member_no)
        self.assertNotIn("avatar_key", event.payload)
