from django.urls import path

from . import views

urlpatterns = [
    path("fiscal/afd/", views.AfdView.as_view(), name="fiscal-afd"),
    path("fiscal/payroll-profiles/", views.PayrollProfileListView.as_view(), name="fiscal-payroll-profiles"),
    path("fiscal/payroll-export/", views.PayrollExportView.as_view(), name="fiscal-payroll-export"),
    path("fiscal/files/", views.GeneratedFileListView.as_view(), name="fiscal-files"),
]
