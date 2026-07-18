"""Public world-scoped registration page."""

from __future__ import annotations

from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.exceptions import DomainError
from core.identity_services import ensure_basic_member_for_user, register_participant_account
from live_os.access import member_for_request
from worlds.routing import world_redirect
from worlds.views import SESSION_WORLD_ID

from .forms import ParticipantRegistrationForm, apply_daisyui_widgets


@require_http_methods(["GET", "POST"])
def register_page(request):
    """Participant account registration — User + Member + baseline role only."""
    if request.user.is_authenticated:
        member = member_for_request(request)
        if member is not None:
            return world_redirect(request, "workspace-page")
        member = ensure_basic_member_for_user(request.user)
        login(request, request.user, backend="django.contrib.auth.backends.ModelBackend")
        return world_redirect(request, "workspace-page")

    if request.method == "POST":
        form = apply_daisyui_widgets(ParticipantRegistrationForm(request.POST))
        if form.is_valid():
            try:
                user, member = register_participant_account(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password1"],
                    display_name=form.cleaned_data["display_name"],
                    contact=form.cleaned_data["contact"],
                )
            except DomainError as exc:
                messages.error(request, f"账号注册失败：{exc}")
            else:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                if getattr(request, "world", None) is not None:
                    request.session[SESSION_WORLD_ID] = request.world.world_id
                messages.success(request, "账号注册成功。欢迎加入大苹果！")
                return world_redirect(request, "workspace-page")
    else:
        form = apply_daisyui_widgets(ParticipantRegistrationForm())
    return render(request, "applications/register.html", {"form": form})
