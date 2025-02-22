import uuid

from django.db import models
from django_extensions.db.models import TimeStampedModel


class BaseModelMixin(models.Model):
    class Meta:
        abstract = True

    def is_new(self):
        return self.pk is None


class UUIDModelMixin(BaseModelMixin, TimeStampedModel, models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        abstract = True
