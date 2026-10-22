from django.contrib import admin
from django.urls import include, path

from apps.biometrics.urls import device_urlpatterns as biometrics_device_urlpatterns
from apps.devices.urls import device_urlpatterns
from apps.timeclock.urls import device_urlpatterns as timeclock_device_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/companies/", include("apps.companies.urls")),
    path("api/companies/<int:company_id>/", include("apps.operations.urls")),
    path("api/companies/<int:company_id>/", include("apps.devices.urls")),
    path("api/companies/<int:company_id>/", include("apps.timeclock.urls")),
    path("api/device/", include(device_urlpatterns)),
    path("api/device/", include(timeclock_device_urlpatterns)),
    path("api/companies/<int:company_id>/", include("apps.biometrics.urls")),
    path("api/device/", include(biometrics_device_urlpatterns)),
]
