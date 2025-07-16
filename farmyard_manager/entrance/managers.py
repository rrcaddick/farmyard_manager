from typing import TYPE_CHECKING

from django.db import models
from django.db import transaction
from model_utils.managers import SoftDeletableManager

if TYPE_CHECKING:
    from farmyard_manager.entrance.models import ReEntry  # noqa: F401
    from farmyard_manager.entrance.models import Ticket
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Vehicle


class TicketManager(SoftDeletableManager["Ticket"], models.Manager["Ticket"]):
    def _validate_price(self, ticket_type):  # noqa: ARG002
        # TODO: Implement price validation logic
        return True

    def create_ticket(self, status, vehicle, performed_by, ref_number=None, **kwargs):
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


class ReEntryManager(SoftDeletableManager["ReEntry"], models.Manager["ReEntry"]):
    def create_re_entry(
        self,
        ticket: "Ticket",
        visitors_left: int,
        created_by: "User",  # noqa: ARG002
        **kwargs,
    ):
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

    def sync_offline_re_entry(self):
        # Check for re-entry for today matching license plate
        # Create re-entry if no match
        # Update re-entry if match - Overwrite created if earlier than current created
        # Update modified if later than current modified
        pass
