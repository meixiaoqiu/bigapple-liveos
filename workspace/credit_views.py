"""Workspace credit transfer, redemption, fulfillment, and settlement views."""

from __future__ import annotations

from uuid import uuid4

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_GET, require_http_methods

from worlds.routing import world_redirect
from live_os.access import page_forbidden
from core.access import member_can_administer
from core.exceptions import DomainError
from core.credit_services import (
    cancel_redemption_order,
    create_redemption_order,
    report_redemption_order_issue,
    ensure_system_accounts,
    fulfill_redemption_order,
    transfer_member_credits,
)
from core.models import (
    CreditAccount,
    CreditTransaction,
    Member,
    MerchantProfile,
    MerchantSettlementRecord,
    RedemptionOrder,
    Task,
)
from workspace.access import require_full_workspace_member
from workspace.context import workspace_context


# ── helpers ──────────────────────────────────────────────────────────


def _require_full_workspace(request: HttpRequest) -> Member | HttpResponseForbidden:
    return require_full_workspace_member(request)


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
    if request.method == "POST" and "report_issue" in request.POST:
        return _report_order_issue(member, request)

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


def _report_order_issue(member, request):
    order_id = request.POST.get("report_issue", "").strip()
    order = RedemptionOrder.objects.filter(order_id=order_id, member=member).first()
    if order is None:
        messages.error(request, "未找到可申诉的订单。")
        return _redemption_list(member, request)
    reason = request.POST.get("issue_reason", "").strip()[:256]
    try:
        report_redemption_order_issue(order=order, reason=reason)
    except DomainError as exc:
        messages.error(request, str(exc))
        return _redemption_list(member, request)
    messages.success(request, f"订单 {order_id} 已报告履约问题。")
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
    if not member_can_administer(member):
        return page_forbidden("仅管理员可访问履约页面。")

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
    is_gov = member_can_administer(member)

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


# ── issuance pool & task budget ───────────────────────────────────────


