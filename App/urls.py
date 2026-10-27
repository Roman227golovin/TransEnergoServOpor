from django.urls import path
from . import views_accounts, views_sync, views_protocols, views_web

urlpatterns = [
    path("accounts/login", views_accounts.login),
    path("accounts/register", views_accounts.register),
    path("sync/push", views_sync.push_records),
    path("sync/pull", views_sync.pull_records),
    path("sync/search", views_sync.search_records),
    path("sync/upload-photo", views_sync.upload_photo),
    path("sync/server-address", views_sync.server_address),
    path("protocols/upload", views_protocols.upload_protocol),
    path("protocols/", views_protocols.list_protocols),

    path("web/login/", views_web.web_login, name="web_login"),
    path("web/logout/", views_web.web_logout, name="web_logout"),
    path("web/", views_web.web_home, name="web_home"),
    path("web/records/", views_web.web_pole_book, name="web_pole_book"),
    path("web/station/", views_web.web_station_records, name="web_station_records"),
    path("web/add-pole/", views_web.web_add_pole, name="web_add_pole"),
    path("web/record/<str:record_uuid>/", views_web.web_record_detail, name="web_record_detail"),

    path("web/info/", views_web.web_info, name="web_info"),
    path("web/info/files/<str:category>/", views_web.web_org_files, name="web_org_files"),
    path("web/info/files/delete/<str:file_uuid>/", views_web.web_org_file_delete, name="web_org_file_delete"),
    path("web/stub/<str:slug>/", views_web.web_stub, name="web_stub"),

    path("web/work/", views_web.web_work, name="web_work"),
    path("web/work/install-pole/", views_web.web_install_pole, name="web_install_pole"),
    path("web/work/dismantle/", views_web.web_dismantle, name="web_dismantle"),
    path("web/work/dismantle/station/", views_web.web_dismantle_station, name="web_dismantle_station"),
    path("web/work/dismantle/<str:record_uuid>/", views_web.web_dismantle_pole, name="web_dismantle_pole"),

    path("web/planning/", views_web.web_planning, name="web_planning"),
    path("web/planning/pole-economy/", views_web.web_pole_economy, name="web_pole_economy"),
    path("web/planning/diagnostics/", views_web.web_diagnostics, name="web_diagnostics"),
    path("web/planning/diagnostics/station/", views_web.web_diagnostics_station, name="web_diagnostics_station"),
]
