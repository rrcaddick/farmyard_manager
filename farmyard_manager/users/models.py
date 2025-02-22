import uuid

from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.db.models import UUIDField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_extensions.db.models import TimeStampedModel


class User(AbstractUser, TimeStampedModel):
    uuid = UUIDField(unique=True, default=uuid.uuid4, editable=False)
    name = CharField(_("Name of User"), blank=True, max_length=255)

    # Remove unwanted AbstractUser fields
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    @staticmethod
    def get_admin_user():
        return User.objects.get(username="admin")

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})
