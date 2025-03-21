from typing import TYPE_CHECKING

from django.db import models
from django.db import transaction
from model_utils.managers import SoftDeletableManager

if TYPE_CHECKING:
    from farmyard_manager.entrance.models import ReEntry
    from farmyard_manager.entrance.models import Ticket
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Vehicle


class TicketManager(SoftDeletableManager, models.Manager):
    model: type["Ticket"]

    def _validate_price(self, ticket_type):
        # TODO: Implement price validation logic
        return True

    def create_queue_ticket(
        self,
        status: str,
        vehicle: "Vehicle",
        performed_by: "User",
        ticket_number: int | None = None,
        **kwargs,
    ):
        """Create a ticket with correct price and initial status."""
        if performed_by is None:
            error_message = "performed_by is required for new tickets"
            raise ValueError(error_message)

        with transaction.atomic():
            ticket_data = {
                "status": status,
                "vehicle": vehicle,
                **kwargs,
            }

            if ticket_number is not None:
                ticket_data["ticket_number"] = ticket_number

            ticket = self.model(**ticket_data)
            ticket.save()

            ticket.add_initial_status(
                status=status,
                performed_by=performed_by,
            )

            return ticket

    def sync_offline_queue_ticket(
        self,
        vehicle: "Vehicle",
        performed_by: "User",
        **kwargs,
    ):
        # status  self.model.StatusChoices.PENDING_SECURITY
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        pass

    def sync_offline_security_check(self):
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        pass

    def sync_offline_visitor_ticket(self):
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        # Overwrite ticket number with incoming ticket number
        pass

    def sync_offline_cash_payment(self):
        # TODO: Decide what to do if incoming offline price charged does not validate
        # Check for ticket for today matching license plate
        # Create ticket if no match
        # Update ticket if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        # Overwrite ticket number with incoming ticket number
        pass


class ReEntryManager(models.Manager):
    model: type["ReEntry"]

    def create_re_entry(
        self,
        ticket: "Ticket",
        visitors_left: int,
        created_by: "User",
        **kwargs,
    ):
        if ticket.status not in [
            ticket.StatusChoices.PAID,
            ticket.StatusChoices.GROUP_ENTRY_PROCESSED,
            ticket.StatusChoices.SCHOOL_ENTRY_PROCESSED,
            ticket.StatusChoices.ONLINE_ENTRY_PROCESSED,
        ]:
            error_message = "Cannot issue Re-Emntry on un processed tickets"
            raise ValueError(error_message)

        re_entry = self.model(
            ticket=ticket,
            visitors_left=visitors_left,
            created_by=created_by,
            **kwargs,
        )

        re_entry.save()

        return re_entry

    def sync_offline_re_entry(self):
        # Check for re-entry for today matching license plate
        # Create re-entry if no match
        # Update re-entry if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        pass
