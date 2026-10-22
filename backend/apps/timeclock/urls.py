from django.urls import path

from . import views

urlpatterns = [
    path("time-records/", views.TimeRecordListView.as_view(), name="timerecord-list"),
    path("time-records/<int:record_id>/", views.TimeRecordDetailView.as_view(), name="timerecord-detail"),
    path("employer/", views.EmployerView.as_view(), name="employer"),
]

device_urlpatterns = [
    path("punches/", views.PunchView.as_view(), name="device-punch"),
    path("punches/<int:record_id>/receipt/", views.PunchReceiptView.as_view(), name="device-punch-receipt"),
]
