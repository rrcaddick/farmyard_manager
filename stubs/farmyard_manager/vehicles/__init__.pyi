from django.db import models

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.entrance.models.base import BaseEntranceRecord

class ReEntry(BaseEntranceRecord, CleanBeforeSaveModel, models.Model):
    objects: ReEntryManager
