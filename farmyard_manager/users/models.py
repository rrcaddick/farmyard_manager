from django.contrib.auth.models import AbstractUser
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin


class User(AbstractUser, UUIDModelMixin, TimeStampedModel):
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

    def get_active_shift(self):
        """Get the user's active shift."""

    @property
    def is_manager(self) -> bool:
        """Check if user has permission to process refunds."""
        return True  # Placeholder implementation

    def __str__(self) -> str:
        return self.name if self.name else self.username
