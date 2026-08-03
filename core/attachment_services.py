"""Authority services for immutable business attachments."""

from collections.abc import Iterable

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import router, transaction

from core.exceptions import DomainError
from core.file_processing.business_attachments import process_business_attachment
from core.file_storage.business_gateway import BusinessAttachmentStorageGateway
from core.models import Attachment, ExpenseClaim, ExpenseClaimAttachment, Member, PaymentExecution


def _validate_batch(uploads: Iterable[UploadedFile]) -> list[UploadedFile]:
    items = list(uploads)
    if not items:
        raise DomainError("请至少上传一份凭证。")
    if len(items) > settings.ATTACHMENT_MAX_FILES:
        raise DomainError(f"一次最多上传 {settings.ATTACHMENT_MAX_FILES} 个凭证文件。")
    declared_total = sum(max(0, int(getattr(item, "size", 0) or 0)) for item in items)
    if declared_total > settings.ATTACHMENT_MAX_TOTAL_BYTES:
        raise DomainError("本次凭证文件总大小超过限制。")
    return items


def create_expense_attachments(
    *, claim: ExpenseClaim, uploaded_by: Member, uploads: Iterable[UploadedFile],
    purpose: str, world_id: str, payment_execution: PaymentExecution | None = None,
    audience: str = Attachment.Audience.PRIVATE,
    source_attachment: Attachment | None = None,
    supersedes: Attachment | None = None,
) -> list[ExpenseClaimAttachment]:
    """Validate, store and seal a batch of attachments for one expense claim."""
    items = _validate_batch(uploads)
    processed = [process_business_attachment(item) for item in items]
    if sum(item.size for item in processed) > settings.ATTACHMENT_MAX_TOTAL_BYTES:
        raise DomainError("本次凭证文件总大小超过限制。")
    gateway = BusinessAttachmentStorageGateway()
    created: list[ExpenseClaimAttachment] = []
    saved_keys: list[str] = []
    try:
        database_alias = claim._state.db or router.db_for_write(Attachment)
        with transaction.atomic(using=database_alias):
            for item in processed:
                key = gateway.save_immutable(world_id=world_id, content=item.content)
                saved_keys.append(key)
                attachment = Attachment.objects.create(
                    object_key=key,
                    detected_media_type=item.media_type,
                    display_filename=item.display_filename,
                    byte_size=item.size,
                    sha256=item.sha256,
                    uploaded_by=uploaded_by,
                    audience=audience,
                    source_attachment=source_attachment,
                    supersedes=supersedes,
                )
                created.append(ExpenseClaimAttachment.objects.create(
                    claim=claim,
                    attachment=attachment,
                    purpose=purpose,
                    payment_execution=payment_execution,
                ))
    except Exception:
        for key in saved_keys:
            gateway.delete_uncommitted(key, world_id=world_id)
        raise
    return created


def cleanup_uncommitted_expense_attachments(
    links: Iterable[ExpenseClaimAttachment], *, world_id: str,
) -> None:
    """Compensate object writes whose surrounding database transaction failed."""
    gateway = BusinessAttachmentStorageGateway()
    for link in links:
        gateway.delete_uncommitted(link.attachment.object_key, world_id=world_id)


def publish_expense_attachment_copy(
    *, claim: ExpenseClaim, source_attachment: Attachment, uploaded_by: Member,
    upload: UploadedFile, world_id: str,
) -> ExpenseClaimAttachment:
    """Publish a separately stored, explicitly sourced public derivative."""
    from core.authorization_services import AuthorizationService
    from core.finance_setup import FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION

    if source_attachment.audience != Attachment.Audience.PRIVATE:
        raise DomainError("公开副本的来源必须是私有原件。")
    if not ExpenseClaimAttachment.objects.filter(claim=claim, attachment=source_attachment).exists():
        raise DomainError("来源附件不属于该报销。")
    if not AuthorizationService().member_has_permission(
        uploaded_by, FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
    ):
        raise DomainError("没有发布公开报销材料的权限。")
    return create_expense_attachments(
        claim=claim, uploaded_by=uploaded_by, uploads=[upload],
        purpose=ExpenseClaimAttachment.Purpose.PUBLIC_MATERIAL,
        world_id=world_id, audience=Attachment.Audience.PUBLIC,
        source_attachment=source_attachment,
    )[0]


def correct_expense_attachment(
    *, claim: ExpenseClaim, replaced_attachment: Attachment, uploaded_by: Member,
    upload: UploadedFile, world_id: str,
) -> ExpenseClaimAttachment:
    """Append a correction without overwriting or deleting the sealed original."""
    old_link = ExpenseClaimAttachment.objects.filter(
        claim=claim, attachment=replaced_attachment,
    ).first()
    if old_link is None or replaced_attachment.audience != Attachment.Audience.PRIVATE:
        raise DomainError("只能更正该报销中的私有凭证。")
    if uploaded_by.pk != claim.claimant_member_id and not can_read_private_claim_attachment(member=uploaded_by, claim=claim):
        raise DomainError("没有更正该报销凭证的权限。")
    return create_expense_attachments(
        claim=claim, uploaded_by=uploaded_by, uploads=[upload],
        purpose=old_link.purpose, world_id=world_id,
        payment_execution=old_link.payment_execution,
        supersedes=replaced_attachment,
    )[0]


def can_read_private_claim_attachment(*, member: Member, claim: ExpenseClaim) -> bool:
    if member.pk == claim.claimant_member_id and claim.status != ExpenseClaim.Status.WITHDRAWN:
        return True
    from core.authorization_services import AuthorizationService
    from core.finance_setup import FINANCE_PAY_PERMISSION, FINANCE_REVIEW_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION
    auth = AuthorizationService()
    return any(auth.member_has_permission(member, code) for code in (
        FINANCE_REVIEW_PERMISSION, FINANCE_PAY_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION,
    ))
