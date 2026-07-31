from django.contrib import messages
from django.http import HttpRequest, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods
from worlds.routing import world_redirect
from core.access import is_finance_reviewer, member_can_maintain
from core.exceptions import DomainError
from core.models import RiskAlert, RiskRule
from core.risk_services import acknowledge_risk_alert, resolve_risk_alert, update_risk_rule
from live_os.access import page_forbidden
from .access import require_full_workspace_member


def chk(request):
    return require_full_workspace_member(request)


def gorf(member):
    return not (member_can_maintain(member) or is_finance_reviewer(member))


@require_GET
def risk_list(request):
    member = chk(request)
    if isinstance(member, HttpResponseForbidden): return member
    if gorf(member): return page_forbidden("仅维护者或财务职责成员可访问。")
    alerts = list(RiskAlert.objects.order_by("-severity", "-last_seen_at"))
    return render(request, "workspace/risk_list.html", {"member": member, "alerts": alerts})


@require_http_methods(["POST"])
def risk_ack(request, alert_id):
    member = chk(request)
    if isinstance(member, HttpResponseForbidden): return member
    if gorf(member): return page_forbidden("仅维护者或财务职责成员可访问。")
    alert = get_object_or_404(RiskAlert, alert_id=alert_id)
    try:
        acknowledge_risk_alert(alert, member)
        messages.success(request, f"风险 {alert_id} 已确认。")
    except DomainError as e:
        messages.error(request, str(e))
    return world_redirect(request, "workspace-risks")


@require_http_methods(["POST"])
def risk_resolve(request, alert_id):
    member = chk(request)
    if isinstance(member, HttpResponseForbidden): return member
    if gorf(member): return page_forbidden("仅维护者或财务职责成员可访问。")
    alert = get_object_or_404(RiskAlert, alert_id=alert_id)
    note = request.POST.get("note", "").strip() or "已处理"
    try:
        resolve_risk_alert(alert, member, note)
        messages.success(request, f"风险 {alert_id} 已解除。")
    except DomainError as e:
        messages.error(request, str(e))
    return world_redirect(request, "workspace-risks")


@require_GET
def risk_rules_list(request):
    member = chk(request)
    if isinstance(member, HttpResponseForbidden): return member
    if gorf(member): return page_forbidden("仅维护者或财务职责成员可访问。")
    rules = list(RiskRule.objects.order_by("domain", "-severity"))
    return render(request, "workspace/risk_rule_list.html", {"member": member, "rules": rules})


@require_http_methods(["POST"])
def risk_rule_update(request, rule_id):
    member = chk(request)
    if isinstance(member, HttpResponseForbidden): return member
    if not member_can_maintain(member): return page_forbidden("仅维护者可访问。")
    rule = get_object_or_404(RiskRule, rule_id=rule_id)
    changes = {}
    for key in ["threshold_value", "threshold_operator", "severity", "visibility", "status", "responsible_role"]:
        val = request.POST.get(key, "").strip()
        if val and val != str(getattr(rule, key, "")):
            changes[key] = val
    if not changes:
        return world_redirect(request, "workspace-risk-rules")
    try:
        update_risk_rule(rule, member, **changes)
        messages.success(request, f"规则 {rule_id} 已更新。")
    except DomainError as e:
        messages.error(request, str(e))
    return world_redirect(request, "workspace-risk-rules")
