from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ShiftsConfig(AppConfig):
    name = "farmyard_manager.shifts"
    verbose_name = _("Shifts")
