from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class EntranceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "farmyard_manager.entrance"
    verbose_name = _("Entrance")
