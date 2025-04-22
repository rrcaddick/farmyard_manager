from django.contrib import admin
from django.utils.html import format_html

from farmyard_manager.entrance.models import Pricing
from farmyard_manager.entrance.models import ReEntry
from farmyard_manager.entrance.models import ReEntryItem
from farmyard_manager.entrance.models import ReEntryItemEditHistory
from farmyard_manager.entrance.models import ReEntryStatusHistory
from farmyard_manager.entrance.models import Ticket
from farmyard_manager.entrance.models import TicketItem
from farmyard_manager.entrance.models import TicketItemEditHistory
from farmyard_manager.entrance.models import TicketStatusHistory


# ----- INLINE ADMIN -----
class TicketStatusHistoryInline(admin.TabularInline):
    model = TicketStatusHistory
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


class TicketItemInline(admin.TabularInline):
    model = TicketItem
    extra = 0
    readonly_fields = ["created", "modified"]
    fields = ["item_type", "visitor_count", "applied_price", "created_by"]
    show_change_link = True


class ReEntryInline(admin.TabularInline):
    model = ReEntry
    extra = 0
    fields = ["status", "visitors_left", "visitors_returned", "completed_time"]
    readonly_fields = ["created"]
    show_change_link = True


class TicketItemEditHistoryInline(admin.TabularInline):
    model = TicketItemEditHistory
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


class ReEntryStatusHistoryInline(admin.TabularInline):
    model = ReEntryStatusHistory
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


class ReEntryItemInline(admin.TabularInline):
    model = ReEntryItem
    extra = 0
    readonly_fields = ["created", "modified"]
    fields = ["item_type", "visitor_count", "applied_price", "created_by"]
    show_change_link = True


class ReEntryItemEditHistoryInline(admin.TabularInline):
    model = ReEntryItemEditHistory
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


# ----- MODEL ADMIN -----
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "ref_number",
        "status",
        "vehicle_link",
        "total_visitors",
        "total_due",
        "created",
    ]
    list_filter = ["status", "created", "modified"]
    search_fields = ["ref_number", "vehicle__plate_number"]
    readonly_fields = ["ref_number", "created", "modified", "is_removed"]
    inlines = [TicketStatusHistoryInline, TicketItemInline, ReEntryInline]

    fieldsets = [
        (None, {"fields": ["ref_number", "status", "vehicle", "payment"]}),
        (
            "Metadata",
            {"fields": ["created", "modified", "is_removed"], "classes": ["collapse"]},
        ),
    ]

    @admin.display(description="Vehicle")
    def vehicle_link(self, obj):
        if obj.vehicle:
            url = f"/admin/vehicles/vehicle/{obj.vehicle.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.vehicle.plate_number)
        return "-"


@admin.register(TicketItem)
class TicketItemAdmin(admin.ModelAdmin):
    list_display = [
        "ticket",
        "item_type",
        "visitor_count",
        "applied_price",
        "created_by",
        "created",
    ]
    readonly_fields = ["created", "modified"]
    list_filter = ["item_type"]
    search_fields = ["ticket__ref_number", "created_by__username"]
    inlines = [TicketItemEditHistoryInline]


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["ticket", "prev_status", "new_status", "performed_by", "created"]
    readonly_fields = ["created", "modified"]
    list_filter = ["prev_status", "new_status"]
    search_fields = ["ticket__ref_number", "performed_by__username"]


@admin.register(TicketItemEditHistory)
class TicketItemEditHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "ticket_item",
        "field",
        "prev_value",
        "new_value",
        "performed_by",
        "created",
    ]
    readonly_fields = ["created", "modified"]
    list_filter = ["field"]
    search_fields = ["ticket_item__ticket__ref_number", "performed_by__username"]


@admin.register(ReEntry)
class ReEntryAdmin(admin.ModelAdmin):
    list_display = [
        "ticket",
        "status",
        "visitors_left",
        "visitors_returned",
        "completed_time",
        "created",
    ]
    readonly_fields = ["created", "modified"]
    list_filter = ["status", "created", "completed_time"]
    search_fields = ["ticket__ref_number"]
    inlines = [ReEntryStatusHistoryInline, ReEntryItemInline]


@admin.register(ReEntryItem)
class ReEntryItemAdmin(admin.ModelAdmin):
    list_display = [
        "re_entry",
        "item_type",
        "visitor_count",
        "applied_price",
        "created_by",
        "created",
    ]
    readonly_fields = ["created", "modified"]
    list_filter = ["item_type"]
    search_fields = ["re_entry__ticket__ref_number", "created_by__username"]
    inlines = [ReEntryItemEditHistoryInline]


@admin.register(ReEntryStatusHistory)
class ReEntryStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["re_entry", "prev_status", "new_status", "performed_by", "created"]
    readonly_fields = ["created", "modified"]
    list_filter = ["prev_status", "new_status"]
    search_fields = ["re_entry__ticket__ref_number", "performed_by__username"]


@admin.register(ReEntryItemEditHistory)
class ReEntryItemEditHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "re_entry_item",
        "field",
        "prev_value",
        "new_value",
        "performed_by",
        "created",
    ]
    readonly_fields = ["created", "modified"]
    list_filter = ["field"]
    search_fields = [
        "re_entry_item__re_entry__ticket__ref_number",
        "performed_by__username",
    ]


@admin.register(Pricing)
class PricingAdmin(admin.ModelAdmin):
    list_display = [
        "ticket_item_type",
        "price",
        "price_start",
        "price_end",
        "is_active",
    ]
    list_filter = ["ticket_item_type", "is_active"]
    search_fields = ["ticket_item_type"]
    readonly_fields = ["created", "modified"]
