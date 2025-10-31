from datetime import timedelta
from decimal import Decimal
from itertools import chain
from itertools import zip_longest

import factory
from django.utils import timezone

from farmyard_manager.core.tests.factories import SkipCleanBeforeSaveFactoryMixin
from farmyard_manager.entrance.models.pricing import Pricing
from farmyard_manager.entrance.models.ticket import TicketItem
from farmyard_manager.payments.enums import RefundVehicleAllocationStatusChoices
from farmyard_manager.payments.models import Payment
from farmyard_manager.payments.models import Refund
from farmyard_manager.payments.models import RefundTransactionItem
from farmyard_manager.payments.models import RefundVehicleAllocation
from farmyard_manager.payments.models import TransactionItem
from farmyard_manager.shifts.tests.factories import ShiftFactory
from farmyard_manager.users.tests.factories import UserFactory


class PaymentFactory(factory.django.DjangoModelFactory[Payment]):
    class Meta:
        model = Payment
        skip_postgeneration_save = True

    created_by = factory.SubFactory(UserFactory)
    status = Payment.PaymentStatusChoices.PENDING_SETTLEMENT
    completed_at = None

    class Params:
        pending_settlement = factory.Trait(
            status=Payment.PaymentStatusChoices.PENDING_SETTLEMENT,
        )
        partially_settled = factory.Trait(
            status=Payment.PaymentStatusChoices.PARTIALLY_SETTLED,
        )
        settled = factory.Trait(
            status=Payment.PaymentStatusChoices.SETTLED,
            completed_at=factory.LazyFunction(timezone.now),
        )
        partially_refunded = factory.Trait(
            status=Payment.PaymentStatusChoices.PARTIALLY_REFUNDED,
            completed_at=factory.LazyFunction(timezone.now),
        )
        refunded = factory.Trait(
            status=Payment.PaymentStatusChoices.REFUNDED,
            completed_at=factory.LazyFunction(timezone.now),
        )
        non_refundable = factory.Trait(
            status=Payment.PaymentStatusChoices.SETTLED,
            completed_at=factory.LazyFunction(
                lambda: timezone.now() - timedelta(hours=5),
            ),
        )

    @factory.post_generation
    def for_entrance_records(self, create, extracted, **kwargs):  # noqa: ARG002
        """
        Drives transaction item creations based on entrance records
        """
        if not create or not extracted:
            return

        if isinstance(extracted, bool):
            from farmyard_manager.entrance.tests.models.factories import TicketFactory

            TicketFactory(
                payment=self,
                processed=True,
                with_items=True,
            )

            return

        entrance_records = extracted if isinstance(extracted, list) else [extracted]

        # Link entrance records to this payment
        for record in entrance_records:
            record.payment = self
            record.save(update_fields=["payment"])

    @factory.post_generation
    def with_transactions(self, create, extracted, **kwargs):
        """
        Post generation hook to add transaction items.

        Usage:
            PaymentFactory()  # No transactions added
            PaymentFactory(with_transactions=False)  # No transactions added
            PaymentFactory(with_transactions=True)  # Adds default transactions based on
            payment status
            PaymentFactory(
                with_transactions=True,
                with_transactions__amount=100,
                with_transactions__visitor_count=3,
                with_transactions__payment_type="card"
            )  # Used to manipulate default values
            PaymentFactory(
                with_transactions=[
                    {"amount": 200, "visitor_count": 2, "payment_type": "card"},
                    {"amount": 100, "visitor_count": 1, "payment_type": "cash"}
                ]
            )  # Full Control
        """
        # Not saving or with_transactions=False passed or with_transactions not passed
        if not create or not extracted:
            return

        if (
            self.total_due_count == 1
            and self.status == Payment.PaymentStatusChoices.PARTIALLY_SETTLED
        ):
            error_message = "Cannot partially settle payment for only one visitor. "
            raise ValueError(
                error_message,
            )

        price_per_visitor = Pricing.objects.get_price(fallback=Decimal("100.00")).price
        default_visitor_count = kwargs.get(
            "visitor_count",
            1
            if self.status == Payment.PaymentStatusChoices.PARTIALLY_SETTLED
            else self.total_due_count,
        )
        default_payment_type = kwargs.get(
            "payment_type",
            TransactionItem.PaymentTypeChoices.CARD,
        )

        default_amount = kwargs.get(
            "amount",
            default_visitor_count * price_per_visitor,
        )

        default_transaction = {
            "visitor_count": default_visitor_count,
            "amount": default_amount,
            "payment_type": default_payment_type,
        }

        if default_payment_type == "cash":
            default_transaction["cash_tendered"] = kwargs.get(
                "cash_tendered",
                default_amount,
            )

        transaction_items = (
            extracted if isinstance(extracted, list) else [default_transaction]
        )

        # Create the transaction items
        for transaction in transaction_items:
            # Determine which factory trait to use based on payment type
            visitor_count = transaction.get("visitor_count")

            payment_type = transaction.get(
                "payment_type",
                TransactionItem.PaymentTypeChoices.CARD,
            )

            # Build factory kwargs
            factory_kwargs = {
                "payment": self,
                "visitor_count": visitor_count,
                "amount": transaction.get("amount", visitor_count * price_per_visitor),
                "cash_tendered": transaction.get("cash_tendered"),
                "as_card_transaction": payment_type == "card",
                "as_cash_transaction": payment_type == "cash",
            }

            TransactionItemFactory(**factory_kwargs)


