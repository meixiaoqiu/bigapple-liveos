"""Control-plane URL configuration for bigadmin.local."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/simulation-lab/", include("simulation_lab.urls")),
    path("admin/", admin.site.urls),
]
