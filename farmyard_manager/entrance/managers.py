from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any

from django.db import models
from django.db import transaction
from django.utils import timezone
from model_utils.managers import SoftDeletableManager
from model_utils.managers import SoftDeletableQuerySet

if TYPE_CHECKING:
    from farmyard_manager.entrance.models import ReEntry
    from farmyard_manager.entrance.models import Ticket
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Vehicle


class TicketQuerySet(SoftDeletableQuerySet["Ticket"], models.QuerySet["Ticket"]):
    """Custom QuerySet for Ticket model with chainable methods"""

    def pending_security(self) -> "TicketQuerySet":
        """Get tickets pending security check"""
        return self.filter(status="pending_security")

    def passed_security(self) -> "TicketQuerySet":
        """Get tickets that passed security"""
        return self.filter(status="passed_security")

    def counted(self) -> "TicketQuerySet":
        """Get tickets with visitors counted"""
        return self.filter(status="counted")

    def processed(self) -> "TicketQuerySet":
        """Get processed tickets"""
        return self.filter(status="processed")

    def refunded(self) -> "TicketQuerySet":
        """Get refunded tickets"""
        return self.filter(status="refunded")

    def by_status(self, status: str) -> "TicketQuerySet":
        """Get tickets by specific status"""
        return self.filter(status=status)

    def for_vehicle(self, vehicle: "Vehicle") -> "TicketQuerySet":
        """Get tickets for specific vehicle"""
        return self.filter(vehicle=vehicle).order_by("-created")

    def for_today(self) -> "TicketQuerySet":
        """Get tickets created today"""
        today = timezone.now().date()
        start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        return self.filter(created__range=[start_of_day, end_of_day])

    def with_payment(self) -> "TicketQuerySet":
        """Get tickets that have a payment assigned"""
        return self.filter(payment__isnull=False)

    def without_payment(self) -> "TicketQuerySet":
        """Get tickets without payment"""
        return self.filter(payment__isnull=True)

    def by_plate_number(self, plate_number: str) -> "TicketQuerySet":
        """Get tickets by vehicle plate number"""
        return self.filter(vehicle__plate_number__icontains=plate_number)

    def with_re_entries(self) -> "TicketQuerySet":
        """Get tickets that have re-entries"""
        return self.filter(re_entries__isnull=False).distinct()

    def by_date_range(self, start_date, end_date) -> "TicketQuerySet":
        """Get tickets within date range"""
        start_datetime = timezone.make_aware(
            datetime.combine(start_date, datetime.min.time()),
        )
        end_datetime = timezone.make_aware(
            datetime.combine(end_date, datetime.max.time()),
        )
        return self.filter(created__range=[start_datetime, end_datetime])


