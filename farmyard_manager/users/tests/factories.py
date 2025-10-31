import factory

from farmyard_manager.users.models import User


class UserFactory(factory.django.DjangoModelFactory[User]):
    """Factory for User model."""

    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Faker("user_name")
    name = factory.Faker("name")
    password = factory.PostGenerationMethodCall("set_password", "password")
    is_active = True
    is_staff = False

    class Params:
        as_manager = factory.Trait(
            is_staff=True,
            # Since is_manager is a placeholder property, we can add groups or
            # permissions if needed
        )
        with_active_shift = factory.Trait(
            shifts=factory.RelatedFactoryList(
                "farmyard_manager.shifts.tests.factories.ShiftFactory",
                size=1,
            ),
        )

    @factory.post_generation
    def with_active_shift(self, create, extracted, **kwargs):  # noqa: ARG002
        """Assign an active shift to the user."""
        if not create or not extracted:
            return

        if isinstance(extracted, bool) and extracted:
            from farmyard_manager.shifts.tests.factories import ShiftFactory

            ShiftFactory(user=self)
