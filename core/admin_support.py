"""Reusable Django Admin helpers for technical backend modules."""

from __future__ import annotations


def model_field_names(model: type) -> tuple[str, ...]:
    return tuple(field.name for field in model._meta.fields)


class StablePrimaryKeyAdminMixin:
    """Make business primary keys immutable after a record is created."""

    stable_primary_key = ""

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and self.stable_primary_key and self.stable_primary_key not in readonly_fields:
            readonly_fields.append(self.stable_primary_key)
        return tuple(readonly_fields)


class NoDeleteAdminMixin:
    """Prevent accidental deletion of authority records from Django Admin."""

    def has_delete_permission(self, request, obj=None):
        return False


class HiddenFromAdminIndexMixin:
    """Hide low-level support models from the top-level Admin menus."""

    def get_model_perms(self, request):
        return {}


class ImmutableHistoryAdminMixin(NoDeleteAdminMixin):
    """Expose append-only or generated history records as read-only in Admin."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)


class NoDeleteInlineMixin:
    """Prevent deleting authority child records through inline forms."""

    can_delete = False

    def has_delete_permission(self, request, obj=None):
        return False


class ImmutableHistoryInlineMixin(NoDeleteInlineMixin):
    """Expose generated inline history records without editable form fields."""

    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        for field_name in model_field_names(self.model):
            if field_name not in readonly_fields:
                readonly_fields.append(field_name)
        return tuple(readonly_fields)
