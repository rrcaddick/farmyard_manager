from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class VehiclesConfig(AppConfig):
    name = "farmyard_manager.vehicles"
    verbose_name = _("Vehicles")
