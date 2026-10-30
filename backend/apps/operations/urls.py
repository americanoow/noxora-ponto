from django.urls import path

from . import views

urlpatterns = [
    path("units/", views.UnitListView.as_view(), name="unit-list"),
    path("units/<int:unit_id>/", views.UnitDetailView.as_view(), name="unit-detail"),
    path("sectors/", views.SectorListView.as_view(), name="sector-list"),
    path("sectors/<int:sector_id>/", views.SectorDetailView.as_view(), name="sector-detail"),
    path("employees/", views.EmployeeListView.as_view(), name="employee-list"),
    path("employees/import/", views.EmployeeImportView.as_view(), name="employee-import"),
    path("employees/<int:employee_id>/", views.EmployeeDetailView.as_view(), name="employee-detail"),
    path(
        "employees/<int:employee_id>/access/",
        views.EmployeeAccessView.as_view(),
        name="employee-access",
    ),
    path(
        "employees/<int:employee_id>/assignments/",
        views.EmployeeAssignmentsView.as_view(),
        name="employee-assignments",
    ),
    path(
        "employees/<int:employee_id>/schedules/",
        views.EmployeeSchedulesView.as_view(),
        name="employee-schedules",
    ),
    path("schedules/", views.ScheduleListView.as_view(), name="schedule-list"),
    path("schedules/<int:schedule_id>/", views.ScheduleDetailView.as_view(), name="schedule-detail"),
]
