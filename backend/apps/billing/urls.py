from django.urls import path

from . import views

company_urlpatterns = [
    path("billing/", views.CompanyBillingView.as_view(), name="billing"),
    path("billing/plan/", views.CompanyPlanChangeView.as_view(), name="billing-plan"),
    path("billing/cancel/", views.CompanyCancelView.as_view(), name="billing-cancel"),
]

platform_urlpatterns = [
    path("plans/", views.PlatformPlanListView.as_view(), name="platform-plans"),
    path("subscriptions/", views.PlatformSubscriptionListView.as_view(), name="platform-subscriptions"),
    path(
        "companies/<int:company_id>/subscription/",
        views.PlatformCompanySubscriptionView.as_view(),
        name="platform-company-subscription",
    ),
    path("billing/run/", views.PlatformRunBillingView.as_view(), name="platform-billing-run"),
    path(
        "invoices/<int:invoice_id>/simulate/",
        views.PlatformSimulatePaymentView.as_view(),
        name="platform-invoice-simulate",
    ),
]

webhook_urlpatterns = [
    path("<str:gateway>/", views.WebhookView.as_view(), name="billing-webhook"),
]