class TicketManager(SoftDeletableManager["Ticket"], models.Manager["Ticket"]):
    """Custom Manager for Ticket model with business logic methods"""

    def get_queryset(self) -> TicketQuerySet:
        """Return custom QuerySet"""
        return TicketQuerySet(self.model, using=self._db)

    def _validate_price(self, ticket_type: str) -> bool:  # noqa: ARG002
        """Validate pricing for ticket type"""
        # TODO: Implement price validation logic
        return True

    def create_ticket(
        self,
        status: str,
        vehicle: "Vehicle",
        performed_by: "User",
        ref_number: str | None = None,
        **kwargs: Any,
    ) -> "Ticket":
        """Create a new ticket with status history"""
        if performed_by is None:
            error_message = "performed_by is required for new tickets"
            raise ValueError(error_message)

        with transaction.atomic():
            ticket_data = {
                "status": status,
                "vehicle": vehicle,
                **kwargs,
            }

            if ref_number is not None:
                ticket_data["ref_number"] = ref_number

            ticket = self.model(**ticket_data)

            save_kwargs = {} if ref_number is None else {"ref_number": ref_number}
            ticket.save(**save_kwargs)

            ticket.status_history_model.objects.create(
                ticket=ticket,
                prev_status="",
                new_status=status,
                performed_by=performed_by,
            )

            return ticket

    def sync_offline_queue_ticket(
        self,
        vehicle: "Vehicle",
        performed_by: "User",
        **kwargs: Any,
    ) -> None:
        """Sync offline queue ticket data"""
        # TODO: Implement offline queue ticket sync
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified

    def sync_offline_security_check(
        self,
        ticket_data: dict[str, Any],
        performed_by: "User",
        **kwargs: Any,
    ) -> None:
        """Sync offline security check data"""
        # TODO: Implement offline security check sync
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified

    def sync_offline_visitor_ticket(
        self,
        ticket_data: dict[str, Any],
        performed_by: "User",
        **kwargs: Any,
    ) -> None:
        """Sync offline visitor ticket data"""
        # TODO: Implement offline visitor ticket sync
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        # Overwrite ticket number with incoming ticket number

    def sync_offline_cash_payment(
        self,
        payment_data: dict[str, Any],
        performed_by: "User",
        **kwargs: Any,
    ) -> None:
        """Sync offline cash payment data"""
        # TODO: Implement offline cash payment sync
        # TODO: Decide what to do if incoming offline price charged does not validate
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        # Overwrite ticket number with incoming ticket number

    # Delegate QuerySet methods for IntelliSense support
    def pending_security(self) -> TicketQuerySet:
        """Get tickets pending security check"""
        return self.get_queryset().pending_security()

    def passed_security(self) -> TicketQuerySet:
        """Get tickets that passed security"""
        return self.get_queryset().passed_security()

    def counted(self) -> TicketQuerySet:
        """Get tickets with visitors counted"""
        return self.get_queryset().counted()

    def processed(self) -> TicketQuerySet:
        """Get processed tickets"""
        return self.get_queryset().processed()

    def refunded(self) -> TicketQuerySet:
        """Get refunded tickets"""
        return self.get_queryset().refunded()

    def by_status(self, status: str) -> TicketQuerySet:
        """Get tickets by specific status"""
        return self.get_queryset().by_status(status)

    def for_vehicle(self, vehicle: "Vehicle") -> TicketQuerySet:
        """Get tickets for specific vehicle"""
        return self.get_queryset().for_vehicle(vehicle)

    def for_today(self) -> TicketQuerySet:
        """Get tickets created today"""
        return self.get_queryset().for_today()

    def with_payment(self) -> TicketQuerySet:
        """Get tickets that have a payment assigned"""
        return self.get_queryset().with_payment()

    def without_payment(self) -> TicketQuerySet:
        """Get tickets without payment"""
        return self.get_queryset().without_payment()

    def by_plate_number(self, plate_number: str) -> TicketQuerySet:
        """Get tickets by vehicle plate number"""
        return self.get_queryset().by_plate_number(plate_number)

    def with_re_entries(self) -> TicketQuerySet:
        """Get tickets that have re-entries"""
        return self.get_queryset().with_re_entries()

    def by_date_range(self, start_date, end_date) -> TicketQuerySet:
        """Get tickets within date range"""
        return self.get_queryset().by_date_range(start_date, end_date)


class ReEntryQuerySet(SoftDeletableQuerySet["ReEntry"], models.QuerySet["ReEntry"]):
    """Custom QuerySet for ReEntry model with chainable methods"""

    def pending(self) -> "ReEntryQuerySet":
        """Get pending re-entries"""
        return self.filter(status="pending")

    def pending_payment(self) -> "ReEntryQuerySet":
        """Get re-entries pending payment"""
        return self.filter(status="pending_payment")

    def processed(self) -> "ReEntryQuerySet":
        """Get processed re-entries"""
        return self.filter(status="processed")

    def refunded(self) -> "ReEntryQuerySet":
        """Get refunded re-entries"""
        return self.filter(status="refunded")

    def by_status(self, status: str) -> "ReEntryQuerySet":
        """Get re-entries by specific status"""
        return self.filter(status=status)

    def for_ticket(self, ticket: "Ticket") -> "ReEntryQuerySet":
        """Get re-entries for specific ticket"""
        return self.filter(ticket=ticket).order_by("-created")

    def for_vehicle(self, vehicle: "Vehicle") -> "ReEntryQuerySet":
        """Get re-entries for specific vehicle"""
        return self.filter(ticket__vehicle=vehicle).order_by("-created")

    def for_today(self) -> "ReEntryQuerySet":
        """Get re-entries created today"""
        today = timezone.now().date()
        start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))
        return self.filter(created__range=[start_of_day, end_of_day])

    def with_payment(self) -> "ReEntryQuerySet":
        """Get re-entries that have a payment assigned"""
        return self.filter(payment__isnull=False)

    def without_payment(self) -> "ReEntryQuerySet":
        """Get re-entries without payment"""
        return self.filter(payment__isnull=True)

    def with_additional_visitors(self) -> "ReEntryQuerySet":
        """Get re-entries where more visitors returned than left"""
        return self.filter(visitors_returned__gt=models.F("visitors_left"))

    def completed(self) -> "ReEntryQuerySet":
        """Get re-entries that have been completed"""
        return self.filter(completed_time__isnull=False)

    def incomplete(self) -> "ReEntryQuerySet":
        """Get re-entries that are not yet completed"""
        return self.filter(completed_time__isnull=True)

    def by_date_range(self, start_date, end_date) -> "ReEntryQuerySet":
        """Get re-entries within date range"""
        start_datetime = timezone.make_aware(
            datetime.combine(start_date, datetime.min.time()),
        )
        end_datetime = timezone.make_aware(
            datetime.combine(end_date, datetime.max.time()),
        )
        return self.filter(created__range=[start_datetime, end_datetime])


