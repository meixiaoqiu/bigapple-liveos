"""Combined URL configuration for the unit test suite only."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/simulation-lab/", include("simulation_lab.urls")),
    path("admin/", admin.site.urls),
    path("", include("live_os.urls_world")),
]
