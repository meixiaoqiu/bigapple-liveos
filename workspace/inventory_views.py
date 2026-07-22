"""Resource inventory maintenance views for the member workspace."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods
from django.utils import timezone

from worlds.routing import world_redirect

from core.access import is_governance_principal
from core.exceptions import DomainError
from core.models import Member, Resource
from core.resource_services import record_resource_adjustment
from live_os.access import member_for_request

from .context import member_has_full_workspace_access


def _check_member(request: HttpRequest) -> Member | None:
    """Return member if authenticated and with full workspace access, else None."""
    member = member_for_request(request)
    if member is None:
        return None
    if not member_has_full_workspace_access(member):
        return None
    return member


def _governance_or_forbidden(member: Member) -> bool:
    return not is_governance_principal(member)


_RESOURCE_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# helpers shared across inventory views
# ---------------------------------------------------------------------------

def _inventory_choices() -> dict:
    """Return TextChoices needed by inventory forms."""
    return {
        "resource_types": Resource.ResourceType.choices,
        "statuses": Resource.Status.choices,
        "units": Resource.Unit.choices,
        "replenishment_methods": Resource.ReplenishmentMethod.choices,
    }


def _resource_form_initial(resource: Resource | None = None) -> dict:
    """Build initial form data dict from an existing Resource, or empty defaults."""
    if resource is None:
        return {}
    return {
        "resource_id": resource.resource_id,
        "name": resource.name,
        "resource_type": resource.resource_type,
        "status": resource.status,
        "unit": resource.unit,
        "current_stock": str(resource.current_stock),
        "daily_consumption_estimate": str(resource.daily_consumption_estimate),
        "warning_threshold": str(resource.warning_threshold),
        "loss_rate": str(resource.loss_rate),
        "replenishment_method": resource.replenishment_method,
        "location": resource.location,
        "description": resource.description,
        "rule_version": resource.rule_version,
        "accepts_offers": getattr(resource, "accepts_offers", True),
    }


def _parse_resource_form(
    request: HttpRequest,
    *,
    include_current_stock: bool,
) -> tuple[dict, list[str]]:
    """Parse and validate shared resource form fields from POST data.

    Returns ``(data, errors)``.  *data* is a dict of cleaned field values.
    ``resource_id`` is **not** parsed by this function – callers handle it
    separately.

    When *include_current_stock* is ``False`` the ``current_stock`` key is
    omitted from the returned dict entirely.
    """
    data = {
        key: request.POST.get(key, "").strip()
        for key in (
            "name",
            "resource_type",
            "status",
            "unit",
            "replenishment_method",
            "location",
            "description",
            "rule_version",
        )
    }
    errors: list[str] = []

    # --- required text fields ------------------------------------------------
    for required in ("resource_type", "unit", "replenishment_method", "rule_version"):
        if not data[required]:
            errors.append(f"{required} 不能为空。")

    if not data["status"]:
        data["status"] = Resource.Status.ACTIVE

    # --- choice validation ---------------------------------------------------
    _validate_choice("resource_type", data["resource_type"], Resource.ResourceType, errors)
    _validate_choice("status", data["status"], Resource.Status, errors)
    _validate_choice("unit", data["unit"], Resource.Unit, errors)
    _validate_choice("replenishment_method", data["replenishment_method"], Resource.ReplenishmentMethod, errors)

    # --- decimal parsing -----------------------------------------------------
    def _parse_decimal(name: str) -> Decimal | None:
        val = request.POST.get(name, "").strip()
        if not val:
            return None
        try:
            return Decimal(val)
        except Exception:
            errors.append(f"{name} 必须是数字。")
            return None

    daily_consumption = _parse_decimal("daily_consumption_estimate")
    warning_threshold = _parse_decimal("warning_threshold")
    loss_rate = _parse_decimal("loss_rate")

    if daily_consumption is None:
        daily_consumption = Decimal("0")
    if warning_threshold is None:
        warning_threshold = Decimal("0")
    if loss_rate is None:
        loss_rate = Decimal("0")

    if warning_threshold < 0:
        errors.append("warning_threshold 不能为负数。")
    if daily_consumption < 0:
        errors.append("daily_consumption_estimate 不能为负数。")
    if loss_rate < 0:
        errors.append("loss_rate 不能为负数。")

    data["daily_consumption_estimate"] = daily_consumption
    data["warning_threshold"] = warning_threshold
    data["loss_rate"] = loss_rate

    current_stock = None
    if include_current_stock:
        current_stock = _parse_decimal("current_stock")
        if current_stock is None:
            current_stock = Decimal("0")
        if current_stock < 0:
            errors.append("current_stock 不能为负数。")
        data["current_stock"] = current_stock

    return data, errors


def _validate_choice(
    field_name: str,
    value: str,
    choices_cls: type,
    errors: list[str],
) -> None:
    """Append an error to *errors* if *value* is non-empty and invalid."""
    if not value:
        return
    valid = {v for v, _ in choices_cls.choices}
    if value not in valid:
        errors.append(f"{field_name} 值无效。")


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------


@require_GET
def inventory_list(request: HttpRequest) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    resources = list(Resource.objects.order_by("resource_type", "resource_id")[:_RESOURCE_LIST_LIMIT])
    low_stock = [r for r in resources if r.current_stock <= r.warning_threshold]

    return render(
        request,
        "workspace/inventory_list.html",
        {
            "member": member,
            "resources": resources,
            "low_stock": low_stock,
        },
    )


@require_http_methods(["GET", "POST"])
def inventory_adjust(request: HttpRequest, resource_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    resource = get_object_or_404(Resource, resource_id=resource_id)

    if request.method == "POST":
        return _handle_adjust_post(request, member, resource)

    return render(
        request,
        "workspace/inventory_adjust.html",
        {
            "member": member,
            "resource": resource,
            "replenishment_choices": Resource.ReplenishmentMethod.choices,
        },
    )


def _handle_adjust_post(request: HttpRequest, member: Member, resource: Resource) -> HttpResponse:
    delta_str = request.POST.get("delta", "").strip()
    reason = request.POST.get("reason", "").strip()
    replenishment_method = request.POST.get("replenishment_method", "").strip()

    errors = []
    if not delta_str:
        errors.append("调整量不能为空。")
    try:
        delta = Decimal(delta_str)
    except Exception:
        errors.append("调整量必须是数字。")
        delta = None

    if not reason:
        errors.append("调整原因不能为空。")
    if not replenishment_method:
        errors.append("请选择补充方式。")

    if errors:
        return render(
            request,
            "workspace/inventory_adjust.html",
            {
                "member": member,
                "resource": resource,
                "replenishment_choices": Resource.ReplenishmentMethod.choices,
                "errors": errors,
                "form_delta": delta_str,
                "form_reason": reason,
                "form_method": replenishment_method,
            },
            status=400,
        )

    operator = {
        "actor_id": member.member_no,
        "display_name": member.display_name or member.member_no,
        "role": "governance_principal",
    }

    try:
        record_resource_adjustment(
            resource=resource,
            delta=delta,
            operator=operator,
            reason=reason,
            replenishment_method=replenishment_method,
            simulation_day=getattr(request, "simulation_day", 1),
        )
    except DomainError as exc:
        return render(
            request,
            "workspace/inventory_adjust.html",
            {
                "member": member,
                "resource": resource,
                "replenishment_choices": Resource.ReplenishmentMethod.choices,
                "errors": [str(exc)],
                "form_delta": delta_str,
                "form_reason": reason,
                "form_method": replenishment_method,
            },
            status=400,
        )

    messages.success(request, "库存调整成功。")
    return world_redirect(request, "workspace-inventory")


@require_http_methods(["GET", "POST"])
def inventory_new(request: HttpRequest) -> HttpResponse:
    """Create a new resource (ledger entry, not a stock transaction)."""
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    choices = _inventory_choices()

    if request.method == "POST":
        return _handle_new_post(request, choices)

    return render(
        request,
        "workspace/inventory_form.html",
        {**choices, "member": member, "mode": "new", "errors": [], "form_data": {}},
    )


def _handle_new_post(request: HttpRequest, choices: dict) -> HttpResponse:
    resource_id = request.POST.get("resource_id", "").strip()
    if not resource_id:
        form_data = {"resource_id": ""}
        return render(
            request,
            "workspace/inventory_form.html",
            {**choices, "member": _check_member(request),
             "mode": "new", "errors": ["resource_id 不能为空。"], "form_data": form_data},
            status=400,
        )

    data, errors = _parse_resource_form(request, include_current_stock=True)

    if errors:
        form_data = {"resource_id": resource_id, **data}
        return render(
            request,
            "workspace/inventory_form.html",
            {**choices, "member": _check_member(request),
             "mode": "new", "errors": errors, "form_data": form_data},
            status=400,
        )

    if Resource.objects.filter(resource_id=resource_id).exists():
        form_data = {"resource_id": resource_id, **data}
        return render(
            request,
            "workspace/inventory_form.html",
            {**choices, "member": _check_member(request),
             "mode": "new", "errors": ["资源 ID 已存在，请更换 ID。"], "form_data": form_data},
            status=400,
        )

    Resource.objects.create(
        resource_id=resource_id,
        name=data["name"] or resource_id,
        resource_type=data["resource_type"],
        status=data["status"],
        unit=data["unit"],
        current_stock=data["current_stock"],
        daily_consumption_estimate=data["daily_consumption_estimate"],
        warning_threshold=data["warning_threshold"],
        loss_rate=data["loss_rate"],
        replenishment_method=data["replenishment_method"],
        location=data["location"] or "",
        description=data["description"] or "",
        rule_version=data["rule_version"],
        accepts_offers=request.POST.get("accepts_offers", "") == "1",
        updated_at=timezone.now(),
    )

    messages.success(request, "资源新建成功。")
    return world_redirect(request, "workspace-inventory")


@require_http_methods(["GET", "POST"])
def inventory_edit(request: HttpRequest, resource_id: str) -> HttpResponse:
    """Edit resource ledger fields (not stock quantity).

    Stock changes must go through ``inventory_adjust`` →
    ``record_resource_adjustment`` so that every stock movement is recorded
    via ``ResourceTransaction``.
    """
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    resource = get_object_or_404(Resource, resource_id=resource_id)
    choices = _inventory_choices()

    if request.method == "POST":
        data, errors = _parse_resource_form(request, include_current_stock=False)

        if errors:
            form_data = {"resource_id": resource.resource_id, **data}
            return render(
                request,
                "workspace/inventory_form.html",
                {
                    **choices,
                    "member": member,
                    "mode": "edit",
                    "errors": errors,
                    "form_data": form_data,
                    "resource": resource,
                },
                status=400,
            )

        # Update allowed ledger fields only – current_stock is never touched.
        resource.name = data["name"] or resource.resource_id
        resource.resource_type = data["resource_type"]
        resource.status = data["status"]
        resource.unit = data["unit"]
        resource.daily_consumption_estimate = data["daily_consumption_estimate"]
        resource.warning_threshold = data["warning_threshold"]
        resource.loss_rate = data["loss_rate"]
        resource.replenishment_method = data["replenishment_method"]
        resource.location = data["location"] or ""
        resource.description = data["description"] or ""
        resource.rule_version = data["rule_version"]
        resource.accepts_offers = request.POST.get("accepts_offers", "") == "1"
        resource.updated_at = timezone.now()
        resource.save()

        messages.success(request, "资源资料已更新。")
        return world_redirect(request, "workspace-inventory")

    form_data = _resource_form_initial(resource)
    return render(
        request,
        "workspace/inventory_form.html",
        {
            **choices,
            "member": member,
            "mode": "edit",
            "errors": [],
            "form_data": form_data,
            "resource": resource,
        },
    )