class ReEntryManager(SoftDeletableManager["ReEntry"], models.Manager["ReEntry"]):
    """Custom Manager for ReEntry model with business logic methods"""

    def get_queryset(self) -> ReEntryQuerySet:
        """Return custom QuerySet"""
        return ReEntryQuerySet(self.model, using=self._db)

    def create_re_entry(
        self,
        ticket: "Ticket",
        visitors_left: int,
        created_by: "User",  # noqa: ARG002
        **kwargs: Any,
    ) -> "ReEntry":
        """Create a new re-entry with validation"""
        if not ticket.is_processed:
            error_message = "Cannot issue Re-Entry on un processed tickets"
            raise ValueError(error_message)

        re_entry = self.model(
            ticket=ticket,
            visitors_left=visitors_left,
            **kwargs,
        )

        re_entry.save()
        return re_entry

    def sync_offline_re_entry(
        self,
        re_entry_data: dict[str, Any],
        created_by: "User",
        **kwargs: Any,
    ) -> None:
        """Sync offline re-entry data"""
        # TODO: Implement offline re-entry sync
        # Check for re-entry for today matching license plate
        # Create re-entry if no match
        # Update re-entry if match - Overwrite created if earlier than current created
        # Update modified if later than current modified

    # Delegate QuerySet methods for IntelliSense support
    def pending(self) -> ReEntryQuerySet:
        """Get pending re-entries"""
        return self.get_queryset().pending()

    def pending_payment(self) -> ReEntryQuerySet:
        """Get re-entries pending payment"""
        return self.get_queryset().pending_payment()

    def processed(self) -> ReEntryQuerySet:
        """Get processed re-entries"""
        return self.get_queryset().processed()

    def refunded(self) -> ReEntryQuerySet:
        """Get refunded re-entries"""
        return self.get_queryset().refunded()

    def by_status(self, status: str) -> ReEntryQuerySet:
        """Get re-entries by specific status"""
        return self.get_queryset().by_status(status)

    def for_ticket(self, ticket: "Ticket") -> ReEntryQuerySet:
        """Get re-entries for specific ticket"""
        return self.get_queryset().for_ticket(ticket)

    def for_vehicle(self, vehicle: "Vehicle") -> ReEntryQuerySet:
        """Get re-entries for specific vehicle"""
        return self.get_queryset().for_vehicle(vehicle)

    def for_today(self) -> ReEntryQuerySet:
        """Get re-entries created today"""
        return self.get_queryset().for_today()

    def with_payment(self) -> ReEntryQuerySet:
        """Get re-entries that have a payment assigned"""
        return self.get_queryset().with_payment()

    def without_payment(self) -> ReEntryQuerySet:
        """Get re-entries without payment"""
        return self.get_queryset().without_payment()

    def with_additional_visitors(self) -> ReEntryQuerySet:
        """Get re-entries where more visitors returned than left"""
        return self.get_queryset().with_additional_visitors()

    def completed(self) -> ReEntryQuerySet:
        """Get re-entries that have been completed"""
        return self.get_queryset().completed()

    def incomplete(self) -> ReEntryQuerySet:
        """Get re-entries that are not yet completed"""
        return self.get_queryset().incomplete()

    def by_date_range(self, start_date, end_date) -> ReEntryQuerySet:
        """Get re-entries within date range"""
        return self.get_queryset().by_date_range(start_date, end_date)
