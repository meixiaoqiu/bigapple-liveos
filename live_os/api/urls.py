"""API routes matching `bigapple-docs/static/technical-contracts/openapi/live-os.v0.1.openapi.json`."""

from django.urls import path

from . import capacity, event_feedbacks, events, ledger, members, merchants, redemption_orders, resources, tasks


urlpatterns = [
    path("members/<str:member_no>", members.get_member, name="get-member"),
    path("members/<str:member_no>/workspace", members.get_workspace_summary, name="get-workspace-summary"),
    path("members/<str:member_no>/credit-transfers", members.post_credit_transfer, name="post-credit-transfer"),
    path("members/<str:member_no>/redemption-orders", redemption_orders.list_create_redemption_orders, name="list-create-redemption-orders"),
    path("redemption-orders/<str:order_id>/cancel", redemption_orders.cancel_redemption_order_view, name="cancel-redemption-order"),
    path("redemption-orders/<str:order_id>/issue", redemption_orders.report_redemption_order_issue_view, name="report-redemption-order-issue"),
    path("redemption-orders/<str:order_id>/fulfill", redemption_orders.fulfill_redemption_order_view, name="fulfill-redemption-order"),
    path("merchant-settlements", merchants.list_settlements, name="list-merchant-settlements"),
    path("tasks", tasks.list_tasks, name="list-tasks"),
    path("tasks/<str:task_id>/claim", tasks.claim_task_view, name="claim-task"),
    path("tasks/<str:task_id>/submit-labor", tasks.submit_labor_view, name="submit-labor"),
    path("tasks/<str:task_id>/review", tasks.review_task_view, name="review-task"),
    path("ledger-entries", ledger.list_ledger_entries, name="list-ledger-entries"),
    path("resources", resources.list_resources, name="list-resources"),
    path("event-feedbacks", event_feedbacks.create_event_feedback, name="create-event-feedback"),
    path("events", events.list_events, name="list-events"),
    path(
        "capacity-assessments/latest",
        capacity.latest_capacity_assessment,
        name="latest-capacity-assessment",
    ),
]
