"""Business attachment and replaceable payment boundary tests."""

from datetime import date
from io import BytesIO
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.attachment_services import can_read_private_claim_attachment, correct_expense_attachment, create_expense_attachments, publish_expense_attachment_copy
from core.exceptions import DomainError
from core.file_processing.business_attachments import process_business_attachment
from core.file_storage.business_gateway import BusinessAttachmentStorageGateway
from core.finance_services import mark_expense_claim_paid, review_expense_claim, submit_expense_claim
from core.finance_setup import FINANCE_PAY_PERMISSION, FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION, FINANCE_REVIEW_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION, ensure_finance_roles
from core.member_roles import ROLE_COVENANTER
from core.models import Attachment, ExpenseClaimAttachment, FinanceTransaction, PaymentExecution
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member, login_as_member


def _png_upload(name="evidence.png"):
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _finance_member(member_no, permission):
    member = create_member(member_no, display_name=member_no, role_name=ROLE_COVENANTER)
    setup = ensure_finance_roles()
    if permission == FINANCE_REVIEW_PERMISSION:
        role = setup["review_role"]
    elif permission == FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION:
        role = setup["publish_role"]
    else:
        role = setup["pay_role"]
    create_role_assignment(member=member, role=role)
    return member


class BusinessAttachmentTests(TestCase):
    def setUp(self):
        self.claimant = create_member("attach-claimant", display_name="申请人", role_name=ROLE_COVENANTER)

    def test_valid_png_preserves_original_bytes_and_hash(self):
        processed = process_business_attachment(_png_upload())
        self.assertEqual(processed.media_type, "image/png")
        self.assertEqual(processed.size, len(processed.content))
        self.assertEqual(len(processed.sha256), 64)

    def test_disguised_text_is_rejected(self):
        with self.assertRaises(DomainError):
            process_business_attachment(SimpleUploadedFile("fake.png", b"not an image"))

    @override_settings(ATTACHMENT_MAX_FILES=1)
    def test_batch_count_limit_is_enforced(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="数量", description="", amount=10,
            expense_date="2026-08-03",
        )
        with self.assertRaises(DomainError):
            create_expense_attachments(
                claim=claim, uploaded_by=self.claimant,
                uploads=[_png_upload("a.png"), _png_upload("b.png")],
                purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE,
                world_id="realworld",
            )

    def test_attachment_is_immutable_and_avatar_prefix_is_separate(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="凭证", description="", amount=10,
            expense_date="2026-08-03",
        )
        link = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload()],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE,
            world_id="realworld",
        )[0]
        self.assertTrue(link.attachment.object_key.startswith("realworld/runtime/permanent-attachments/"))
        link.attachment.display_filename = "changed.png"
        with self.assertRaises(ValueError):
            link.attachment.save()

    def test_cross_world_key_is_rejected(self):
        gateway = BusinessAttachmentStorageGateway()
        key = gateway.save_immutable(world_id="simulation0001", content=b"world-boundary")
        with self.assertRaises(DomainError):
            gateway.open(key, world_id="realworld")

    def test_public_derivative_is_a_distinct_object(self):
        publisher = _finance_member("attach-publisher", FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION)
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="公开副本", description="", amount=10,
            expense_date="2026-08-03",
        )
        private_link = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload("private.png")],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE, world_id="realworld",
        )[0]
        public_link = publish_expense_attachment_copy(
            claim=claim, source_attachment=private_link.attachment, uploaded_by=publisher,
            upload=_png_upload("redacted.png"), world_id="realworld",
        )
        self.assertEqual(public_link.attachment.audience, Attachment.Audience.PUBLIC)
        self.assertEqual(public_link.attachment.source_attachment, private_link.attachment)
        self.assertNotEqual(public_link.attachment.object_key, private_link.attachment.object_key)

    def test_unrelated_member_cannot_publish(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="拒绝发布", description="", amount=10,
            expense_date="2026-08-03",
        )
        source = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload()],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE, world_id="realworld",
        )[0].attachment
        unrelated = create_member("attach-unrelated")
        with self.assertRaises(DomainError):
            publish_expense_attachment_copy(
                claim=claim, source_attachment=source, uploaded_by=unrelated,
                upload=_png_upload("public.png"), world_id="realworld",
            )

    def test_reviewers_and_payers_cannot_publish(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="独立发布权限", description="", amount=10,
            expense_date="2026-08-03",
        )
        source = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload()],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE, world_id="realworld",
        )[0].attachment
        for member in (
            _finance_member("attach-publish-reviewer", FINANCE_REVIEW_PERMISSION),
            _finance_member("attach-publish-payer", FINANCE_PAY_PERMISSION),
        ):
            with self.subTest(member=member.member_no), self.assertRaises(DomainError):
                publish_expense_attachment_copy(
                    claim=claim, source_attachment=source, uploaded_by=member,
                    upload=_png_upload("public.png"), world_id="realworld",
                )

    def test_publication_link_failure_rolls_back_attachment_and_object(self):
        publisher = _finance_member(
            "attach-atomic-publisher", FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
        )
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="发布关联失败", description="", amount=10,
            expense_date="2026-08-03",
        )
        source = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload("private.png")],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE, world_id="realworld",
        )[0].attachment
        before_attachments = Attachment.objects.count()
        gateway = BusinessAttachmentStorageGateway()
        saved_keys = []
        original_save = BusinessAttachmentStorageGateway.save_immutable

        def capture_save(instance, **kwargs):
            key = original_save(instance, **kwargs)
            saved_keys.append(key)
            return key

        with patch.object(BusinessAttachmentStorageGateway, "save_immutable", capture_save), \
             patch.object(ExpenseClaimAttachment.objects, "create", side_effect=RuntimeError("link failed")):
            with self.assertRaises(RuntimeError):
                publish_expense_attachment_copy(
                    claim=claim, source_attachment=source, uploaded_by=publisher,
                    upload=_png_upload("public.png"), world_id="realworld",
                )
        self.assertEqual(Attachment.objects.count(), before_attachments)
        self.assertEqual(len(saved_keys), 1)
        self.assertFalse(gateway.exists(saved_keys[0], world_id="realworld"))

    def test_correction_appends_and_keeps_original(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="更正", description="", amount=10,
            expense_date="2026-08-03",
        )
        original = create_expense_attachments(
            claim=claim, uploaded_by=self.claimant, uploads=[_png_upload("old.png")],
            purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE, world_id="realworld",
        )[0]
        correction = correct_expense_attachment(
            claim=claim, replaced_attachment=original.attachment, uploaded_by=self.claimant,
            upload=_png_upload("new.png"), world_id="realworld",
        )
        self.assertEqual(correction.attachment.supersedes, original.attachment)
        self.assertTrue(Attachment.objects.filter(pk=original.attachment.pk).exists())

    def test_complete_claim_payment_with_evidence(self):
        reviewer = _finance_member("attach-reviewer", FINANCE_REVIEW_PERMISSION)
        payer = _finance_member("attach-payer", FINANCE_PAY_PERMISSION)
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="服务器账单", description="月费", amount=100,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("invoice.png")],
            world_id="realworld", require_evidence=True,
        )
        review_expense_claim(claim=claim, reviewer_member=reviewer, decision="approved")
        transaction = mark_expense_claim_paid(
            claim=claim, payer_member=payer, payment_date=date(2026, 8, 3),
            payment_method="银行转账", evidence_uploads=[_png_upload("payment.png")],
            world_id="realworld", require_evidence=True,
        )
        claim.refresh_from_db()
        self.assertEqual(claim.status, claim.Status.PAID)
        self.assertEqual(FinanceTransaction.objects.filter(claim=claim).count(), 1)
        execution = PaymentExecution.objects.get(claim=claim)
        self.assertEqual(execution.backend_type, "liveos_manual")
        self.assertEqual(execution.finance_transaction, transaction)
        self.assertEqual(claim.attachment_links.count(), 2)

    @override_settings(FINANCE_PAYMENT_BACKEND="not-implemented")
    def test_unknown_payment_backend_fails_closed(self):
        reviewer = _finance_member("attach-reviewer2", FINANCE_REVIEW_PERMISSION)
        payer = _finance_member("attach-payer2", FINANCE_PAY_PERMISSION)
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="失败付款", description="", amount=10,
            expense_date="2026-08-03",
        )
        review_expense_claim(claim=claim, reviewer_member=reviewer, decision="approved")
        with self.assertRaises(DomainError):
            mark_expense_claim_paid(claim=claim, payer_member=payer)
        claim.refresh_from_db()
        self.assertEqual(claim.status, claim.Status.APPROVED)
        self.assertFalse(FinanceTransaction.objects.filter(claim=claim).exists())

    def test_storage_failure_rolls_back_claim(self):
        before = self.claimant.expense_claims.count()
        with patch("core.file_storage.business_gateway.BusinessAttachmentStorageGateway.save_immutable", side_effect=OSError("storage down")):
            with self.assertRaises(OSError):
                submit_expense_claim(
                    claimant_member=self.claimant, title="存储失败", description="", amount=10,
                    expense_date="2026-08-03", evidence_uploads=[_png_upload()],
                    world_id="realworld", require_evidence=True,
                )
        self.assertEqual(self.claimant.expense_claims.count(), before)

    def test_later_database_failure_removes_uploaded_object(self):
        gateway = BusinessAttachmentStorageGateway()
        saved_keys = []
        original_save = BusinessAttachmentStorageGateway.save_immutable

        def capture_save(instance, **kwargs):
            key = original_save(instance, **kwargs)
            saved_keys.append(key)
            return key

        with patch.object(BusinessAttachmentStorageGateway, "save_immutable", capture_save), \
             patch("core.finance_services._write_public_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                submit_expense_claim(
                    claimant_member=self.claimant, title="事件失败", description="", amount=10,
                    expense_date="2026-08-03", evidence_uploads=[_png_upload()],
                    world_id="realworld", require_evidence=True,
                )
        self.assertFalse(self.claimant.expense_claims.filter(title="事件失败").exists())
        self.assertEqual(len(saved_keys), 1)
        self.assertFalse(gateway.exists(saved_keys[0], world_id="realworld"))

    def test_later_payment_failure_removes_uploaded_object(self):
        reviewer = _finance_member("attach-rollback-reviewer", FINANCE_REVIEW_PERMISSION)
        payer = _finance_member("attach-rollback-payer", FINANCE_PAY_PERMISSION)
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="付款事件失败", description="", amount=10,
            expense_date="2026-08-03",
        )
        review_expense_claim(claim=claim, reviewer_member=reviewer, decision="approved")
        gateway = BusinessAttachmentStorageGateway()
        saved_keys = []
        original_save = BusinessAttachmentStorageGateway.save_immutable

        def capture_save(instance, **kwargs):
            key = original_save(instance, **kwargs)
            saved_keys.append(key)
            return key

        with patch.object(BusinessAttachmentStorageGateway, "save_immutable", capture_save), \
             patch("core.finance_services._write_public_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                mark_expense_claim_paid(
                    claim=claim, payer_member=payer, evidence_uploads=[_png_upload()],
                    world_id="realworld", require_evidence=True,
                )
        claim.refresh_from_db()
        self.assertEqual(claim.status, claim.Status.APPROVED)
        self.assertFalse(FinanceTransaction.objects.filter(claim=claim).exists())
        self.assertFalse(PaymentExecution.objects.filter(claim=claim).exists())
        self.assertEqual(len(saved_keys), 1)
        self.assertFalse(gateway.exists(saved_keys[0], world_id="realworld"))

    def test_private_read_matrix(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="读取矩阵", description="", amount=10,
            expense_date="2026-08-03",
        )
        reviewer = _finance_member("attach-matrix-reviewer", FINANCE_REVIEW_PERMISSION)
        payer = _finance_member("attach-matrix-payer", FINANCE_PAY_PERMISSION)
        unrelated = create_member("attach-matrix-other")
        self.assertTrue(can_read_private_claim_attachment(member=self.claimant, claim=claim))
        self.assertTrue(can_read_private_claim_attachment(member=reviewer, claim=claim))
        self.assertTrue(can_read_private_claim_attachment(member=payer, claim=claim))
        self.assertFalse(can_read_private_claim_attachment(member=unrelated, claim=claim))

    def test_new_admin_models_are_read_only(self):
        request = type("Request", (), {})()
        for model in (Attachment, ExpenseClaimAttachment, PaymentExecution):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    @override_settings(
        SITE_FIXED_WORLD=True, SITE_WORLD_ID="realworld", SITE_WORLD_DATABASE_ALIAS="default",
        SITE_WORLD_DATABASE_NAME="test", SITE_WORLD_TYPE="real",
    )
    def test_probe_and_audit_commands_are_safe(self):
        for alias in ("business_attachments",):
            storages._storages.pop(alias, None)
        output = StringIO()
        call_command("probe_business_attachment_storage", world_id="realworld", stdout=output)
        self.assertIn("业务附件存储探针通过", output.getvalue())
        orphan = "realworld/runtime/permanent-attachments/orphan"
        storages["business_attachments"].save(orphan, ContentFile(b"orphan"))
        output = StringIO()
        call_command("audit_business_attachment_storage", world_id="realworld", stdout=output)
        self.assertIn("orphan=1", output.getvalue())
        self.assertTrue(storages["business_attachments"].exists(orphan))

    @override_settings(
        SITE_FIXED_WORLD=True, SITE_WORLD_ID="realworld", SITE_WORLD_DATABASE_ALIAS="default",
        SITE_WORLD_DATABASE_NAME="test", SITE_WORLD_TYPE="real",
    )
    def test_smoke_command_completes_the_closure(self):
        reviewer = _finance_member("attach-smoke-reviewer", FINANCE_REVIEW_PERMISSION)
        payer = _finance_member("attach-smoke-payer", FINANCE_PAY_PERMISSION)
        publisher = _finance_member("attach-smoke-publisher", FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION)
        output = StringIO()
        call_command(
            "smoke_expense_reimbursement", world_id="realworld",
            claimant=self.claimant.member_no, reviewer=reviewer.member_no, payer=payer.member_no,
            publisher=publisher.member_no,
            stdout=output,
        )
        self.assertIn("报销闭环通过", output.getvalue())
        claim = self.claimant.expense_claims.get(title="报销闭环探针")
        self.assertEqual(claim.status, claim.Status.PAID)
        self.assertEqual(claim.attachment_links.count(), 3)


