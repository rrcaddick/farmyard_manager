from django.contrib import admin
from django.utils.html import format_html

from farmyard_manager.entrance.models import EditHistory
from farmyard_manager.entrance.models import Pricing
from farmyard_manager.entrance.models import ReEntry
from farmyard_manager.entrance.models import ReEntryAddition
from farmyard_manager.entrance.models import StatusHistory
from farmyard_manager.entrance.models import Ticket


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = [
        "created",
        "modified",
        "prev_status",
        "new_status",
        "performed_by",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class EditHistoryInline(admin.TabularInline):
    model = EditHistory
    extra = 0
    readonly_fields = [
        "created",
        "modified",
        "field",
        "prev_value",
        "new_value",
        "performed_by",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ReEntryInline(admin.TabularInline):
    model = ReEntry
    extra = 0
    fields = [
        "status",
        "visitors_left",
        "visitors_returned",
        "created",
        "created_by",
        "completed_time",
        "completed_by",
    ]
    readonly_fields = ["created"]


class ReEntryAdditionInline(admin.TabularInline):
    model = ReEntryAddition
    extra = 0
    fields = ["status", "visitor_count", "applied_price", "payment"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "ticket_number",
        "status",
        "type",
        "vehicle_link",
        "visitor_count",
        "applied_price",
        "created",
        "modified",
    ]
    list_filter = ["status", "type", "created", "modified"]
    search_fields = ["ticket_number", "vehicle__plate_number"]
    readonly_fields = ["ticket_number", "created", "modified"]
    inlines = [StatusHistoryInline, EditHistoryInline, ReEntryInline]
    fieldsets = [
        (
            None,
            {
                "fields": ["ticket_number", "status", "type", "vehicle"],
            },
        ),
        (
            "Visitor Information",
            {
                "fields": ["visitor_count", "applied_price"],
            },
        ),
        (
            "Payment",
            {
                "fields": ["payment"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["created", "modified", "is_removed"],
                "classes": ["collapse"],
            },
        ),
    ]

    @admin.display(
        description="Vehicle",
    )
    def vehicle_link(self, obj):
        if obj.vehicle:
            url = f"/admin/vehicles/vehicle/{obj.vehicle.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.vehicle.plate_number)
        return "-"


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["ticket", "prev_status", "new_status", "performed_by", "created"]
    list_filter = ["prev_status", "new_status", "created"]
    search_fields = ["ticket__ticket_number", "performed_by__username"]
    readonly_fields = ["created", "modified"]


@admin.register(EditHistory)
class EditHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "ticket",
        "field",
        "prev_value",
        "new_value",
        "performed_by",
        "created",
    ]
    list_filter = ["field", "created"]
    search_fields = ["ticket__ticket_number", "performed_by__username"]
    readonly_fields = ["created", "modified"]


@admin.register(Pricing)
class PricingAdmin(admin.ModelAdmin):
    list_display = ["ticket_type", "price", "applies_from", "applies_to", "is_active"]
    list_filter = ["ticket_type", "is_active"]
    search_fields = ["ticket_type"]
    readonly_fields = ["created", "modified"]


@admin.register(ReEntry)
class ReEntryAdmin(admin.ModelAdmin):
    list_display = [
        "ticket",
        "status",
        "visitors_left",
        "visitors_returned",
        "created",
        "created_by",
        "completed_time",
        "completed_by",
    ]
    list_filter = ["status", "created", "completed_time"]
    search_fields = [
        "ticket__ticket_number",
        "created_by__username",
        "completed_by__username",
    ]
    readonly_fields = ["created", "modified"]
    inlines = [ReEntryAdditionInline]


@admin.register(ReEntryAddition)
class ReEntryAdditionAdmin(admin.ModelAdmin):
    list_display = [
        "re_entry",
        "ticket",
        "status",
        "visitor_count",
        "applied_price",
        "payment",
    ]
    list_filter = ["status"]
    search_fields = ["ticket__ticket_number", "re_entry__id"]
    readonly_fields = ["created", "modified"]
