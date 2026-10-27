from django.urls import path

from . import views

urlpatterns = [
    path("availability/", views.BoardView.as_view(), name="availability-board"),
    path("availability/settings/", views.SettingsView.as_view(), name="availability-settings"),
    path(
        "availability/employees/<int:employee_id>/", views.HistoryView.as_view(), name="availability-history"
    ),
    path("me/availability/", views.MyAvailabilityView.as_view(), name="me-availability"),
]
