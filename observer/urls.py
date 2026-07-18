from django.urls import path

from . import page_views, theme_views


urlpatterns = [
    path("", page_views.observer_page, name="observer-page"),
    path("simulations/", page_views.simulation_report_list_page, name="observer-simulation-reports"),
    path(
        "simulations/<str:snapshot_id>/",
        page_views.simulation_report_detail_page,
        name="observer-simulation-report-detail",
    ),
    path("dashboard/partials/missions/", page_views.dashboard_missions_partial, name="dashboard-missions-partial"),
    path("dashboard/partials/events/", page_views.dashboard_events_partial, name="dashboard-events-partial"),
    path(
        "dashboard/partials/map-points/",
        page_views.dashboard_map_points_partial,
        name="dashboard-map-points-partial",
    ),
    path(
        "dashboard/partials/task-detail/",
        page_views.dashboard_task_detail_partial,
        name="dashboard-task-detail-partial",
    ),
    path("dashboard/partials/risk/", page_views.dashboard_risk_partial, name="dashboard-risk-partial"),
    path("dashboard/partials/capacity/", page_views.dashboard_capacity_partial, name="dashboard-capacity-partial"),
    path(
        "dashboard/partials/photo-stories/",
        page_views.dashboard_photo_story_partial,
        name="dashboard-photo-story-partial",
    ),
    path("events/", page_views.observer_events_list, name="observer-events-list"),
    path("events/<str:event_id>/", page_views.observer_event_detail, name="observer-event-detail"),
    path("member-applications/<str:application_id>/", page_views.observer_member_application_detail, name="observer-member-application-detail"),
    path("u/<str:member_no>/", page_views.observer_member_profile, name="observer-member-profile"),
    path("event-ledger/", page_views.observer_event_ledger_list, name="observer-event-ledger-list"),
    path("event-ledger/<int:seq>/", page_views.observer_event_ledger_detail, name="observer-event-ledger-detail"),
    path("themes/switch/", theme_views.switch_theme, name="switch-theme"),
]
