"""Public world-scoped application pages."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.application_services import submit_member_application, submit_partner_application
from core.exceptions import DomainError
from worlds.routing import world_redirect

from .forms import MemberApplicationForm, PartnerApplicationForm, apply_daisyui_widgets
from .simulation_metadata import metadata_from_signed_form_post


@require_http_methods(["GET", "POST"])
def member_application_page(request):
    if request.method == "POST":
        form = apply_daisyui_widgets(MemberApplicationForm(request.POST))
        if form.is_valid():
            try:
                application = submit_member_application(
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
