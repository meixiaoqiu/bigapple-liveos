from django.urls import path

from . import views

urlpatterns = [
    path("", views.feedback_list, name="feedback-list"),
    path("new/", views.feedback_create, name="feedback-create"),
    path("<str:feedback_id>/", views.feedback_detail, name="feedback-detail"),
    path("<str:feedback_id>/respond/", views.feedback_respond, name="feedback-respond"),
]
