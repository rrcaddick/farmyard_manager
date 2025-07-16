# ruff: noqa: N806
import uuid
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from farmyard_manager.core.models import BaseModelMixin
from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import TransitionTextChoices
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin


class TestBaseModelMixin:
    def test_is_new_with_new_instance(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(base_class=BaseModelMixin)
        instance = FakeModel()
        assert instance.is_new() is True

    @pytest.mark.django_db(transaction=True)
    def test_is_new_with_saved_instance(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(base_class=BaseModelMixin, create_in_db=True)
        instance = FakeModel.objects.create()
        assert instance.is_new() is False


class TestUUIDModelMixin:
    @pytest.mark.django_db(transaction=True)
    def test_uuid_field_on_create(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=UUIDModelMixin,
            create_in_db=True,
        )
        instance = FakeModel.objects.create()
        assert instance.uuid is not None
        assert isinstance(instance.uuid, uuid.UUID)


@pytest.mark.django_db(transaction=True)
class TestUUIDRefNumberModelMixin:
    def test_ref_number_generation(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=UUIDRefNumberModelMixin,
            create_in_db=True,
        )
        instance = FakeModel.objects.create()
        assert instance.ref_number is not None

        # Ensure it's a unique ref_number
        instance_2 = FakeModel.objects.create()
        assert instance.ref_number != instance_2.ref_number

    def test_retry_ref_number_conflict_save(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=UUIDRefNumberModelMixin,
            create_in_db=True,
        )

        instance = FakeModel.objects.create()
        ref_number = instance.ref_number

        instance_2 = FakeModel.objects.create(ref_number=ref_number)

        assert instance_2.ref_number != ref_number

    def test_integrity_error_handling(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=UUIDRefNumberModelMixin,
            create_in_db=True,
        )

        instance = FakeModel.objects.create()
        ref_number = instance.ref_number

        instance_2 = FakeModel()
        with pytest.raises(
            IntegrityError,
            match="Failed to generate a unique ref number after 0 retries.",
        ):
            instance_2.save(ref_number=ref_number, retries=0)


@pytest.mark.django_db(transaction=True)
class TestCleanBeforeSaveModel:
    def test_save_calls_full_clean(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=CleanBeforeSaveModel,
            create_in_db=True,
        )

        instance = FakeModel()

        instance.full_clean = MagicMock()
        instance.save()
        instance.full_clean.assert_called_once()

    def test_save_bypass_clean(self, fake_model_factory):
        FakeModel, _ = fake_model_factory(
            base_class=CleanBeforeSaveModel,
            create_in_db=True,
        )

        instance = FakeModel()

        instance.full_clean = MagicMock()
        instance.save(clean=False)
        instance.full_clean.assert_not_called()


class TestTransitionTextChoices:
    class TextChoices(TransitionTextChoices):
        CHOICE_1 = ("choice_1", "Choice 1")
        CHOICE_2 = ("choice_2", "Choice 2")
        CHOICE_3 = ("choice_3", "Choice 3")

        @classmethod
        def get_transition_map(cls):
            return {
                cls.CHOICE_1: [cls.CHOICE_2],
                cls.CHOICE_2: [cls.CHOICE_3],
                cls.CHOICE_3: [],
            }

    def test_get_transition_map(self):
        transition_map = self.TextChoices.get_transition_map()
        assert isinstance(transition_map, dict)
        assert transition_map == {
            self.TextChoices.CHOICE_1: [self.TextChoices.CHOICE_2],
            self.TextChoices.CHOICE_2: [self.TextChoices.CHOICE_3],
            self.TextChoices.CHOICE_3: [],
        }

    def test_validate_choice_transition_valid(self):
        # Valid transition
        prev_choice = self.TextChoices.CHOICE_1
        new_choice = self.TextChoices.CHOICE_2
        result = self.TextChoices.validate_choice_transition(prev_choice, new_choice)
        assert result is True

    def test_validate_choice_transition_invalid(self):
        # Invalid transition
        prev_choice = self.TextChoices.CHOICE_1
        new_choice = self.TextChoices.CHOICE_3

        with pytest.raises(ValidationError):
            self.TextChoices.validate_choice_transition(prev_choice, new_choice)
