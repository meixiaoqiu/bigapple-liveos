from django.urls import path
from worlds.routing import world_scoped_view

from . import views


urlpatterns = [
    path("member/", world_scoped_view(views.member_application_page), name="member-application-page"),
    path("partner/", world_scoped_view(views.partner_application_page), name="partner-application-page"),
]
