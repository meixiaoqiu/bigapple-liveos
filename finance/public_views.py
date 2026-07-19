"""Public finance page view."""

from __future__ import annotations

from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.models import ExpenseClaim, FinanceTransaction


@require_GET
def public_finance(request: HttpRequest) -> HttpResponse:
    claims = list(ExpenseClaim.objects.exclude(
        status=ExpenseClaim.Status.WITHDRAWN,
    ).select_related("claimant_member").order_by("-created_at")[:30])
    txns = list(FinanceTransaction.objects.select_related("claim", "recorded_by").order_by("-occurred_at")[:30])
    total_out_by_currency = list(
        FinanceTransaction.objects.filter(direction=FinanceTransaction.Direction.OUT)
        .values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    )
    pending = ExpenseClaim.objects.filter(status=ExpenseClaim.Status.SUBMITTED).count()
    return render(request, "finance/public_finance.html", {
        "claims": claims, "transactions": txns,
        "total_out_by_currency": total_out_by_currency, "pending_count": pending,
    })
