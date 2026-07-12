from __future__ import annotations

from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.http import HttpRequest
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .forms import WorldAuthenticationForm


SESSION_WORLD_ID = "world_id"
SESSION_WORLD_DATABASE_ALIAS = "world_database_alias"


class WorldLoginView(LoginView):
    template_name = "worlds/login.html"
    authentication_form = WorldAuthenticationForm

    def get_initial(self):
        initial = super().get_initial()
        world_id = self.kwargs.get("world_id")
        if world_id:
            initial["world_id"] = world_id
        return initial

    def form_valid(self, form):
        self.request.session[SESSION_WORLD_ID] = form.cleaned_data["world_id"]
        self.request.session[SESSION_WORLD_DATABASE_ALIAS] = form.cleaned_data["world_database_alias"]
        return super().form_valid(form)

    def get_success_url(self):
        url = self.get_redirect_url()
        if url:
            return url
        return "/workspace/"


@require_POST
def world_logout(request: HttpRequest, world_id: str | None = None):
    logout(request)
    return redirect("/login/")
