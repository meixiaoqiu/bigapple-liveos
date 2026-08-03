"""Run a real reimbursement closure with four explicitly named members."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from core.attachment_services import publish_expense_attachment_copy
from core.finance_services import mark_expense_claim_paid, review_expense_claim, submit_expense_claim
from core.models import ExpenseClaimAttachment, Member
from worlds.command_context import command_world_context


def _probe_png(name: str) -> SimpleUploadedFile:
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class Command(BaseCommand):
    help = "使用四个明确成员验证报销、审核、付款、流水和公开副本闭环。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)
        parser.add_argument("--claimant", required=True)
        parser.add_argument("--reviewer", required=True)
        parser.add_argument("--payer", required=True)
        parser.add_argument("--publisher", required=True)

    def handle(self, *args, **options):
        member_nos = [options["claimant"], options["reviewer"], options["payer"], options["publisher"]]
        if len(set(member_nos)) != 4:
            raise CommandError("申请人、审核人、付款人和公开发布人必须是四个不同成员。")
        with command_world_context(options["world_id"], command_name="smoke_expense_reimbursement") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            members = {member.member_no: member for member in Member.objects.filter(member_no__in=member_nos)}
            if len(members) != 4:
                raise CommandError("目标 world 中缺少指定成员。")
            claim = submit_expense_claim(
                claimant_member=members[options["claimant"]], title="报销闭环探针",
                description="自动验收生成的 100 元服务器账单。", public_note="服务器账单",
                amount="100.00", currency="CNY", expense_date="2026-08-03",
                vendor="测试供应商", category="server",
                evidence_uploads=[_probe_png("expense-evidence.png")],
                world_id=world.world_id, require_evidence=True,
            )
            review_expense_claim(claim=claim, reviewer_member=members[options["reviewer"]], decision="approved", reason="凭证完整")
            transaction = mark_expense_claim_paid(
                claim=claim, payer_member=members[options["payer"]],
                payment_date="2026-08-03", payment_method="人工转账",
                evidence_uploads=[_probe_png("payment-evidence.png")],
                world_id=world.world_id, require_evidence=True,
            )
            source = claim.attachment_links.filter(purpose=ExpenseClaimAttachment.Purpose.EXPENSE_EVIDENCE).first().attachment
            public_link = publish_expense_attachment_copy(
                claim=claim, source_attachment=source,
                uploaded_by=members[options["publisher"]],
                upload=_probe_png("redacted-public.png"), world_id=world.world_id,
            )
        self.stdout.write(self.style.SUCCESS(
            f"报销闭环通过：claim_id={claim.claim_id} transaction_id={transaction.transaction_id} "
            f"public_attachment_id={public_link.attachment.attachment_id}"
        ))
