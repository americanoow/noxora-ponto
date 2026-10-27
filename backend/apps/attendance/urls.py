from django.urls import path

from . import views

urlpatterns = [
    path("attendance/rules/", views.RuleSetListView.as_view(), name="attendance-rules"),
    path("attendance/holidays/", views.HolidayListView.as_view(), name="attendance-holidays"),
    path(
        "attendance/holidays/<int:holiday_id>/", views.HolidayDetailView.as_view(), name="attendance-holiday"
    ),
    path("attendance/timesheet/", views.TimesheetView.as_view(), name="attendance-timesheet"),
    path("attendance/summary/", views.SummaryView.as_view(), name="attendance-summary"),
    path("attendance/requests/", views.RequestListView.as_view(), name="attendance-requests"),
    path(
        "attendance/<str:kind>/<int:item_id>/decision/",
        views.DecisionView.as_view(),
        name="attendance-decision",
    ),
    path("attendance/closings/", views.ClosingListView.as_view(), name="attendance-closings"),
    path(
        "attendance/closings/<int:closing_id>/", views.ClosingDetailView.as_view(), name="attendance-closing"
    ),
    path(
        "attendance/closings/<int:closing_id>/reopen/",
        views.ClosingReopenView.as_view(),
        name="attendance-closing-reopen",
    ),
    path("me/timesheet/", views.MyTimesheetView.as_view(), name="me-timesheet"),
    path("me/requests/", views.MyRequestsView.as_view(), name="me-requests"),
    path(
        "me/<str:kind>/<int:item_id>/cancel/", views.MyRequestCancelView.as_view(), name="me-request-cancel"
    ),
]
