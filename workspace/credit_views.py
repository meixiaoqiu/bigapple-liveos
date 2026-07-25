"""Workspace credit transfer and redemption order views."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

from worlds.routing import world_redirect
from live_os.access import is_authenticated, member_for_request, page_forbidden
from core.exceptions import DomainError
from core.credit_services import (
    cancel_redemption_order,
    create_redemption_order,
    dispute_redemption_order,
    transfer_member_credits,
)
from core.models import Member, RedemptionOrder
from workspace.context import member_has_full_workspace_access, workspace_context


def _require_full_workspace(request: HttpRequest) -> Member | HttpResponseForbidden:
    """Return the request's bound Member, or 403 if not a full workspace user."""
    if not is_authenticated(request):
        return page_forbidden("需要登录。")
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要绑定成员身份。")
    if not member_has_full_workspace_access(member):
        return page_forbidden("正式成员以上才能访问此功能。")
    return member


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


@require_http_methods(["GET", "POST"])
def redemption_orders_page(request: HttpRequest) -> HttpResponse:
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    # ── POST: create order ──────────────────────────────────────
    if request.method == "POST" and "create" in request.POST:
        try:
            credit_amount = int(request.POST.get("credit_amount", "").strip())
        except (ValueError, TypeError):
            messages.error(request, "积分数量必须是正整数。")
            return _redemption_list(member, request)

        item_type = request.POST.get("item_type", "other").strip()
        title = request.POST.get("title", f"兑换 {credit_amount} 积分").strip()[:256]

        try:
            create_redemption_order(
                member=member, credit_amount=credit_amount,
                item_type=item_type, title=title, created_by=member,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return _redemption_list(member, request)

        messages.success(request, "兑换订单已创建，积分已冻结。")
        return world_redirect(request, "workspace-credits-redemption")

    # ── POST: cancel ────────────────────────────────────────────
    if request.method == "POST" and "cancel" in request.POST:
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

    # ── POST: dispute ───────────────────────────────────────────
    if request.method == "POST" and "dispute" in request.POST:
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

    return _redemption_list(member, request)


def _redemption_list(member, request):
    from django.shortcuts import render

    orders = list(
        RedemptionOrder.objects.filter(member=member)
        .select_related("merchant")
        .order_by("-created_at")[:50]
    )
    ctx = workspace_context(member.member_no)
    ctx["orders"] = orders
    ctx["member"] = member
    ctx["item_types"] = [v for v, _ in RedemptionOrder.ItemType.choices]
    return render(request, "workspace/credits_redemption.html", ctx)


def render_with(request, template, context):
    """Shorthand to avoid importing ``render`` in multiple call-sites."""
    from django.shortcuts import render

    return render(request, template, context)
