import pytest

from .factory import FakeModelFactory


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
