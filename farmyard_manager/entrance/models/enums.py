from django.db import models

from farmyard_manager.core.models import TransitionTextChoices


class ItemTypeChoices(models.TextChoices):
    PUBLIC = ("public", "Public")
    GROUP = ("group", "Group")
    SCHOOL = ("school", "School")
    ONLINE = ("online", "Online")
    VOIDED = ("voided", "VOIDED")


class TicketStatusChoices(TransitionTextChoices):
    PENDING_SECURITY = ("pending_security", "Pending Security")
    PASSED_SECURITY = ("passed_security", "Passed Security")
    COUNTED = ("counted", "Visitors Counted")
    PROCESSED = ("processed", "Processed")
    REFUNDED = ("refunded", "Ticket Refunded")

    @classmethod
    def get_transition_map(cls) -> dict:
        return {
            cls.PENDING_SECURITY: [cls.PASSED_SECURITY],
            cls.PASSED_SECURITY: [cls.COUNTED],
            cls.COUNTED: [cls.PROCESSED],
            cls.PROCESSED: [cls.REFUNDED],
            cls.REFUNDED: [],
        }


class ReEntryStatusChoices(TransitionTextChoices):
    PENDING = ("pending", "Pending")
    PENDING_PAYMENT = ("pending_payment", "Pending Payment")
    PROCESSED = ("processed", "Processed")
    REFUNDED = ("refunded", "Re-Entry Refunded")

    @classmethod
    def get_transition_map(cls) -> dict:
        return {
            cls.PENDING: [cls.PENDING_PAYMENT, cls.PROCESSED],
            cls.PENDING_PAYMENT: [cls.PROCESSED],
            cls.PROCESSED: [cls.REFUNDED],
            cls.REFUNDED: [],
        }
