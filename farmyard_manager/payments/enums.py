from farmyard_manager.core.models import TransitionTextChoices


class RefundVehicleAllocationStatusChoices(TransitionTextChoices):
    PENDING_COUNT = ("pending_count", "Pending Count")
    COUNTED = ("counted", "Counted")
    SETTLED = ("settled", "Settled")
    DENIED = ("denied", "Denied")

    @classmethod
    def get_transition_map(cls) -> dict:
        return {
            cls.PENDING_COUNT: [cls.COUNTED],
            cls.COUNTED: [cls.SETTLED, cls.DENIED],
            cls.SETTLED: [],
            cls.DENIED: [],
        }
