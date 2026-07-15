from functools import wraps

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.urls import path

from . import views


def superuser_admin_view(view_func):
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("Simulation Lab requires superuser permission.")
        return view_func(request, *args, **kwargs)

    return admin.site.admin_view(wrapper)


urlpatterns = [
    path("", superuser_admin_view(views.lab_index), name="simulation-lab-page"),
    path("snapshots/", superuser_admin_view(views.lab_snapshot_list), name="simulation-lab-snapshot-list"),
    path(
        "snapshots/<str:snapshot_id>/",
        superuser_admin_view(views.lab_snapshot_detail),
        name="simulation-lab-snapshot-detail",
    ),
    path(
        "snapshots/<str:snapshot_id>/verify/",
        superuser_admin_view(views.lab_verify_snapshot),
        name="simulation-lab-verify-snapshot",
    ),
    path("advance/", superuser_admin_view(views.lab_advance), name="simulation-lab-advance"),
    path(
        "run-until-failure/",
        superuser_admin_view(views.lab_run_until_failure),
        name="simulation-lab-run-until-failure",
    ),
    path(
        "runs/<str:run_id>/",
        superuser_admin_view(views.lab_run_detail),
        name="simulation-lab-run-detail",
    ),
    path(
        "runs/<str:run_id>/archive/",
        superuser_admin_view(views.lab_archive_run),
        name="simulation-lab-archive-run",
    ),
    path(
        "runs/<str:run_id>/abort/",
        superuser_admin_view(views.lab_abort_run),
        name="simulation-lab-abort-run",
    ),
    path(
        "runs/<str:run_id>/change-sets/<str:change_set_id>/apply/",
        superuser_admin_view(views.lab_apply_change_set),
        name="simulation-lab-apply-change-set",
    ),
    path(
        "runs/<str:run_id>/change-sets/<str:change_set_id>/reject/",
        superuser_admin_view(views.lab_reject_change_set),
        name="simulation-lab-reject-change-set",
    ),
    path(
        "runs/<str:run_id>/discard/",
        superuser_admin_view(views.lab_discard_run),
        name="simulation-lab-discard-run",
    ),
    path(
        "reset-world/",
        superuser_admin_view(views.lab_reset_world),
        name="simulation-lab-reset-world",
    ),
]
