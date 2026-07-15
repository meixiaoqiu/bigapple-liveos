from django.contrib import admin

from .models import WorldMaintenanceLog, WorldRegistry


@admin.register(WorldRegistry)
class WorldRegistryAdmin(admin.ModelAdmin):
    list_display = ("world_id", "name", "world_type", "database_alias", "database_name", "status", "created_at")
    list_filter = ("world_type", "status", "database_alias")
    search_fields = ("world_id", "name", "database_alias", "database_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorldMaintenanceLog)
class WorldMaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ("id", "world", "action", "status", "force", "actor_username", "created_at")
    list_filter = ("action", "status", "world")
    search_fields = ("world__world_id", "actor_username")
    readonly_fields = (
        "world",
        "action",
        "actor_username",
        "status",
        "force",
        "counts_before_json",
        "counts_after_json",
        "message",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
