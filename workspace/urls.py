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
]
