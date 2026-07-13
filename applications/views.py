"""Public world-scoped application pages."""

from __future__ import annotations

from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.application_services import submit_member_application, submit_partner_application
from core.exceptions import DomainError
from core.models import MemberApplication
from live_os.access import member_for_request
from worlds.routing import world_redirect
from worlds.views import SESSION_WORLD_ID

from .forms import MemberApplicationForm, PartnerApplicationForm, apply_daisyui_widgets
from .simulation_metadata import metadata_from_signed_form_post


@require_http_methods(["GET", "POST"])
def member_application_page(request):
    member = member_for_request(request)
    if member is not None:
        return render(request, "applications/member_application_status.html", {"member": member})

    current_application = None
    if request.user.is_authenticated:
        current_application = (
            MemberApplication.objects.filter(account_user=request.user)
            .select_related("linked_member")
            .order_by("-submitted_at", "application_id")
            .first()
        )
    if current_application is not None:
        return render(request, "applications/member_application_status.html", {"application": current_application})

    if request.method == "POST":
        form = apply_daisyui_widgets(MemberApplicationForm(request.POST))
        if form.is_valid():
            try:
                application = submit_member_application(
                    account_username=form.cleaned_data["username"],
                    account_password=form.cleaned_data["password1"],
                    applicant_name=form.cleaned_data["applicant_name"],
                    contact=form.cleaned_data["contact"],
                    motivation=form.cleaned_data["motivation"],
                    availability_hours_per_week=form.cleaned_data["availability_hours_per_week"],
                    capability_scores=form.capability_scores(),
                    can_issue_responsibility_documents=form.cleaned_data["can_issue_responsibility_documents"],
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
                return world_redirect(request, "member-application-page")
    else:
        form = apply_daisyui_widgets(MemberApplicationForm())
    return render(request, "applications/member_application.html", {"form": form})


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
