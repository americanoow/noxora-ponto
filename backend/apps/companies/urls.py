from django.urls import path

from . import views

urlpatterns = [
    path("", views.CompanyListView.as_view(), name="company-list"),
    path("<int:company_id>/", views.CompanyDetailView.as_view(), name="company-detail"),
    path("<int:company_id>/members/", views.MemberListView.as_view(), name="member-list"),
    path("<int:company_id>/members/<int:member_id>/", views.MemberDetailView.as_view(), name="member-detail"),
    path("<int:company_id>/audit/", views.AuditListView.as_view(), name="audit-list"),
]
