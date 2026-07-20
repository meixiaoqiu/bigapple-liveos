"""Control-plane URL configuration for bigadmin.local."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False), name="admin-root"),
    path("admin/simulation-lab/", include("simulation_lab.urls")),
    path("admin/", admin.site.urls),
]
