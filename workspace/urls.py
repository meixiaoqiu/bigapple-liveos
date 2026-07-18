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
        "proposals/<str:proposal_id>/vote/",
        world_scoped_view(views.workspace_proposal_vote),
        name="workspace-proposal-vote",
    ),
    path(
        "proposals/<str:proposal_id>/execute/",
        world_scoped_view(views.workspace_proposal_execute),
        name="workspace-proposal-execute",
    ),
    path(
        "apply/",
        world_scoped_view(views.workspace_member_application),
        name="workspace-member-application",
    ),
    path(
        "profile/",
        world_scoped_view(views.workspace_public_profile_page),
        name="workspace-public-profile",
    ),
    path(
        "profile/update/",
        world_scoped_view(views.workspace_public_profile_update),
        name="workspace-public-profile-update",
    ),
]
