"""Workspace credit transfer, redemption, fulfillment, and settlement views."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_GET, require_http_methods

from worlds.routing import world_redirect
from live_os.access import is_authenticated, member_for_request, page_forbidden
from core.access import is_governance_principal
from core.exceptions import DomainError
from core.credit_services import (
    cancel_redemption_order,
    create_redemption_order,
    dispute_redemption_order,
    fulfill_redemption_order,
    transfer_member_credits,
)
from core.models import Member, MerchantProfile, MerchantSettlementRecord, RedemptionOrder
from workspace.context import member_has_full_workspace_access, workspace_context


# ── helpers ──────────────────────────────────────────────────────────


def _require_full_workspace(request: HttpRequest) -> Member | HttpResponseForbidden:
    if not is_authenticated(request):
        return page_forbidden("需要登录。")
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要绑定成员身份。")
    if not member_has_full_workspace_access(member):
        return page_forbidden("正式成员以上才能访问此功能。")
    return member


def render_with(request, template, context):
    from django.shortcuts import render
    return render(request, template, context)


# ── transfer ─────────────────────────────────────────────────────────


@require_http_methods(["GET", "POST"])
def credit_transfer_page(request: HttpRequest) -> HttpResponse:
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    from core.credit_services import member_credit_balance
    ctx = {"member": member, "credit_balance": member_credit_balance(member)}

    if request.method == "POST":
        to_member_no = request.POST.get("to_member_no", "").strip()
        amount_str = request.POST.get("amount", "").strip()
        reason = request.POST.get("reason", "").strip()[:256]

        if not to_member_no:
            messages.error(request, "请输入收款成员编号。")
            return render_with(request, "workspace/credits_transfer.html", ctx)
        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            messages.error(request, "积分数量必须是正整数。")
            return render_with(request, "workspace/credits_transfer.html", ctx)

        to_member = Member.objects.filter(member_no=to_member_no).first()
        if to_member is None:
            messages.error(request, f"成员 {to_member_no} 不存在。")
            return render_with(request, "workspace/credits_transfer.html", ctx)
        try:
            transfer_member_credits(
                from_member=member, to_member=to_member,
                amount=amount, reason=reason, initiated_by=member,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return render_with(request, "workspace/credits_transfer.html", ctx)

        messages.success(request, f"成功向 {to_member_no} 转账 {amount} 积分。")
        return world_redirect(request, "workspace-page")

    return render_with(request, "workspace/credits_transfer.html", ctx)


# ── redemption orders (member-facing) ────────────────────────────────


@require_http_methods(["GET", "POST"])
def redemption_orders_page(request: HttpRequest) -> HttpResponse:
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    if request.method == "POST" and "create" in request.POST:
        return _create_order(member, request)
    if request.method == "POST" and "cancel" in request.POST:
        return _cancel_order(member, request)
    if request.method == "POST" and "dispute" in request.POST:
        return _dispute_order(member, request)

    return _redemption_list(member, request)


def _create_order(member, request):
    try:
        credit_amount = int(request.POST.get("credit_amount", "").strip())
    except (ValueError, TypeError):
        messages.error(request, "积分数量必须是正整数。")
        return _redemption_list(member, request)

    item_type = request.POST.get("item_type", "other").strip()
    title = request.POST.get("title", f"兑换 {credit_amount} 积分").strip()[:256]
    merchant_id = request.POST.get("merchant_id", "").strip()

    merchant = None
    if merchant_id:
        merchant = MerchantProfile.objects.filter(merchant_id=merchant_id).first()
        if merchant is None:
            messages.error(request, f"商户 {merchant_id} 不存在。")
            return _redemption_list(member, request)
        if merchant.merchant_type == MerchantProfile.Type.MEMBER_MICRO:
            messages.error(request, "成员微创业商户收款应使用积分转账，不走兑换订单。")
            return _redemption_list(member, request)
        if merchant.status != MerchantProfile.Status.ACTIVE:
            messages.error(request, "指定商户当前非营业中状态。")
            return _redemption_list(member, request)

    try:
        create_redemption_order(
            member=member, credit_amount=credit_amount,
            item_type=item_type, title=title, merchant=merchant, created_by=member,
        )
    except DomainError as exc:
        messages.error(request, str(exc))
        return _redemption_list(member, request)

    messages.success(request, "兑换订单已创建，积分已冻结。")
    return world_redirect(request, "workspace-credits-redemption")


def _cancel_order(member, request):
    order_id = request.POST.get("cancel", "").strip()
    order = RedemptionOrder.objects.filter(order_id=order_id, member=member).first()
    if order is None:
        messages.error(request, "未找到可取消的订单。")
        return _redemption_list(member, request)
    try:
        cancel_redemption_order(order=order, cancelled_by=member)
    except DomainError as exc:
        messages.error(request, str(exc))
        return _redemption_list(member, request)
    messages.success(request, f"订单 {order_id} 已取消，积分已解冻。")
    return world_redirect(request, "workspace-credits-redemption")


def _dispute_order(member, request):
    order_id = request.POST.get("dispute", "").strip()
    order = RedemptionOrder.objects.filter(order_id=order_id, member=member).first()
    if order is None:
        messages.error(request, "未找到可申诉的订单。")
        return _redemption_list(member, request)
    reason = request.POST.get("dispute_reason", "").strip()[:256]
    try:
        dispute_redemption_order(order=order, reason=reason)
    except DomainError as exc:
        messages.error(request, str(exc))
        return _redemption_list(member, request)
    messages.success(request, f"订单 {order_id} 已提交申诉。")
    return world_redirect(request, "workspace-credits-redemption")


def _redemption_list(member, request):
    from django.shortcuts import render

    orders = list(
        RedemptionOrder.objects.filter(member=member)
        .select_related("merchant")
        .order_by("-created_at")[:50]
    )
    # Only active cash_settlement merchants appear in the create-form dropdown
    merchants = list(
        MerchantProfile.objects.filter(
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            status=MerchantProfile.Status.ACTIVE,
        ).order_by("display_name")
    )
    ctx = workspace_context(member.member_no)
    ctx["orders"] = orders
    ctx["merchants"] = merchants
    ctx["member"] = member
    ctx["item_types"] = [v for v, _ in RedemptionOrder.ItemType.choices]
    return render(request, "workspace/credits_redemption.html", ctx)


# ── governance fulfillment ───────────────────────────────────────────


@require_http_methods(["GET", "POST"])
def redemption_review_page(request: HttpRequest) -> HttpResponse:
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if not is_governance_principal(member):
        return page_forbidden("仅治理成员可访问履约页面。")

    if request.method == "POST" and "fulfill" in request.POST:
        order_id = request.POST.get("fulfill", "").strip()
        order = RedemptionOrder.objects.filter(order_id=order_id).first()
        if order is None:
            messages.error(request, "未找到该订单。")
            return _review_list(member, request)
        try:
            fulfill_redemption_order(order=order, reviewed_by=member)
        except DomainError as exc:
            messages.error(request, str(exc))
            return _review_list(member, request)
        messages.success(request, f"订单 {order_id} 已履约，积分已销毁。")
        return world_redirect(request, "workspace-credits-review")

    return _review_list(member, request)


def _review_list(member, request):
    from django.shortcuts import render

    pending = list(
        RedemptionOrder.objects.filter(
            status__in=[RedemptionOrder.Status.PENDING, RedemptionOrder.Status.DISPUTED],
        )
        .select_related("member", "merchant")
        .order_by("-created_at")[:50]
    )
    fulfilled = list(
        RedemptionOrder.objects.filter(status=RedemptionOrder.Status.FULFILLED)
        .select_related("member", "merchant")
        .order_by("-fulfilled_at")[:20]
    )
    ctx = workspace_context(member.member_no)
    ctx["review_orders"] = pending
    ctx["fulfilled_orders"] = fulfilled
    ctx["member"] = member
    return render(request, "workspace/credits_review.html", ctx)


# ── merchant settlements ─────────────────────────────────────────────


@require_GET
def merchant_settlements_page(request: HttpRequest) -> HttpResponse:
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    qs = MerchantSettlementRecord.objects.select_related(
        "merchant", "redemption_order",
    ).order_by("-created_at")
    is_gov = is_governance_principal(member)

    if is_gov:
        # Governance filter
        selected = ""
        merchant_id = request.GET.get("merchant_id", "").strip()
        if merchant_id:
            qs = qs.filter(merchant_id=merchant_id)
            selected = merchant_id
    else:
        operator_merchants = MerchantProfile.objects.filter(
            operator_member=member,
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
        )
        if not operator_merchants.exists():
            return page_forbidden("你不是任何商户的经营者，无法查看商户结算。")
        qs = qs.filter(merchant__in=operator_merchants)
        merchant_id = request.GET.get("merchant_id", "").strip()
        if merchant_id:
            qs = qs.filter(merchant_id=merchant_id)

    records = list(qs[:50])
    ctx = workspace_context(member.member_no)
    ctx["settlements"] = records
    ctx["member"] = member
    ctx["is_governance"] = is_gov
    ctx["selected_merchant_id"] = selected if is_gov else ""
    if is_gov:
        ctx["all_merchants"] = list(
            MerchantProfile.objects.filter(
                merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            ).order_by("display_name")
        )
    return render_with(request, "workspace/credits_settlements.html", ctx)
