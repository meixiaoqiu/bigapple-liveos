from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm

from .context import DEFAULT_REALWORLD_ID, bind_default_world_context, bind_world_context
from .models import WorldRegistry
from .state import reset_current_world, set_current_world


class WorldAuthenticationForm(AuthenticationForm):
    world_id = forms.ChoiceField(label="世界")

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields["world_id"].widget.attrs.update({"class": "select select-bordered w-full"})
        self.fields["username"].widget.attrs.update({"class": "input input-bordered w-full"})
        self.fields["password"].widget.attrs.update({"class": "input input-bordered w-full"})
        if getattr(settings, "SITE_FIXED_WORLD", False):
            world_id = str(getattr(settings, "SITE_WORLD_ID", DEFAULT_REALWORLD_ID))
            self.fields["world_id"].choices = [(world_id, world_id)]
            self.fields["world_id"].initial = world_id
            self.fields["world_id"].widget = forms.HiddenInput()
            return
        worlds = WorldRegistry.objects.filter(status=WorldRegistry.Status.ACTIVE).order_by("world_id")
        choices = [(world.world_id, f"{world.world_id} - {world.name}") for world in worlds]
        self.fields["world_id"].choices = choices
        if choices:
            active_world_ids = {world_id for world_id, _label in choices}
            initial_world_id = str(self.initial.get("world_id") or DEFAULT_REALWORLD_ID).strip()
            if initial_world_id not in active_world_ids:
                initial_world_id = DEFAULT_REALWORLD_ID if DEFAULT_REALWORLD_ID in active_world_ids else choices[0][0]
            self.fields["world_id"].initial = initial_world_id

    def clean(self):
        world_id = str(self.data.get("world_id") or DEFAULT_REALWORLD_ID).strip()
        if self.request is None:
            raise forms.ValidationError("Request is required.")

        world = bind_default_world_context(self.request) if getattr(settings, "SITE_FIXED_WORLD", False) else bind_world_context(self.request, world_id)
        token = set_current_world(world)
        try:
            cleaned_data = super().clean()
        finally:
            reset_current_world(token)

        cleaned_data["world_id"] = world.world_id
        cleaned_data["world_database_alias"] = world.database_alias
        return cleaned_data