@require_http_methods(["GET", "POST"])
def budgets_page(request: HttpRequest) -> HttpResponse:
    """管理员专用：发行池余额与任务预算锁定、退回。"""
    member = _require_full_workspace(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if not member_can_administer(member):
        return page_forbidden("仅管理员可访问积分预算页面。")

    ensure_system_accounts()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "issue":
            return _handle_issue(member, request)
        if action == "lock":
            return _handle_lock(member, request)
        if action == "unlock":
            return _handle_unlock(member, request)

    return _budgets_page(member, request)


def _parse_int_post(request, field):
    val = request.POST.get(field, "").strip()
    try:
        amount = int(val)
        if amount <= 0:
            raise ValueError
        return amount
    except (ValueError, TypeError):
        raise DomainError(f"{field} 必须是正整数。")


def _handle_issue(member, request):
    try:
        amount = _parse_int_post(request, "amount")
    except DomainError as e:
        messages.error(request, str(e))
        return _budgets_page(member, request)

    reason = request.POST.get("reason", "").strip()[:256]
    idem_key = request.POST.get("idempotency_key", "").strip()
    if not idem_key:
        messages.error(request, "缺少幂等键，请刷新页面后重试。")
        return _budgets_page(member, request)

    try:
        from core.credit_services import issue_credits_to_pool
        issue_credits_to_pool(
            amount=amount, reason=reason,
            initiated_by=member, reviewed_by=member,
            idempotency_key=idem_key,
        )
    except DomainError as exc:
        messages.error(request, str(exc))
        return _budgets_page(member, request)

    messages.success(request, f"成功发行 {amount} 积分到公共发行池。")
    return world_redirect(request, "workspace-credits-budgets")


def _handle_lock(member, request):
    try:
        amount = _parse_int_post(request, "amount")
    except DomainError as e:
        messages.error(request, str(e))
        return _budgets_page(member, request)

    task_id = request.POST.get("task_id", "").strip()
    if not task_id:
        messages.error(request, "请输入任务 ID。")
        return _budgets_page(member, request)

    task = Task.objects.filter(task_id=task_id).first()
    if task is None:
        messages.error(request, f"任务 {task_id} 不存在。")
        return _budgets_page(member, request)

    reason = request.POST.get("reason", "").strip()[:256]
    idem_key = request.POST.get("idempotency_key", "").strip()
    if not idem_key:
        messages.error(request, "缺少幂等键，请刷新页面后重试。")
        return _budgets_page(member, request)

    try:
        from core.credit_services import lock_task_credit_budget
        lock_task_credit_budget(
            task=task, amount=amount, reason=reason,
            initiated_by=member, idempotency_key=idem_key,
        )
    except DomainError as exc:
        messages.error(request, str(exc))
        return _budgets_page(member, request)

    messages.success(request, f"成功为任务 {task_id} 锁定 {amount} 积分预算。")
    return world_redirect(request, "workspace-credits-budgets")


def _handle_unlock(member, request):
    try:
        amount = _parse_int_post(request, "amount")
    except DomainError as e:
        messages.error(request, str(e))
        return _budgets_page(member, request)

    task_id = request.POST.get("task_id", "").strip()
    if not task_id:
        messages.error(request, "请输入任务 ID。")
        return _budgets_page(member, request)

    task = Task.objects.filter(task_id=task_id).first()
    if task is None:
        messages.error(request, f"任务 {task_id} 不存在。")
        return _budgets_page(member, request)

    reason = request.POST.get("reason", "").strip()[:256]
    idem_key = request.POST.get("idempotency_key", "").strip()
    if not idem_key:
        messages.error(request, "缺少幂等键，请刷新页面后重试。")
        return _budgets_page(member, request)

    try:
        from core.credit_services import unlock_unused_task_credit_budget
        unlock_unused_task_credit_budget(
            task=task, amount=amount, reason=reason,
            initiated_by=member, idempotency_key=idem_key,
        )
    except DomainError as exc:
        messages.error(request, str(exc))
        return _budgets_page(member, request)

    messages.success(request, f"成功从任务 {task_id} 退回 {amount} 积分到发行池。")
    return world_redirect(request, "workspace-credits-budgets")


def _budgets_page(member, request):
    from django.shortcuts import render
    from core.credit_services import credit_balance, task_locked_credit_balance

    pool = CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).first()
    task_locked = CreditAccount.objects.filter(account_type=CreditAccount.Type.TASK_LOCKED).first()

    ctx = workspace_context(member.member_no)
    ctx["member"] = member
    ctx["issue_key"] = f"budget-issue:{uuid4().hex}"
    ctx["lock_key"] = f"budget-lock:{uuid4().hex}"
    ctx["unlock_key"] = f"budget-unlock:{uuid4().hex}"
    ctx["pool_balance"] = credit_balance(pool) if pool else 0
    ctx["task_locked_balance"] = credit_balance(task_locked) if task_locked else 0

    # Recent records (pool None guard for pre-initialization state)
    ctx["recent_issuance"] = list(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            target_account=pool,
        ).order_by("-created_at")[:10]
    ) if pool else []
    ctx["recent_locks"] = list(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
        ).select_related("related_task").order_by("-created_at")[:10]
    )
    ctx["recent_unlocks"] = list(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
        ).select_related("related_task").order_by("-created_at")[:10]
    )

    # Tasks with locked budget
    all_tasks = list(
        Task.objects.filter(
            status__in=["open", "claimed", "in_progress", "pending_review"],
        ).order_by("task_id")[:50]
    )
    task_budgets = []
    for t in all_tasks:
        locked = task_locked_credit_balance(t)
        if locked > 0 or t.base_points > 0:
            task_budgets.append({"task": t, "locked": locked})
    ctx["task_budgets"] = task_budgets

    return render(request, "workspace/credits_budgets.html", ctx)
