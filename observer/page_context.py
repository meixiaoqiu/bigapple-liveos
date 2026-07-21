"""Observer page read model."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum

from core.member_roles import ROLE_BIG_APPLE_MEMBER, ROLE_CANDIDATE, member_role_filter
from core.models import (
    CapacityAssessment,
    Dispute,
    Event,
    LedgerEntry,
    Member,
    PlanChangeSet,
    PlanNode,
    PlanNodeRunState,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationTurn,
    Task,
)

from .dashboard_context import observer_command_dashboard_context
from .presentation import BOTTLENECK_LABELS, RISK_LABELS, task_completion_rate


def observer_context(*, full_plan_nodes: bool = False) -> dict[str, Any]:
    latest = CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()
    resources = list(Resource.objects.all().order_by("resource_type", "resource_id"))
    resource_warnings = [resource for resource in resources if resource.current_stock <= resource.warning_threshold]
    events = list(Event.objects.filter(visibility=Event.Visibility.PUBLIC).order_by("-occurred_at")[:12])
    simulation_events = list(
        Event.objects.filter(visibility=Event.Visibility.PUBLIC)
        .filter(Q(generated_by=Event.GeneratedBy.SIMULATION_ENGINE) | Q(event_type=Event.EventType.SIMULATION_DAY))
        .order_by("-occurred_at", "event_id")[:18]
    )
    task_counts = {
        row["status"]: row["count"]
        for row in Task.objects.values("status").annotate(count=Count("task_id")).order_by("status")
    }
    task_status_rows = [
        {
            "status": value,
            "label": label,
            "count": task_counts.get(value, 0),
        }
        for value, label in Task.Status.choices
        if task_counts.get(value, 0)
    ]
    open_disputes = Dispute.objects.exclude(
        status__in=[Dispute.Status.RESOLVED, Dispute.Status.REJECTED, Dispute.Status.REVERSED]
    ).count()
    bottleneck_rows = []
    risk_rows = []
    if latest:
        bottleneck_rows = [
            {"value": item, "label": BOTTLENECK_LABELS.get(item, item)}
            for item in latest.bottlenecks
        ]
        risk_rows = [
            {"name": RISK_LABELS.get(name, name), "value": value}
            for name, value in latest.risk_indicators.items()
        ]
    active_plan = ProjectPlan.objects.filter(status=ProjectPlan.Status.ACTIVE).order_by("plan_id").first()
    active_revision = None
    plan_nodes: list[PlanNode] = []
    current_plan_nodes: list[PlanNode] = []
    next_plan_nodes: list[PlanNode] = []
    plan_node_counts: dict[str, int] = {}
    plan_required_total = 0
    plan_required_completed = 0
    plan_estimated_cost_total = 0
    if active_plan:
        active_revision = (
            active_plan.revisions.filter(status=PlanRevision.Status.PUBLISHED)
            .order_by("-published_at", "-created_at", "revision_code")
            .first()
        )
        if active_revision is None:
            active_revision = active_plan.revisions.order_by("-created_at", "revision_code").first()
        if active_revision:
            node_queryset = active_revision.nodes.select_related("parent").order_by("sequence", "node_id")
            plan_nodes = list(node_queryset) if full_plan_nodes else list(node_queryset[:60])
            current_plan_nodes = list(
                node_queryset.filter(status__in=[PlanNode.Status.IN_PROGRESS, PlanNode.Status.BLOCKED])[:6]
            )
            next_plan_nodes = list(node_queryset.filter(status=PlanNode.Status.PLANNED)[:6])
            plan_node_counts = {
                row["status"]: row["count"]
                for row in active_revision.nodes.values("status").annotate(count=Count("node_id"))
            }
            required_nodes = active_revision.nodes.filter(is_required=True)
            plan_required_total = required_nodes.count()
            plan_required_completed = required_nodes.filter(status=PlanNode.Status.COMPLETED).count()
            plan_estimated_cost_total = (
                active_revision.nodes.aggregate(total=Sum("estimated_cost_expected"))["total"] or 0
            )

    latest_simulation_run = (
        SimulationRun.objects.select_related("plan_revision", "plan_revision__plan")
        .order_by("-started_at", "run_id")
        .first()
    )
    latest_run_node_states: list[PlanNodeRunState] = []
    latest_run_failures: list[SimulationFailure] = []
    latest_run_proposals: list[PlanRevisionProposal] = []
    latest_run_change_sets: list[PlanChangeSet] = []
    latest_run_turn = None
    if latest_simulation_run:
        latest_run_node_states = list(
            latest_simulation_run.node_states.select_related("plan_node")
            .exclude(status=PlanNodeRunState.Status.PENDING)
            .order_by("plan_node__sequence", "plan_node__node_id")[:12]
        )
        latest_run_failures = list(
            latest_simulation_run.failures.select_related("plan_node").order_by("-detected_at")[:6]
        )
        latest_run_proposals = list(
            latest_simulation_run.proposals.select_related("plan_node", "source_failure").order_by("-created_at")[:6]
        )
        latest_run_change_sets = list(
            latest_simulation_run.plan_change_sets.prefetch_related("operations")
            .select_related("proposal", "plan_revision")
            .order_by("-created_at", "change_set_id")[:6]
        )
        latest_run_turn = (
            SimulationTurn.objects.filter(run=latest_simulation_run)
            .order_by("-turn_number", "-occurred_at")
            .first()
        )

    return {
        "command_dashboard": observer_command_dashboard_context(),
        "latest_assessment": latest,
        "bottleneck_rows": bottleneck_rows,
        "risk_rows": risk_rows,
        "active_plan": active_plan,
        "active_revision": active_revision,
        "plan_nodes": plan_nodes,
        "current_plan_nodes": current_plan_nodes,
        "next_plan_nodes": next_plan_nodes,
        "plan_node_counts": plan_node_counts,
        "plan_required_total": plan_required_total,
        "plan_required_completed": plan_required_completed,
        "plan_estimated_cost_total": plan_estimated_cost_total,
        "latest_simulation_run": latest_simulation_run,
        "latest_run_node_states": latest_run_node_states,
        "latest_run_failures": latest_run_failures,
        "latest_run_proposals": latest_run_proposals,
        "latest_run_change_sets": latest_run_change_sets,
        "latest_run_turn": latest_run_turn,
        "resources": resources,
        "resource_warnings": resource_warnings,
        "events": events,
        "simulation_events": simulation_events,
        "task_status_rows": task_status_rows,
        "open_tasks": list(Task.objects.filter(status=Task.Status.OPEN).order_by("due_at", "task_id")[:8]),
        "member_rows": list(
            Member.objects.filter(
                member_role_filter(ROLE_BIG_APPLE_MEMBER),
                status__in=[Member.Status.ADMITTED, Member.Status.ACTIVE],
            )
            .order_by("member_no")[:12]
        ),
        "simulation_event_count": Event.objects.filter(generated_by=Event.GeneratedBy.SIMULATION_ENGINE).count(),
        "formal_members": Member.objects.filter(status=Member.Status.ADMITTED).count(),
        "candidate_members": Member.objects.filter(member_role_filter(ROLE_CANDIDATE)).count(),
        "total_tasks": Task.objects.count(),
        "task_completion_rate": task_completion_rate(),
        "open_disputes": open_disputes,
        "ledger_entries": LedgerEntry.objects.count(),
        "latest_day": latest.simulation_day if latest else 1,
    }
