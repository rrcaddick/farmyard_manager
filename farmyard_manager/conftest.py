import pytest

from farmyard_manager.core.tests.factories import FakeModelFactory
from farmyard_manager.users.models import User
from farmyard_manager.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:  # noqa: ARG001
    return UserFactory()


@pytest.fixture
def fake_model_factory():
    """
    Fixture to provide a factory for creating fake models in tests.

    Returns:
        function: A function that builds a fake model.
    """
    factory = FakeModelFactory()
    yield factory.build_model
    factory.cleanup()
