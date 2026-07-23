"""HTML and HTMX observer views."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core.models import (
    RiskAlert,
    ApprovalProposal,
    CredentialGrant,
    Event,
    Resource,
    SimulationSnapshot,
    SupplierQuote,
    SystemEvent,
)
from core.procurement_services import submit_resource_offer

from .page_context import _resource_public_rows, observer_context
from .dashboard_theme import build_dashboard_theme_context
from .simulation_reports import public_simulation_report, public_simulation_reports
from .theme import get_theme_partial_path, get_theme_template_path
from .timeline_context import observer_timeline_events_for_request
from .theme_views import apply_theme_query_override


@require_GET
def observer_page(request: HttpRequest, **_kwargs):
    apply_theme_query_override(request)
    context = observer_context()
    context["timeline_events"] = observer_timeline_events_for_request(request, context["command_dashboard"])
    context["timeline_compact"] = request.GET.get("compact") == "1"
    context["selected_task_id"] = request.GET.get("quest_task") or request.GET.get("task_id") or ""
    context["quest_status"] = request.GET.get("quest_status") or ""
    context["dashboard_context"] = build_dashboard_theme_context(request, context)
    return render(request, get_theme_template_path(request, "dashboard.html"), context)


@require_GET
def simulation_report_list_page(request: HttpRequest, **_kwargs):
    apply_theme_query_override(request)
    return render(
        request,
        get_theme_template_path(request, "simulation_reports.html"),
        {
            "reports": public_simulation_reports(),
        },
    )


@require_GET
def simulation_report_detail_page(request: HttpRequest, snapshot_id: str, **_kwargs):
    apply_theme_query_override(request)
    try:
        report = public_simulation_report(snapshot_id)
    except SimulationSnapshot.DoesNotExist as exc:
        raise Http404("Simulation report not found.") from exc
    return render(
        request,
        get_theme_template_path(request, "simulation_report_detail.html"),
        {
            "report": report,
        },
    )


def dashboard_theme_context(request: HttpRequest) -> dict[str, Any]:
    apply_theme_query_override(request)
    context = observer_context()
    context["selected_task_id"] = request.GET.get("quest_task") or request.GET.get("task_id") or ""
    context["quest_status"] = request.GET.get("quest_status") or ""
    context["dashboard_context"] = build_dashboard_theme_context(request, context)
    return context


@require_GET
def dashboard_mainline(request: HttpRequest, **_kwargs):
    """Full mainline detail page showing all plan nodes grouped by stage."""
    apply_theme_query_override(request)
    raw = observer_context(full_plan_nodes=True)
    context = {
        **raw,
        "selected_task_id": request.GET.get("quest_task") or request.GET.get("task_id") or "",
        "quest_status": request.GET.get("quest_status") or "",
        "dashboard_context": build_dashboard_theme_context(request, raw),
    }
    return render(request, get_theme_template_path(request, "mainline.html"), context)


@require_GET
def dashboard_events_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "event_feed.html"), dashboard_theme_context(request))


@require_GET
def dashboard_task_detail_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "task_detail.html"), dashboard_theme_context(request))


@require_GET
def dashboard_risk_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "risk_panel.html"), dashboard_theme_context(request))


@require_GET
def dashboard_capacity_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "capacity_panel.html"), dashboard_theme_context(request))


@require_GET
def dashboard_photo_story_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "photo_story_feed.html"), dashboard_theme_context(request))


@require_GET
def observer_events_list(request: HttpRequest, **_kwargs):
    """Public community event stream list page."""
    apply_theme_query_override(request)
    from .event_context import is_member_application_stage_event, public_event_row, public_member_application_rows

    max_events = 100
    events = Event.objects.filter(visibility=Event.Visibility.PUBLIC).filter(
        Q(payload__source__isnull=True) | ~Q(payload__source="member_application"),
    ).order_by("-occurred_at", "event_id")[:max_events]
    events = [e for e in events if not is_member_application_stage_event(e)]
    rows = [public_event_row(e) for e in events]

    # Prepend aggregated member application cards
    ma_rows = public_member_application_rows()
    merged = ma_rows + rows
    merged.sort(key=lambda r: r.get("occurred_at", timezone.now()), reverse=True)

    return render(
        request,
        get_theme_template_path(request, "events_list.html"),
        {"events": merged[:max_events]},
    )



@require_GET
def observer_event_detail(request: HttpRequest, event_id: str, **_kwargs):
    """Public community event detail page.

    Member-application stage events (submitted / admitted / rejected) are
    not exposed as standalone detail pages; they 404 here.  Use
    ``/member-applications/<application_id>/`` instead.
    """
    apply_theme_query_override(request)
    from .event_context import is_member_application_stage_event, public_event_detail

    try:
        event = Event.objects.get(event_id=event_id, visibility=Event.Visibility.PUBLIC)
    except Event.DoesNotExist as exc:
        raise Http404("Public event not found.") from exc

    if is_member_application_stage_event(event):
        raise Http404("Member application stage events are no longer standalone pages.")

    detail = public_event_detail(event)
    return render(
        request,
        get_theme_template_path(request, "event_detail.html"),
        {"event": detail},
    )


@require_GET
def observer_member_application_detail(request: HttpRequest, application_id: str, **_kwargs):
    """Member application detail page aggregating all stage events."""
    apply_theme_query_override(request)
    from .event_context import public_member_application_detail

    detail = public_member_application_detail(application_id)
    if detail is None:
        raise Http404("Member application not found.")
    return render(
        request,
        get_theme_template_path(request, "member_application_detail.html"),
        detail,
    )


@require_GET
def observer_member_profile(request: HttpRequest, member_no: str, **_kwargs):
    """Public member profile page."""
    apply_theme_query_override(request)
    from .member_profiles import public_member_profile_context

    context = public_member_profile_context(member_no)
    if context is None:
        raise Http404("Member not found.")
    return render(
        request,
        get_theme_template_path(request, "member_profile.html"),
        context,
    )


@require_GET
def observer_event_ledger_list(request: HttpRequest, **_kwargs):
    """Public system event audit ledger list page."""
    apply_theme_query_override(request)
    from .event_context import public_system_event_row

    max_events = 100
    events = SystemEvent.objects.order_by("-seq")[:max_events]
    rows = [public_system_event_row(e) for e in events]
    return render(
        request,
        get_theme_template_path(request, "event_ledger_list.html"),
        {"events": rows},
    )


@require_GET
def observer_event_ledger_detail(request: HttpRequest, seq: int, **_kwargs):
    """Public system event audit ledger detail page."""
    apply_theme_query_override(request)
    from .event_context import public_system_event_detail

    try:
        event = SystemEvent.objects.get(seq=seq)
    except SystemEvent.DoesNotExist as exc:
        raise Http404("System event not found.") from exc

    detail = public_system_event_detail(event)

    # Previous / next navigation
    prev_event = SystemEvent.objects.filter(seq__lt=seq).order_by("-seq").first()
    next_event = SystemEvent.objects.filter(seq__gt=seq).order_by("seq").first()
    detail["prev_seq"] = prev_event.seq if prev_event else None
    detail["next_seq"] = next_event.seq if next_event else None

    return render(
        request,
        get_theme_template_path(request, "event_ledger_detail.html"),
        {"event": detail},
    )


@require_GET
def observer_resources_page(request: HttpRequest, **_kwargs):
    """Public read-only resource inventory list page (no login required)."""
    apply_theme_query_override(request)
    from .page_context import _sort_resources_by_stock_ratio
    from core.models import Resource

    all_resources = list(Resource.objects.all())
    sorted_resources = _sort_resources_by_stock_ratio(all_resources)
    rows = _resource_public_rows(sorted_resources)

    # Attach offer summaries to each resource row
    for row in rows:
        quotes = SupplierQuote.objects.filter(resource_id=row["resource_id"])
        row["offer_count"] = quotes.count()
        row["submitted_count"] = quotes.filter(
            decision_status=SupplierQuote.DecisionStatus.SUBMITTED
        ).count()
        row["accepted_count"] = quotes.filter(
            decision_status=SupplierQuote.DecisionStatus.ACCEPTED
        ).count()
        row["fulfilled_count"] = quotes.filter(
            decision_status=SupplierQuote.DecisionStatus.FULFILLED
        ).count()
        _quote_rows = list(
            quotes.filter(
                decision_status=SupplierQuote.DecisionStatus.SUBMITTED,
                offer_type=SupplierQuote.OfferType.QUOTE,
            ).order_by("unit_price")
        )
        row["lowest_quote_price"] = float(_quote_rows[0].unit_price) if _quote_rows else None
        _donations = quotes.filter(
            decision_status__in=[
                SupplierQuote.DecisionStatus.SUBMITTED,
                SupplierQuote.DecisionStatus.ACCEPTED,
            ],
            offer_type=SupplierQuote.OfferType.DONATION,
        ).aggregate(total=Sum("available_quantity"))
        row["donation_qty_total"] = float(_donations["total"] or 0)

    return render(
        request,
        get_theme_template_path(request, "resources.html"),
        {"resource_rows": rows},
    )


# ── public procurement offer pages ────────────────────────────────────


def _offer_summary(resource_id: str) -> dict:
    """Return counts + lowest price summary for a resource."""
    quotes = SupplierQuote.objects.filter(resource_id=resource_id)
    submitted = quotes.filter(decision_status=SupplierQuote.DecisionStatus.SUBMITTED)
    quote_rows = list(
        submitted.filter(offer_type=SupplierQuote.OfferType.QUOTE).order_by("unit_price")
    )
    return {
        "total": quotes.count(),
        "submitted": submitted.count(),
        "accepted": quotes.filter(decision_status=SupplierQuote.DecisionStatus.ACCEPTED).count(),
        "fulfilled": quotes.filter(decision_status=SupplierQuote.DecisionStatus.FULFILLED).count(),
        "lowest_quote_price": float(quote_rows[0].unit_price) if quote_rows else None,
    }


def _public_offer_row(quote: SupplierQuote) -> dict:
    """Build a public-safe dict for one SupplierQuote."""
    return {
        "quote_id": quote.quote_id,
        "offer_type": quote.offer_type,
        "offer_type_label": quote.get_offer_type_display(),
        "unit_price": float(quote.unit_price),
        "currency": quote.currency,
        "available_quantity": float(quote.available_quantity),
        "minimum_order_quantity": float(quote.minimum_order_quantity),
        "lead_time_days": quote.lead_time_days,
        "quality_summary": quote.quality_summary or "",
        "estimated_total_amount": float(quote.estimated_total_amount),
        "approval_tier": quote.approval_tier,
        "approval_tier_label": quote.get_approval_tier_display(),
        "decision_status": quote.decision_status,
        "decision_status_label": quote.get_decision_status_display(),
        "receipt_status": quote.receipt_status,
        "receipt_status_label": quote.get_receipt_status_display(),
        "payment_status": quote.payment_status,
        "payment_status_label": quote.get_payment_status_display(),
        "submitted_by_display": (
            quote.public_display_name
            or (
                quote.submitted_by.member_no
                if quote.submitted_by and quote.public_visibility != SupplierQuote.PublicVisibility.ANONYMOUS
                else "匿名"
            )
            if quote.submitted_by
            else (quote.partner_application.member_id if quote.partner_application else "")
        ),
        "public_visibility": quote.public_visibility,
        "has_performance_credential": quote.performance_credential_id is not None,
        "created_at": quote.created_at,
        "challenge_count": getattr(quote, "challenge_count", 0),
    }


_OFFER_SORT_ORDER = {
    SupplierQuote.DecisionStatus.SUBMITTED: 0,
    SupplierQuote.DecisionStatus.ACCEPTED: 1,
    SupplierQuote.DecisionStatus.FULFILLED: 3,
    SupplierQuote.DecisionStatus.REJECTED: 4,
    SupplierQuote.DecisionStatus.CANCELLED: 5,
}


@require_GET
def observer_resource_offers(request: HttpRequest, resource_id: str, **_kwargs):
    """Public read-only list of offers for a resource."""
    apply_theme_query_override(request)
    resource = get_object_or_404(Resource, resource_id=resource_id)
    resource_row = _resource_public_rows([resource])[0]
    summary = _offer_summary(resource_id)

    quotes = list(SupplierQuote.objects.filter(resource_id=resource_id))
    # Sort: decision_status priority → donation near top → quote by price
    quotes.sort(key=lambda q: (
        _OFFER_SORT_ORDER.get(q.decision_status, 9),
        0 if q.offer_type == SupplierQuote.OfferType.DONATION else 1,
        float(q.unit_price),
        q.lead_time_days,
    ))
    offer_rows = [_public_offer_row(q) for q in quotes]

    # Attach proposal status to each offer row
    from core.models import ApprovalProposal
    offer_ids = [q.quote_id for q in quotes]
    proposals = {
        p.target_id: p
        for p in ApprovalProposal.objects.filter(
            target_type="supplier_quote",
            target_id__in=offer_ids,
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        )
    }
    for row in offer_rows:
        prop = proposals.get(row["quote_id"])
        row["proposal_status"] = prop.status if prop else ""
        row["proposal_status_label"] = prop.get_status_display() if prop else ""

    return render(
        request,
        get_theme_template_path(request, "resource_offers.html"),
        {
            "resource": resource_row,
            "summary": summary,
            "offer_rows": offer_rows,
            "accepts_offers": resource.accepts_offers,
        },
    )


@require_http_methods(["GET", "POST"])
def observer_resource_offer_new(request: HttpRequest, resource_id: str, **_kwargs):
    """Submit a quote or donation for a resource (login required)."""
    apply_theme_query_override(request)
    resource = get_object_or_404(Resource, resource_id=resource_id)
    resource_row = _resource_public_rows([resource])[0]

    # Login required
    from live_os.access import is_authenticated as live_os_authenticated, member_for_request
    if not live_os_authenticated(request):
        return HttpResponseRedirect(f"/login/?next=/resources/{resource_id}/offers/new/")

    member = member_for_request(request)
    if member is None:
        return HttpResponseRedirect(f"/login/?next=/resources/{resource_id}/offers/new/")

    # Check accepts_offers
    if not resource.accepts_offers:
        return render(
            request,
            get_theme_template_path(request, "resource_offer_new.html"),
            {
                "resource": resource_row,
                "member": member,
                "errors": ["该资源当前不接受公开报价。"],
                "form_data": {},
            },
            status=403,
        )

    if request.method == "GET":
        return render(
            request,
            get_theme_template_path(request, "resource_offer_new.html"),
            {
                "resource": resource_row,
                "member": member,
                "errors": [],
                "form_data": {},
            },
        )

    # POST
    errors = []
    offer_type = request.POST.get("offer_type", "").strip()
    quantity_str = request.POST.get("available_quantity", "").strip()
    price_str = request.POST.get("unit_price", "").strip()
    currency = request.POST.get("currency", "CNY").strip() or "CNY"
    moq_str = request.POST.get("minimum_order_quantity", "").strip()
    lead_str = request.POST.get("lead_time_days", "").strip()
    quality = request.POST.get("quality_summary", "").strip()
    notes = request.POST.get("notes", "").strip()
    public_visibility = request.POST.get("public_visibility", "public").strip()
    public_display_name = request.POST.get("public_display_name", "").strip()

    if offer_type not in {"quote", "donation"}:
        errors.append("供给类型无效。")
    try:
        quantity = Decimal(quantity_str) if quantity_str else None
        if quantity is None:
            errors.append("可供数量不能为空。")
    except Exception:
        errors.append("可供数量必须是数字。")
        quantity = None
    try:
        unit_price = Decimal(price_str) if price_str else Decimal("0")
    except Exception:
        errors.append("单价必须是数字。")
        unit_price = None
    try:
        moq = Decimal(moq_str) if moq_str else Decimal("0")
    except Exception:
        moq = Decimal("0")
    try:
        lead = int(lead_str) if lead_str else 0
    except Exception:
        lead = 0

    if errors:
        return render(
            request,
            get_theme_template_path(request, "resource_offer_new.html"),
            {
                "resource": resource_row,
                "member": member,
                "errors": errors,
                "form_data": {
                    "offer_type": offer_type,
                    "available_quantity": quantity_str,
                    "unit_price": price_str,
                    "currency": currency,
                    "minimum_order_quantity": moq_str,
                    "lead_time_days": lead_str,
                    "quality_summary": quality,
                    "notes": notes,
                    "public_visibility": public_visibility,
                    "public_display_name": public_display_name,
                },
            },
            status=400,
        )

    try:
        quote = submit_resource_offer(
            resource=resource,
            submitted_by=member,
            offer_type=offer_type,
            available_quantity=quantity,
            unit_price=unit_price,
            currency=currency,
            minimum_order_quantity=moq,
            lead_time_days=lead,
            quality_summary=quality,
            notes=notes,
            public_visibility=public_visibility or "public",
            public_display_name=public_display_name or "",
        )
    except Exception as exc:
        errors.append(str(exc))
        return render(
            request,
            get_theme_template_path(request, "resource_offer_new.html"),
            {
                "resource": resource_row,
                "member": member,
                "errors": errors,
                "form_data": {
                    "offer_type": offer_type,
                    "available_quantity": quantity_str,
                    "unit_price": price_str,
                    "currency": currency,
                    "minimum_order_quantity": moq_str,
                    "lead_time_days": lead_str,
                    "quality_summary": quality,
                    "notes": notes,
                    "public_visibility": public_visibility,
                    "public_display_name": public_display_name,
                },
            },
            status=400,
        )

    messages.success(request, "报价已提交。")
    return HttpResponseRedirect(f"/resources/{resource_id}/offers/")


# ── public provider reputation ──────────────────────────────────────────


def _provider_reputation(member_no: str) -> dict:
    """Public-safe reputation summary for a supplier member."""
    from core.models import CredentialGrant

    completed = CredentialGrant.objects.filter(
        member__member_no=member_no,
        template__code="provider_delivery_completed",
    ).count()
    fulfilled_quotes = SupplierQuote.objects.filter(
        submitted_by__member_no=member_no,
        decision_status=SupplierQuote.DecisionStatus.FULFILLED,
    ).count()
    rejected_receipts = SupplierQuote.objects.filter(
        submitted_by__member_no=member_no,
        receipt_status=SupplierQuote.ReceiptStatus.REJECTED,
    ).count()
    return {
        "completed_delivery_count": completed,
        "fulfilled_quote_count": fulfilled_quotes,
        "rejected_receipt_count": rejected_receipts,
        "has_credentials": completed > 0,
    }


# ── public offer detail / timeline ──────────────────────────────────────


def _build_offer_timeline(quote: SupplierQuote) -> list[dict]:
    """Build public-safe timeline entries for a quote by querying SystemEvent.
    Falls back to aggregating from model fields if events are incomplete."""
    events = list(
        SystemEvent.objects.filter(
            aggregate_type="SupplierQuote",
            aggregate_id=quote.quote_id,
        ).order_by("occurred_at")
    )
    # Also include related ApprovalProposal events
    proposal = ApprovalProposal.objects.filter(
        target_type="supplier_quote",
        target_id=quote.quote_id,
    ).first()
    if proposal:
        proposal_events = list(
            SystemEvent.objects.filter(
                aggregate_type="ApprovalProposal",
                aggregate_id=proposal.proposal_id,
            ).order_by("occurred_at")
        )
        events.extend(proposal_events)
        events.sort(key=lambda e: e.occurred_at)

    timeline: list[dict] = []
    for evt in events:
        payload = evt.payload_json or {}
        public_facts = payload.get("public_facts") or {}
        timeline.append({
            "occurred_at": evt.occurred_at.isoformat() if evt.occurred_at else "",
            "event_type": evt.event_type,
            "summary": payload.get("summary", evt.event_type),
            "action": payload.get("action", ""),
        })

    # Build from model fields as fallback
    if not timeline:
        timeline.append({
            "occurred_at": quote.created_at.isoformat() if quote.created_at else "",
            "event_type": "quote_created",
            "summary": f"报价 {quote.quote_id} 已提交",
            "action": "submitted",
        })
    return timeline


@require_GET
def observer_resource_offer_detail(request: HttpRequest, resource_id: str, quote_id: str, **_kwargs):
    """Public read-only detail page for one offer with timeline."""
    apply_theme_query_override(request)
    quote = get_object_or_404(SupplierQuote, quote_id=quote_id, resource_id=resource_id)
    row = _public_offer_row(quote)
    timeline = _build_offer_timeline(quote)
    reputation = {}
    if quote.submitted_by:
        reputation = _provider_reputation(quote.submitted_by.member_no)

    from core.models import ProcurementChallenge

    challenges = list(
        ProcurementChallenge.objects.filter(quote=quote).order_by("-created_at")
    )
    challenge_rows = [
        {
            "challenge_id": c.challenge_id,
            "challenge_type": c.challenge_type,
            "challenge_type_label": c.get_challenge_type_display(),
            "status": c.status,
            "status_label": c.get_status_display(),
            "public_reason": c.public_reason,
            "proposed_unit_price": float(c.proposed_unit_price) if c.proposed_unit_price else None,
            "proposed_quantity": float(c.proposed_quantity) if c.proposed_quantity else None,
            "created_at": c.created_at,
        }
        for c in challenges
    ]

    return render(
        request,
        get_theme_template_path(request, "resource_offer_detail.html"),
        {
            "offer": row,
            "timeline": timeline,
            "reputation": reputation,
            "resource_id": resource_id,
            "challenges": challenge_rows,
        },
    )


@require_http_methods(["GET", "POST"])
def observer_resource_offer_challenge_new(request: HttpRequest, resource_id: str, quote_id: str, **_kwargs):
    apply_theme_query_override(request)
    quote = get_object_or_404(SupplierQuote, quote_id=quote_id, resource_id=resource_id)
    resource_row = _resource_public_rows([quote.resource])[0]
    offer_row = _public_offer_row(quote)

    from live_os.access import is_authenticated as live_os_authenticated, member_for_request
    if not live_os_authenticated(request):
        return HttpResponseRedirect(f"/login/?next=/resources/{resource_id}/offers/{quote_id}/challenges/new/")
    member = member_for_request(request)
    if member is None:
        return HttpResponseRedirect(f"/login/?next=/resources/{resource_id}/offers/{quote_id}/challenges/new/")

    if request.method == "GET":
        return render(
            request,
            get_theme_template_path(request, "resource_offer_challenge_form.html"),
            {"offer": offer_row, "resource_id": resource_id, "errors": [], "form_data": {}},
        )

    from core.procurement_challenge_services import submit_procurement_challenge
    from core.exceptions import DomainError

    challenge_type = request.POST.get("challenge_type", "").strip()
    public_reason = request.POST.get("public_reason", "").strip()
    price_str = request.POST.get("proposed_unit_price", "").strip()
    qty_str = request.POST.get("proposed_quantity", "").strip()

    try:
        price = Decimal(price_str) if price_str else None
        qty = Decimal(qty_str) if qty_str else None
        submit_procurement_challenge(
            quote=quote, submitted_by=member,
            challenge_type=challenge_type, public_reason=public_reason,
            proposed_unit_price=price, proposed_quantity=qty,
        )
        messages.success(request, "质疑已提交。")
    except DomainError as exc:
        return render(
            request,
            get_theme_template_path(request, "resource_offer_challenge_form.html"),
            {"offer": offer_row, "resource_id": resource_id, "errors": [str(exc)],
             "form_data": {"challenge_type": challenge_type, "public_reason": public_reason,
                           "proposed_unit_price": price_str, "proposed_quantity": qty_str}},
            status=400,
        )
    return HttpResponseRedirect(f"/resources/{resource_id}/offers/{quote_id}/")


@require_GET
def observer_risks_page(request, **_kwargs):
    apply_theme_query_override(request)
    alerts = list(RiskAlert.objects.filter(
        visibility="public",
        status__in=["active", "acknowledged", "investigating"],
    ).order_by("-severity", "-last_seen_at"))
    return render(request, get_theme_template_path(request, 'risks.html'), {'alerts': alerts})
