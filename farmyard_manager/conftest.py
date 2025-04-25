import uuid
from contextlib import suppress

import pytest
from django.db import connection
from django.db import models

from farmyard_manager.users.models import User
from farmyard_manager.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    return UserFactory()


@pytest.fixture
def fake_model_factory():
    created_models = []

    def build_fake_model(base_name="FakeModel", fields=None, *, create_in_db=False):
        fields = fields or {}
        unique_suffix = uuid.uuid4().hex[:8]
        model_name = f"{base_name}_{unique_suffix}"

        class Meta:
            app_label = "testapp"
            managed = True

        model_fields = {
            "__module__": __name__,
            "Meta": Meta,
        }
        model_fields.update(fields)

        model_class = type(model_name, (models.Model,), model_fields)

        if create_in_db:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(model_class)

        created_models.append(model_class)
        return model_class, model_name  # return both class and name

    yield build_fake_model

    def safe_delete_model(model):
        with suppress(Exception), connection.schema_editor() as schema_editor:
            schema_editor.delete_model(model)

    for model in reversed(created_models):
        safe_delete_model(model)
