from django.db import models


class ShiftStatusChoices(models.TextChoices):
    ACTIVE = ("active", "Active")
    CLOSED = ("closed", "Closed")
    SUSPENDED = ("suspended", "Suspended")
