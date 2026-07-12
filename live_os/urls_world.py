"""Single-world runtime URL configuration shared by bigreal.local and bigsim.local."""

from django.urls import include, path

from observer.api_views import observer_summary
from worlds import views as world_views


urlpatterns = [
    path("login/", world_views.WorldLoginView.as_view(), name="world-login"),
    path("logout/", world_views.world_logout, name="world-logout"),
    path("apply/", include("applications.urls")),
    path("observer/", include("observer.urls")),
    path("workspace/", include("workspace.urls")),
    path("api/v0.1/observer/summary", observer_summary, name="world-observer-summary"),
    path("api/v0.1/", include("live_os.api.urls")),
]