class TransactionItemFactory(factory.django.DjangoModelFactory[TransactionItem]):
    class Meta:
        model = TransactionItem

    payment = factory.SubFactory(PaymentFactory)
    added_by = factory.SubFactory(UserFactory)
    shift = factory.SubFactory(ShiftFactory)

    class Params:
        ticket_item_count = None

        for_settled_payment = factory.Trait(
            payment=factory.SubFactory(
                PaymentFactory,
                settled=True,
                with_transactions=False,
                tickets=factory.RelatedFactoryList(
                    "farmyard_manager.entrance.tests.models.factories.TicketFactory",
                    "payment",
                    size=1,
                    processed=True,
                    with_items=True,
                    with_items__visitor_count=factory.SelfAttribute(
                        "....visitor_count",
                    ),
                ),
            ),
        )

        for_partially_settled_payment = factory.Trait(
            payment=factory.SubFactory(
                PaymentFactory,
                partially_settled=True,
                with_transactions=False,
                tickets=factory.RelatedFactoryList(
                    "farmyard_manager.entrance.tests.models.factories.TicketFactory",
                    "payment",
                    size=1,
                    processed=True,
                    with_payment=False,
                    with_items=True,
                    with_items__visitor_count=factory.SelfAttribute(
                        "....ticket_item_count",
                    ),
                ),
            ),
        )

        as_cash_transaction = factory.Trait(
            payment_type=TransactionItem.PaymentTypeChoices.CASH,
            cash_tendered=factory.LazyAttribute(
                lambda obj: obj.amount + Decimal("20.00"),
            ),
        )

        as_card_transaction = factory.Trait(
            payment_type=TransactionItem.PaymentTypeChoices.CARD,
            addpay_rrn="12345",
            addpay_transaction_id="67890",
            addpay_card_number="1234",
            addpay_cardholder_name="John Doe",
            addpay_response_data={},
        )