class BusinessAttachmentViewTests(TestCase):
    def setUp(self):
        self.claimant = create_member("attach-view-claimant", display_name="申请人", role_name=ROLE_COVENANTER)
        login_as_member(self.client, self.claimant)

    def test_workspace_submission_requires_and_accepts_evidence(self):
        response = self.client.post("/workspace/finance/claims/new/", {
            "title": "真实报销",
            "amount": "100.00",
            "currency": "CNY",
            "expense_date": "2026-08-03",
            "vendor": "公开供应商",
            "category": "server",
            "description": "内部用途",
            "public_note": "服务器月费",
            "evidence_files": _png_upload("private-account-123.png"),
        })
        self.assertEqual(response.status_code, 302)
        claim = self.claimant.expense_claims.get(title="真实报销")
        self.assertEqual(claim.attachment_links.count(), 1)

    def test_private_download_fails_closed_for_unrelated_member(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="私有", description="", amount=10,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("secret.png")],
            world_id="realworld", require_evidence=True,
        )
        attachment = claim.attachment_links.get().attachment
        other = create_member("attach-view-other", role_name=ROLE_COVENANTER)
        login_as_member(self.client, other)
        response = self.client.get(f"/workspace/finance/claims/{claim.claim_id}/attachments/{attachment.attachment_id}/")
        self.assertEqual(response.status_code, 404)

    def test_public_page_never_leaks_private_attachment_metadata(self):
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="公开隐私检查", description="内部备注 token-secret", amount=10,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("private-account-123.png")],
            world_id="realworld", require_evidence=True,
        )
        attachment = claim.attachment_links.get().attachment
        response = self.client.get("/finance/")
        content = response.content.decode()
        self.assertNotIn(attachment.object_key, content)
        self.assertNotIn(attachment.sha256, content)
        self.assertNotIn("private-account-123.png", content)
        self.assertNotIn("token-secret", content)

    def test_public_page_attaches_public_derivative_to_its_claim_card(self):
        publisher = _finance_member(
            "attach-view-card-publisher",
            FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
        )
        published_claim = submit_expense_claim(
            claimant_member=self.claimant, title="带公开材料的报销", description="", amount=10,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("published-private.png")],
            world_id="realworld", require_evidence=True,
        )
        other_claim = submit_expense_claim(
            claimant_member=self.claimant, title="没有公开材料的报销", description="", amount=20,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("other-private.png")],
            world_id="realworld", require_evidence=True,
        )
        public_link = publish_expense_attachment_copy(
            claim=published_claim,
            source_attachment=published_claim.attachment_links.get().attachment,
            uploaded_by=publisher,
            upload=_png_upload("published-redacted.png"),
            world_id="realworld",
        )

        response = self.client.get("/finance/")

        self.assertEqual(response.status_code, 200)
        claims_by_pk = {claim.pk: claim for claim in response.context["claims"]}
        self.assertEqual(
            [link.pk for link in claims_by_pk[published_claim.pk].public_attachment_links],
            [public_link.pk],
        )
        self.assertEqual(claims_by_pk[other_claim.pk].public_attachment_links, [])
        self.assertContains(
            response,
            f'/finance/attachments/{public_link.attachment.attachment_id}/',
            count=1,
        )

    def test_public_derivative_download_is_separate(self):
        publisher = _finance_member("attach-view-publisher", FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION)
        claim = submit_expense_claim(
            claimant_member=self.claimant, title="公开文件", description="", amount=10,
            expense_date="2026-08-03", evidence_uploads=[_png_upload("private.png")],
            world_id="realworld", require_evidence=True,
        )
        source = claim.attachment_links.get().attachment
        public_link = publish_expense_attachment_copy(
            claim=claim, source_attachment=source, uploaded_by=publisher,
            upload=_png_upload("redacted.png"), world_id="realworld",
        )
        response = self.client.get(f"/finance/attachments/{public_link.attachment.attachment_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="public-material"')
