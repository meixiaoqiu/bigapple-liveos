from django.contrib import admin

from .models import WorldRegistry


@admin.register(WorldRegistry)
class WorldRegistryAdmin(admin.ModelAdmin):
    list_display = ("world_id", "name", "world_type", "database_alias", "database_name", "status", "created_at")
    list_filter = ("world_type", "status", "database_alias")
    search_fields = ("world_id", "name", "database_alias", "database_name")
    readonly_fields = ("created_at", "updated_at")
