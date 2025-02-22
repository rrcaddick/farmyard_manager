from django.contrib import admin

from .models import Blacklist
from .models import SecurityFail
from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("make", "model", "plate_number", "security_fails", "is_blacklisted")
    list_filter = ("make", "plate_number", "is_blacklisted")
    search_fields = ("plate_number", "make", "model")
    readonly_fields = ("security_fails", "is_blacklisted")


@admin.register(SecurityFail)
class SecurityFailAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "failure_type", "reported_by", "failure_date")
    list_filter = ("failure_type", "failure_date", "reported_by")
    search_fields = ("vehicle__plate_number",)


@admin.register(Blacklist)
class BlacklistAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "reason", "created_by")
    list_filter = ("vehicle", "reason")
    search_fields = ("vehicle__plate_number", "reason")
