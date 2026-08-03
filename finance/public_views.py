"""Public finance page view."""

from __future__ import annotations

from django.db.models import Sum
from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from core.models import Attachment, ExpenseClaim, ExpenseClaimAttachment, FinanceTransaction


@require_GET
def public_finance(request: HttpRequest) -> HttpResponse:
    claims = list(ExpenseClaim.objects.exclude(
        status=ExpenseClaim.Status.WITHDRAWN,
    ).select_related("claimant_member").prefetch_related("reviews__reviewer_member").order_by("-created_at")[:30])
    txns = list(FinanceTransaction.objects.select_related("claim", "recorded_by").order_by("-occurred_at")[:30])
    total_out_by_currency = list(
        FinanceTransaction.objects.filter(direction=FinanceTransaction.Direction.OUT)
        .values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    )
    pending = ExpenseClaim.objects.filter(status=ExpenseClaim.Status.SUBMITTED).count()
    public_links = ExpenseClaimAttachment.objects.filter(
        attachment__audience=Attachment.Audience.PUBLIC,
        claim__in=claims,
    ).select_related("attachment", "claim")
    public_by_claim = {}
    for link in public_links:
        public_by_claim.setdefault(link.claim_id, []).append(link)
    for claim in claims:
        claim.public_attachment_links = public_by_claim.get(claim.pk, [])
    return render(request, "finance/public_finance.html", {
        "claims": claims, "transactions": txns,
        "total_out_by_currency": total_out_by_currency, "pending_count": pending,
    })


@require_GET
def public_finance_attachment(request: HttpRequest, attachment_id: str) -> HttpResponse:
    link = get_object_or_404(
        ExpenseClaimAttachment.objects.select_related("attachment", "claim"),
        attachment__attachment_id=attachment_id,
        attachment__audience=Attachment.Audience.PUBLIC,
    )
    if link.claim.status == ExpenseClaim.Status.WITHDRAWN:
        raise Http404
    from core.file_storage.business_gateway import BusinessAttachmentStorageGateway
    world_id = str(getattr(request, "world_id", "") or getattr(settings, "SITE_WORLD_ID", "") or "realworld")
    stream = BusinessAttachmentStorageGateway().open(link.attachment.object_key, world_id=world_id)
    return FileResponse(stream, as_attachment=True, filename="public-material", content_type=link.attachment.detected_media_type)
