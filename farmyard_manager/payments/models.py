from django.db import models
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin


class Payment(UUIDModelMixin, TimeStampedModel, SoftDeletableModel, models.Model):
    def __str__(self):
        return NotImplemented
