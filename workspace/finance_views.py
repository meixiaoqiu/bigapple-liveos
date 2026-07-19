"""Workspace finance views — expense claims, review, pay."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.exceptions import DomainError
from core.finance_services import (
    FINANCE_REVIEW_PERMISSION, FINANCE_PAY_PERMISSION,
    mark_expense_claim_paid, review_expense_claim, submit_expense_claim,
    withdraw_expense_claim,
)
from core.models import ExpenseClaim, Member
from live_os.access import is_authenticated, member_for_request
from live_os.error_handlers import permission_denied as _forbidden

from core.permission_services import member_has_permission

from .finance_forms import ExpenseClaimForm, FinanceReviewForm


def _current_member(request: HttpRequest) -> Member | HttpResponse:
    if not is_authenticated(request):
        return redirect_to_login(request.get_full_path(), login_url="/login/")
    m = member_for_request(request)
    if m is None:
        return _forbidden(request, Exception("no member"))
    return m


def _check_permission(member: Member, code: str) -> bool:
    return member_has_permission(member, code)


def _is_finance_operator(member: Member) -> bool:
    return _check_permission(member, FINANCE_REVIEW_PERMISSION) or _check_permission(member, FINANCE_PAY_PERMISSION)


def _can_view_claim(member: Member, claim: ExpenseClaim) -> bool:
    return claim.claimant_member_id == member.pk or _is_finance_operator(member)


@require_GET
def finance_claims_list(request: HttpRequest) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    is_finance = _is_finance_operator(member)
    if is_finance:
        claims = ExpenseClaim.objects.select_related("claimant_member").order_by("-created_at")[:100]
    else:
        claims = ExpenseClaim.objects.filter(claimant_member=member).select_related("claimant_member").order_by("-created_at")
    return render(request, "workspace/finance_claims_list.html", {
        "claims": claims, "is_finance": is_finance, "member": member,
    })


@require_http_methods(["GET", "POST"])
def finance_claim_form(request: HttpRequest) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    if request.method == "POST":
        form = ExpenseClaimForm(request.POST)
        if form.is_valid():
            try:
                claim = submit_expense_claim(
                    claimant_member=member,
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    amount=form.cleaned_data["amount"],
                    currency=form.cleaned_data["currency"],
                    expense_date=form.cleaned_data["expense_date"],
                    vendor=form.cleaned_data["vendor"],
                    category=form.cleaned_data["category"],
                )
            except DomainError as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "报销申请已提交。")
                return redirect("workspace-finance-detail", claim_id=claim.claim_id)
    else:
        form = ExpenseClaimForm()
    return render(request, "workspace/finance_claim_form.html", {"member": member, "form": form})


@require_GET
def finance_claim_detail(request: HttpRequest, claim_id: str) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    claim = get_object_or_404(
        ExpenseClaim.objects.select_related("claimant_member"), claim_id=claim_id,
    )
    if not _can_view_claim(member, claim):
        return _forbidden(request, Exception("finance claim forbidden"))
    is_finance = _check_permission(member, FINANCE_REVIEW_PERMISSION)
    is_payer = _check_permission(member, FINANCE_PAY_PERMISSION)
    is_owner = claim.claimant_member_id == member.pk
    can_review = is_finance and not is_owner
    can_pay = is_payer and not is_owner and claim.status == ExpenseClaim.Status.APPROVED
    can_withdraw = is_owner and claim.status in {ExpenseClaim.Status.SUBMITTED, ExpenseClaim.Status.UNDER_REVIEW}
    reviews = claim.reviews.select_related("reviewer_member").all()
    return render(request, "workspace/finance_claim_detail.html", {
        "claim": claim, "member": member, "reviews": reviews,
        "can_review": can_review, "can_pay": can_pay, "can_withdraw": can_withdraw,
        "review_form": FinanceReviewForm(),
    })


@require_POST
def finance_claim_review(request: HttpRequest, claim_id: str) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    claim = get_object_or_404(ExpenseClaim, claim_id=claim_id)
    form = FinanceReviewForm(request.POST)
    if form.is_valid():
        try:
            review_expense_claim(
                claim=claim,
                reviewer_member=member,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data["reason"],
            )
        except DomainError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "审核完成。")
    else:
        messages.error(request, "请检查审核表单。")
    return redirect("workspace-finance-detail", claim_id=claim_id)


@require_POST
def finance_claim_pay(request: HttpRequest, claim_id: str) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    claim = get_object_or_404(ExpenseClaim, claim_id=claim_id)
    try:
        mark_expense_claim_paid(claim=claim, payer_member=member)
    except DomainError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "已标记为已付款。")
    return redirect("workspace-finance-detail", claim_id=claim_id)


@require_POST
def finance_claim_withdraw(request: HttpRequest, claim_id: str) -> HttpResponse:
    member = _current_member(request)
    if isinstance(member, HttpResponse):
        return member
    claim = get_object_or_404(ExpenseClaim, claim_id=claim_id)
    try:
        withdraw_expense_claim(claim=claim, member=member)
    except DomainError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "已撤回。")
    return redirect("workspace-finance-detail", claim_id=claim_id)
