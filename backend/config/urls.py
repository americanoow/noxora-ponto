from django.contrib import admin
from django.urls import include, path

from apps.devices.urls import device_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/companies/", include("apps.companies.urls")),
    path("api/companies/<int:company_id>/", include("apps.operations.urls")),
    path("api/companies/<int:company_id>/", include("apps.devices.urls")),
    path("api/device/", include(device_urlpatterns)),
]
