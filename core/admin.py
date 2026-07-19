"""Django Admin entrypoint for the internal maintenance backend.

The actual ModelAdmin classes are split by maintenance domain. This module is
kept as the Django autodiscovery entrypoint and as a compatibility import
surface for tests and debugging snippets that import Admin classes directly.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin


admin.site.site_header = "大苹果 Live OS 管理后台"
admin.site.site_title = "大苹果 Live OS"
admin.site.index_title = "系统管理"
admin.site.empty_value_display = "未设置"


from .admin_events import LedgerEntryAdmin, SystemEventAdmin
from .admin_applications import MemberApplicationAdmin, PartnerApplicationAdmin
from .admin_identity import (
    ActiveRoleListFilter,
    MemberAdmin,
    OrganizationAdmin,
    PermissionAdmin,
    RoleAdmin,
    RoleAssignmentAdmin,
    RolePermissionAdmin,
)
from .admin_proposals import (
    ProposalAdmin,
    ProposalExecutionAdmin,
    ProposalVoteAdmin,
)
from .admin_operations import DisputeAdmin, ResourceAdmin, ResourceTransactionAdmin, SupplierQuoteAdmin, TaskAdmin
from .admin_finance import ExpenseClaimAdmin, FinanceReviewAdmin, FinanceTransactionAdmin


TECHNICAL_ADMIN_OBJECTS = {
    "SystemEvent": 10,
    "LedgerEntry": 20,
}
SIMULATION_ADMIN_OBJECTS = {
    "SimulationSnapshot": 10,
    "SimulationSnapshotItem": 20,
    "SimulationRunDisposition": 30,
}
SIMULATION_LAB_ADMIN_LINK = {
    "name": "仿真实验后台",
    "object_name": "SimulationLab",
    "perms": {"add": False, "change": False, "delete": False, "view": True},
    "admin_url": "/admin/simulation-lab/",
    "add_url": None,
    "view_only": True,
    "_admin_order": 40,
}
_default_get_app_list = admin.site.get_app_list


def grouped_admin_get_app_list(request, app_label=None):
    if getattr(settings, "SITE_ROLE", "legacy") in {"real", "simulation"}:
        return _default_get_app_list(request, app_label)

    app_list = _default_get_app_list(request, app_label)

    technical_models = []
    simulation_models = []
    regrouped_apps = []
    for app in app_list:
        remaining_models = []
        for model in app["models"]:
            object_name = model.get("object_name")
            technical_order = TECHNICAL_ADMIN_OBJECTS.get(object_name)
            simulation_order = SIMULATION_ADMIN_OBJECTS.get(object_name)
            if app.get("app_label") == "core" and technical_order is not None:
                model = {**model, "_admin_order": technical_order}
                technical_models.append(model)
            elif app.get("app_label") == "core" and simulation_order is not None:
                model = {**model, "_admin_order": simulation_order}
                simulation_models.append(model)
            else:
                remaining_models.append(model)
        if remaining_models:
            regrouped_apps.append({**app, "models": remaining_models})

    technical_models.sort(key=lambda model: (model["_admin_order"], model["name"]))
    simulation_models.sort(key=lambda model: (model["_admin_order"], model["name"]))
    if app_label is None and getattr(request.user, "is_superuser", False):
        simulation_models.append(dict(SIMULATION_LAB_ADMIN_LINK))
        simulation_models.sort(key=lambda model: (model["_admin_order"], model["name"]))
    for model in technical_models:
        model.pop("_admin_order", None)
    for model in simulation_models:
        model.pop("_admin_order", None)

    if app_label is not None:
        if technical_models:
            regrouped_apps.append(
                {
                    "name": "技术审计与配置",
                    "app_label": "core",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": technical_models,
                }
            )
        if simulation_models:
            regrouped_apps.append(
                {
                    "name": "仿真",
                    "app_label": "core",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": simulation_models,
                }
            )
        return regrouped_apps

    if simulation_models:
        regrouped_apps.insert(
            0,
            {
                "name": "仿真",
                "app_label": "simulation_admin",
                "app_url": "",
                "has_module_perms": True,
                "models": simulation_models,
            },
        )
    if technical_models:
        regrouped_apps.insert(
            0,
            {
                "name": "技术审计与配置",
                "app_label": "technical_admin",
                "app_url": "",
                "has_module_perms": True,
                "models": technical_models,
            },
        )
    return regrouped_apps


admin.site.get_app_list = grouped_admin_get_app_list
