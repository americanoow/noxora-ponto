from django.urls import path

from . import views

urlpatterns = [
    path("me/punches/", views.MyPunchesView.as_view(), name="me-punches"),
    path("me/punches/<int:record_id>/receipt/", views.MyReceiptView.as_view(), name="me-receipt"),
    path("me/closings/", views.MyClosingsView.as_view(), name="me-closings"),
    path(
        "me/closings/<int:closing_id>/acknowledge/", views.MyClosingAckView.as_view(), name="me-closing-ack"
    ),
    path("me/timesheet.pdf", views.MyTimesheetPdfView.as_view(), name="me-timesheet-pdf"),
    path("me/data.json", views.MyDataView.as_view(), name="me-data"),
    path("reports/timesheet/", views.TimesheetExportView.as_view(), name="report-timesheet"),
    path("reports/summary.csv", views.SummaryExportView.as_view(), name="report-summary"),
    path("reports/time-records.csv", views.TimeRecordsExportView.as_view(), name="report-time-records"),
    path("time-records/<int:record_id>/receipt.pdf", views.ReceiptPdfView.as_view(), name="report-receipt"),
    path(
        "attendance/closings/<int:closing_id>/acknowledgements/",
        views.AcknowledgementListView.as_view(),
        name="closing-acknowledgements",
    ),
]
