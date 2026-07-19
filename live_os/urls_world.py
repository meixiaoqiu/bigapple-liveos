"""Single-world runtime URL configuration shared by bigreal.local and bigsim.local.

``observer`` is the internal app / module name.  The public entrypoints are at
the site root (``/``, ``/events/``, ``/u/<member_no>/``, etc.).
"""

from django.urls import include, path

from applications import views as application_views
from observer.api_views import observer_summary
from worlds import views as world_views
from worlds.routing import world_scoped_view


urlpatterns = [
    path("login/", world_views.WorldLoginView.as_view(), name="world-login"),
    path("logout/", world_views.world_logout, name="world-logout"),
    path("register/", world_scoped_view(application_views.register_page), name="register-page"),
    path("workspace/", include("workspace.urls")),
    path("feedback/", include("feedback.urls")),
    path("api/v0.1/observer/summary", observer_summary, name="world-observer-summary"),
    path("api/v0.1/", include("live_os.api.urls")),
    path("", include("observer.urls")),
]

handler400 = "live_os.error_handlers.bad_request"
handler403 = "live_os.error_handlers.permission_denied"
handler404 = "live_os.error_handlers.page_not_found"
handler500 = "live_os.error_handlers.server_error"
