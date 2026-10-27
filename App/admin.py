from django.contrib import admin
from .models import Account, Record, Protocol


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("username", "full_name", "role", "directorate", "ks_region", "station", "created_by", "created_at")
    search_fields = ("username", "full_name")
    list_filter = ("role", "directorate")


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ("uuid", "pole_number", "station", "last_modified", "updated_by")
    search_fields = ("uuid",)

    def pole_number(self, obj):
        return obj.data.get("pole_number") if isinstance(obj.data, dict) else None

    def station(self, obj):
        return obj.data.get("station") if isinstance(obj.data, dict) else None


@admin.register(Protocol)
class ProtocolAdmin(admin.ModelAdmin):
    list_display = ("uuid", "record_uuid", "username", "role", "created_at")
    search_fields = ("record_uuid", "username")
