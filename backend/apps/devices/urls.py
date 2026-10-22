from django.urls import path

from . import views

urlpatterns = [
    path("devices/", views.DeviceListView.as_view(), name="device-list"),
    path("devices/<int:device_id>/", views.DeviceDetailView.as_view(), name="device-detail"),
    path("devices/<int:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device-revoke"),
    path(
        "devices/<int:device_id>/activation-code/", views.DeviceReissueView.as_view(), name="device-reissue"
    ),
    path("devices/<int:device_id>/locations/", views.DeviceLocationsView.as_view(), name="device-locations"),
]

device_urlpatterns = [
    path("activate/", views.ActivateView.as_view(), name="device-activate"),
    path("me/", views.DeviceMeView.as_view(), name="device-me"),
    path("heartbeat/", views.HeartbeatView.as_view(), name="device-heartbeat"),
    path("rotate-credential/", views.RotateCredentialView.as_view(), name="device-rotate"),
    path("location/", views.LocationView.as_view(), name="device-location"),
    path("employees/", views.RosterLookupView.as_view(), name="device-roster"),
]