class RefundFactory(factory.django.DjangoModelFactory[Refund]):
    class Meta:
        model = Refund
        skip_postgeneration_save = True

    payment = factory.SubFactory(PaymentFactory)
    reason = factory.Faker("sentence")
    status = Refund.StatusChoices.PENDING_ALLOCATIONS
    requested_by = factory.SubFactory(UserFactory)

    class Params:
        pending_transactions = factory.Trait(
            status=Refund.StatusChoices.PENDING_TRANSACTIONS,
        )

        pending_settlement = factory.Trait(
            status=Refund.StatusChoices.PENDING_SETTLEMENT,
        )

        partially_settled = factory.Trait(
            status=Refund.StatusChoices.PARTIALLY_SETTLED,
        )

        settled = factory.Trait(
            status=Refund.StatusChoices.SETTLED,
            completed_at=factory.LazyFunction(timezone.now),
            completed_by=factory.SubFactory(UserFactory),
        )

        denied = factory.Trait(
            status=Refund.StatusChoices.DENIED,
            completed_at=factory.LazyFunction(timezone.now),
            completed_by=factory.SubFactory(UserFactory),
        )

    @factory.post_generation
    def for_payment(self, create, extracted, **kwargs):  # noqa: ARG002
        if not create or not extracted:
            return

        # True - create default payment
        if isinstance(extracted, bool):
            self.payment = PaymentFactory(
                settled=True,
                for_entrance_records=True,
                with_transactions=True,
            )
            self.save(update_fields=["payment"])
            return

        # Should this rather raise an error?
        if not isinstance(extracted, dict):
            error_message = "RefundFactory.for_payment must be a dict or True"
            raise TypeError(error_message)

        status = extracted.pop("status", Payment.PaymentStatusChoices.SETTLED)

        # Add the transient order index to each record for with_allocations
        entrance_records = extracted.get("for_entrance_records", [])
        for i, record in enumerate(entrance_records):
            record._order = i  # noqa: SLF001

        self.payment = PaymentFactory(status=status, **extracted)

    @factory.post_generation
    def with_allocations(self, create, extracted, **kwargs):  # noqa: ARG002
        if not create or not extracted:
            return

        if isinstance(extracted, bool):
            extracted = []

        # Combine all entrance records (tickets + re-entries)
        entrance_records = list(
            chain(self.payment.tickets.all(), self.payment.re_entries.all()),
        )

        # Sort by the transient order index you tagged earlier
        ordered_records = sorted(
            entrance_records,
            key=lambda r: getattr(r, "_order", 999),
        )

        if len(extracted) > len(ordered_records):
            error_message = "Can't have more allocations than entrance items"
            raise ValueError(error_message)

        for alloc_kwargs, record in zip_longest(extracted, ordered_records):
            entrance_item = record.public_item

            # Less allocations passed in that entrance items. Don't create defaults
            if alloc_kwargs is None and len(extracted) > 0:
                return

            if alloc_kwargs is None:
                alloc_kwargs = {  # noqa: PLW2901
                    "visitor_count": entrance_item.visitor_count,
                }

            alloc_kwargs.setdefault(
                "status",
                RefundVehicleAllocation.StatusChoices.COUNTED,
            )

            if isinstance(entrance_item, TicketItem):
                alloc_kwargs["ticket_item"] = entrance_item
            else:
                alloc_kwargs["re_entry_item"] = entrance_item

            RefundVehicleAllocationFactory(
                refund=self,
                **alloc_kwargs,
            )

    @factory.post_generation
    def with_refund_transactions(self, create, extracted, **kwargs):
        if not create or not extracted:
            return

        if isinstance(extracted, bool):
            extracted = []

        transaction_items = list(self.payment.transaction_items.all())

        for refund_tx_kwargs, transaction_item in zip_longest(
            extracted,
            transaction_items,
        ):
            # Less refund transactions passed in that transaction items.
            # Don't create defaults
            if refund_tx_kwargs is None and len(extracted) > 0:
                return

            # True passed, created defaults that cover transaction item
            if refund_tx_kwargs is None:
                refund_tx_kwargs = {  # noqa: PLW2901
                    "visitor_count": transaction_item.visitor_count,
                    "amount": transaction_item.amount,
                    **kwargs,
                }

            RefundTransactionItemFactory(
                refund=self,
                transaction_item=transaction_item,
                **refund_tx_kwargs,
            )


class RefundVehicleAllocationFactory(
    factory.django.DjangoModelFactory[RefundVehicleAllocation],
):
    """Factory for RefundVehicleAllocation model."""

    class Meta:
        model = RefundVehicleAllocation
        skip_postgeneration_save = True

    refund = factory.SubFactory(RefundFactory)
    processed_by = factory.SubFactory(UserFactory)
    status = RefundVehicleAllocationStatusChoices.PENDING_COUNT

    class Params:
        counted = factory.Trait(
            status=RefundVehicleAllocationStatusChoices.COUNTED,
        )
        settled = factory.Trait(
            status=RefundVehicleAllocationStatusChoices.SETTLED,
        )
        denied = factory.Trait(
            status=RefundVehicleAllocationStatusChoices.DENIED,
        )


class RefundTransactionItemFactory(
    SkipCleanBeforeSaveFactoryMixin,
    factory.django.DjangoModelFactory[RefundTransactionItem],
):
    """Factory for RefundTransactionItem model."""

    class Meta:
        model = RefundTransactionItem
        skip_postgeneration_save = True

    transaction_item = factory.SubFactory(
        TransactionItemFactory,
        visitor_count=factory.SelfAttribute("..visitor_count"),
        amount=factory.SelfAttribute("..amount"),
        as_cash_transaction=True,
        for_settled_payment=True,
        ticket_item_count=factory.SelfAttribute("..ticket_item_count"),
    )
    refund = factory.SubFactory(
        RefundFactory,
        payment=factory.SelfAttribute("..transaction_item.payment"),
        pending_transactions=True,
        with_allocations=True,
    )

    added_by = factory.SubFactory(UserFactory)
    status = RefundTransactionItem.StatusChoices.PENDING

    class Params:
        ticket_item_count = None
        processed = factory.Trait(
            status=RefundTransactionItem.StatusChoices.PROCESSED,
            processed_by=factory.SubFactory(UserFactory),
            processed_at=factory.LazyFunction(timezone.now),
        )
        denied = factory.Trait(
            status=RefundTransactionItem.StatusChoices.DENIED,
        )
