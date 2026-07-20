"""API routes matching `bigapple-docs/technical-contracts/openapi/live-os.v0.1.openapi.json`."""

from django.urls import path

from . import capacity, disputes, events, ledger, members, resources, tasks


urlpatterns = [
    path("members/<str:member_no>", members.get_member, name="get-member"),
    path("members/<str:member_no>/workspace", members.get_workspace_summary, name="get-workspace-summary"),
    path("tasks", tasks.list_tasks, name="list-tasks"),
    path("tasks/<str:task_id>/claim", tasks.claim_task_view, name="claim-task"),
    path("tasks/<str:task_id>/submit-labor", tasks.submit_labor_view, name="submit-labor"),
    path("tasks/<str:task_id>/review", tasks.review_task_view, name="review-task"),
    path("ledger-entries", ledger.list_ledger_entries, name="list-ledger-entries"),
    path("resources", resources.list_resources, name="list-resources"),
    path("disputes", disputes.create_dispute, name="create-dispute"),
    path("events", events.list_events, name="list-events"),
    path(
        "capacity-assessments/latest",
        capacity.latest_capacity_assessment,
        name="latest-capacity-assessment",
    ),
]
