"""Public world-scoped application pages."""

from __future__ import annotations

from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.application_services import submit_member_application, submit_partner_application
from core.exceptions import DomainError
from core.member_roles import ROLE_FORMAL_MEMBER, member_has_role
from core.models import Member, MemberApplication
from live_os.access import member_for_request
from worlds.routing import world_redirect
from worlds.views import SESSION_WORLD_ID

from .forms import MemberApplicationForm, PartnerApplicationForm, apply_daisyui_widgets
from .simulation_metadata import metadata_from_signed_form_post


MEMBER_APPLICATION_REAPPLY_STATUSES = {MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW}

DISABLED_MEMBER_STATUSES: frozenset[str] = frozenset({Member.Status.SUSPENDED, Member.Status.EXITED})


def member_is_formal_member(member: Member | None) -> bool:
    """Return True if *member* is recognisable as a formal member.

    Formal membership is determined by an active ``ROLE_FORMAL_MEMBER``
    RoleAssignment.  Lifecycle-disabled statuses (``SUSPENDED``,
    ``EXITED``) veto the check even when the role is present — a
    suspended or exited member must not be treated as a formal member
    for application-page purposes.
    """
    if member is None:
        return False
    if member.status in DISABLED_MEMBER_STATUSES:
        return False
    return member_has_role(member, ROLE_FORMAL_MEMBER)


def _latest_member_application(*, user=None, member=None):
    queryset = MemberApplication.objects.select_related("linked_member", "account_user")
    if member is not None:
        queryset = queryset.filter(linked_member=member)
    elif user is not None and getattr(user, "is_authenticated", False):
        queryset = queryset.filter(account_user=user)
    else:
        return None
    return queryset.order_by("-submitted_at", "application_id").first()


@require_http_methods(["GET", "POST"])
def member_application_page(request):
    member = member_for_request(request)
    current_application = _latest_member_application(
        user=request.user if request.user.is_authenticated else None,
        member=member,
    )
    if member_is_formal_member(member):
        return render(request, "applications/member_application_status.html", {"member": member})
    can_reapply = bool(current_application and current_application.status in MEMBER_APPLICATION_REAPPLY_STATUSES)
    if current_application is not None and not can_reapply:
        return render(
            request,
            "applications/member_application_status.html",
            {"application": current_application},
        )
    existing_user = request.user if request.user.is_authenticated else None

    if request.method == "POST":
        form = apply_daisyui_widgets(
            MemberApplicationForm(request.POST, existing_user=existing_user, existing_member=member)
        )
        if form.is_valid():
            try:
                application = submit_member_application(
                    account_username="" if existing_user is not None else form.cleaned_data["username"],
                    account_password="" if existing_user is not None else form.cleaned_data["password1"],
                    account_user=existing_user,
                    applicant_name=form.cleaned_data["applicant_name"],
                    contact=form.cleaned_data["contact"],
                    motivation=form.motivation_text(),
                    availability_hours_per_week=form.cleaned_data["availability_hours_per_week"],
                    role_gap=form.cleaned_data["role_gap"],
                    availability_slots=form.cleaned_data["availability_slots"],
                    dynamic_answers=form.dynamic_answers(),
                    capability_scores=form.capability_scores(),
                    can_issue_responsibility_documents=False,
                    document_authority_domains=form.document_authority_domains(),
                    requested_member_no=form.cleaned_data["requested_member_no"],
                    metadata=metadata_from_signed_form_post(request.POST),
                )
            except DomainError as exc:
                messages.error(request, f"成员报名提交失败：{exc}")
            else:
                messages.success(request, f"成员报名已提交：{application.application_id}")
                if application.account_user_id:
                    login(request, application.account_user, backend="django.contrib.auth.backends.ModelBackend")
                    if getattr(request, "world", None) is not None:
                        request.session[SESSION_WORLD_ID] = request.world.world_id
                return world_redirect(request, "workspace-page")
    else:
        form = apply_daisyui_widgets(MemberApplicationForm(existing_user=existing_user, existing_member=member))
    return render(
        request,
        "applications/member_application.html",
        {"form": form, "is_reapply": can_reapply, "previous_application": current_application},
    )


@require_http_methods(["GET", "POST"])
def partner_application_page(request):
    if request.method == "POST":
        form = apply_daisyui_widgets(PartnerApplicationForm(request.POST))
        if form.is_valid():
            try:
                application = submit_partner_application(
                    organization_name=form.cleaned_data["organization_name"],
                    contact_name=form.cleaned_data["contact_name"],
                    contact=form.cleaned_data["contact"],
                    service_domains=form.service_domains(),
                    can_issue_responsibility_documents=form.cleaned_data["can_issue_responsibility_documents"],
                    responsibility_document_domains=form.responsibility_document_domains(),
                    qualification_summary=form.cleaned_data["qualification_summary"],
                    quote_summary=form.cleaned_data["quote_summary"],
                    service_area=form.cleaned_data["service_area"],
                    delivery_cycle_days=form.cleaned_data["delivery_cycle_days"],
                    constraints=form.cleaned_data["constraints"],
                    metadata=metadata_from_signed_form_post(request.POST),
                )
            except DomainError as exc:
                messages.error(request, f"合作方报名提交失败：{exc}")
            else:
                messages.success(request, f"合作方报名已提交：{application.application_id}")
                return world_redirect(request, "partner-application-page")
    else:
        form = apply_daisyui_widgets(PartnerApplicationForm())
    return render(request, "applications/partner_application.html", {"form": form})
