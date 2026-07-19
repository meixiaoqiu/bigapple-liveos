"""Combined URL configuration for the unit test suite only."""

from django.contrib import admin
from django.urls import include, path

from live_os.urls_world import handler400, handler403, handler404, handler500


urlpatterns = [
    path("admin/simulation-lab/", include("simulation_lab.urls")),
    path("admin/", admin.site.urls),
    path("", include("live_os.urls_world")),
]
