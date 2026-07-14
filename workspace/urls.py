"""URL routes for the workspace."""

from django.urls import path
from worlds.routing import world_scoped_view

from . import views


urlpatterns = [
    path("", world_scoped_view(views.workspace_page), name="workspace-page"),
    path(
        "tasks/<str:task_id>/claim/",
        world_scoped_view(views.workspace_claim_task),
        name="workspace-claim-task",
    ),
    path(
        "tasks/<str:task_id>/submit-labor/",
        world_scoped_view(views.workspace_submit_labor),
        name="workspace-submit-labor",
    ),
    path(
        "disputes/",
        world_scoped_view(views.workspace_create_dispute),
        name="workspace-create-dispute",
    ),
    path(
        "applications/",
        world_scoped_view(views.workspace_applications_review),
        name="workspace-applications-review",
    ),
    path(
        "applications/<str:application_id>/",
        world_scoped_view(views.workspace_application_detail),
        name="workspace-application-detail",
    ),
    path(
        "applications/<str:application_id>/review/",
        world_scoped_view(views.workspace_application_review),
        name="workspace-application-review",
    ),
    path(
        "applications/<str:application_id>/create-admission-proposal/",
        world_scoped_view(views.workspace_application_create_admission_proposal),
        name="workspace-application-create-admission-proposal",
    ),
    path(
        "proposals/<str:proposal_id>/vote/",
        world_scoped_view(views.workspace_proposal_vote),
        name="workspace-proposal-vote",
    ),
    path(
        "proposals/<str:proposal_id>/execute/",
        world_scoped_view(views.workspace_proposal_execute),
        name="workspace-proposal-execute",
    ),
]
