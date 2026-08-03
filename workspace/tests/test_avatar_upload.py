from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import storages
from django.test import TestCase

from core.file_processing.images import ProcessedAvatar
from core.models import Member, MemberPublicProfile
from core.tests.helpers import create_member, login_as_member


PROCESSED = ProcessedAvatar(
    content=b"canonical-webp",
    content_type="image/webp",
    sha256="a" * 64,
    size=len(b"canonical-webp"),
)


class WorkspaceAvatarUploadTests(TestCase):
    def setUp(self):
        storages._storages.pop("avatars", None)
        self.member = create_member(member_no="mem-avatar-01")
        login_as_member(self.client, self.member)

    @patch("core.avatar_services.process_avatar", return_value=PROCESSED)
    def test_member_can_upload_and_read_own_avatar(self, _process):
        response = self.client.post(
            "/workspace/profile/avatar/upload/",
            {"avatar": SimpleUploadedFile("secret-name.png", b"input", content_type="image/png")},
        )
        self.assertEqual(response.status_code, 302)
        profile = MemberPublicProfile.objects.get(member=self.member)
        self.assertTrue(profile.avatar_key.startswith("realworld/runtime/current-assets/avatars/"))
        self.assertNotIn("secret-name", profile.avatar_key)
        response = self.client.get(f"/u/{self.member.member_no}/avatar/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(profile.avatar_key, str(response.headers))
        self.assertIn("immutable", response["Cache-Control"])

    @patch("core.avatar_services.process_avatar", return_value=PROCESSED)
    def test_avatar_url_version_changes_after_replacement_and_removal(self, _process):
        self.client.post(
            "/workspace/profile/avatar/upload/",
            {"avatar": SimpleUploadedFile("first.png", b"first", content_type="image/png")},
        )
        first_url = self.client.get("/workspace/profile/").context["profile_form"]["avatar_url"]

        self.client.post(
            "/workspace/profile/avatar/upload/",
            {"avatar": SimpleUploadedFile("second.png", b"second", content_type="image/png")},
        )
        second_url = self.client.get("/workspace/profile/").context["profile_form"]["avatar_url"]
        self.client.post("/workspace/profile/avatar/remove/")
        removed_url = self.client.get("/workspace/profile/").context["profile_form"]["avatar_url"]

        self.assertNotEqual(first_url, second_url)
        self.assertNotEqual(second_url, removed_url)
        self.assertIn("?v=", removed_url)

    def test_missing_upload_keeps_current_profile_unchanged(self):
        response = self.client.post("/workspace/profile/avatar/upload/", {})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MemberPublicProfile.objects.filter(member=self.member).exists())

    @patch("core.avatar_services.process_avatar", return_value=PROCESSED)
    def test_member_can_restore_default_avatar(self, _process):
        self.client.post(
            "/workspace/profile/avatar/upload/",
            {"avatar": SimpleUploadedFile("x.png", b"input", content_type="image/png")},
        )
        response = self.client.post("/workspace/profile/avatar/remove/")
        self.assertEqual(response.status_code, 302)
        profile = MemberPublicProfile.objects.get(member=self.member)
        self.assertEqual(profile.avatar_key, "")
        response = self.client.get(f"/u/{self.member.member_no}/avatar/")
        self.assertEqual(response["Content-Type"], "image/svg+xml")

    def test_staff_without_member_cannot_upload_avatar(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="avatar-staff", is_staff=True)
        self.client.force_login(user)
        response = self.client.post(
            "/workspace/profile/avatar/upload/",
            {"avatar": SimpleUploadedFile("x.png", b"input")},
        )
        self.assertEqual(response.status_code, 403)

    @patch("core.avatar_services.process_avatar", return_value=PROCESSED)
    def test_pending_member_can_upload_only_own_avatar(self, _process):
        pending = create_member(member_no="mem-avatar-pending", status=Member.Status.PENDING_REVIEW)
        other = create_member(member_no="mem-avatar-other")
        login_as_member(self.client, pending)
        response = self.client.post(
            "/workspace/profile/avatar/upload/",
            {
                "member_no": other.member_no,
                "avatar": SimpleUploadedFile("x.png", b"input", content_type="image/png"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MemberPublicProfile.objects.get(member=pending).avatar_key)
        self.assertFalse(MemberPublicProfile.objects.filter(member=other).exists())

    def test_public_missing_avatar_falls_back_without_storage_details(self):
        response = self.client.get(f"/u/{self.member.member_no}/avatar/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertNotIn("immutable", response["Cache-Control"])

    def test_missing_current_object_falls_back_to_default(self):
        MemberPublicProfile.objects.create(
            member=self.member,
            avatar_key="realworld/runtime/current-assets/avatars/missing.webp",
            avatar_sha256="f" * 64,
            avatar_size=123,
        )
        response = self.client.get(f"/u/{self.member.member_no}/avatar/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
