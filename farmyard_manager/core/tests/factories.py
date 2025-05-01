import uuid
from contextlib import suppress

from django.db import connection
from django.db import models


class FakeModelFactory:
    """
    Factory class to dynamically create Django model classes with specified fields.

    This factory allows for the creation of fake model classes that can be used
    for testing purposes.

    It supports specifying fields, decorators, and optional database creation.
    """

    def __init__(self):
        """
        Initializes the FakeModelFactory, setting up an empty list of created models.
        """
        self.created_models = []

    def build_model(
        self,
        base_name="FakeModel",
        fields=None,
        *,
        create_in_db=False,
        base_class=models.Model,
        class_decorators=None,
    ):
        """
        Builds a fake model class with the specified fields, base class, and decorators.

        Args:
            base_name (str): The base name for the model class.
            fields (dict): A dictionary of field names and their definitions.
            create_in_db (bool): Whether to create the model in the database.
            base_class (models.Model): The base class for the model.
            class_decorators (list): List of decorators to apply to the model class.

        Returns:
            tuple: The created model class and its name.
        """
        fields = fields or {}
        class_decorators = class_decorators or []
        model_name = f"{base_name}_{uuid.uuid4().hex[:8]}"

        model_fields = self._build_fields(fields)
        model_fields["Meta"] = self._create_meta_class()

        model_class = type(model_name, (base_class,), model_fields)

        for decorator in class_decorators:
            model_class = decorator(model_class)

        if create_in_db:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(model_class)

        self.created_models.append(model_class)
        return model_class, model_name

    def cleanup(self):
        """
        Cleans up all created models by deleting them from the database.
        """
        for model in reversed(self.created_models):
            with suppress(Exception), connection.schema_editor() as schema_editor:
                schema_editor.delete_model(model)

    def _build_fields(self, fields):
        """
        Builds the fields for the model based on the provided field definitions.

        Args:
            fields (dict): A dictionary of field names and their definitions.

        Returns:
            dict: A dictionary of the model fields.
        """
        model_fields = {"__module__": __name__}
        for field_name, field_def in fields.items():
            if isinstance(field_def, dict) and "expected_type" in field_def:
                model_fields[field_name] = self._create_field_function(
                    field_name,
                    field_def["expected_type"],
                    field_def.get("decorators", []),
                )
            elif field_def is not None:
                model_fields[field_name] = field_def
        return model_fields

    def _create_field_function(self, field_name, expected_type, decorators):
        """
        Creates a field function for the model, marking it as required.

        Args:
            field_name (str): The name of the field.
            expected_type (type): The expected type for the field.
            decorators (list): List of decorators to apply to the field function.

        Returns:
            function: The field function for the model.
        """
        error_message = f"{field_name} must be implemented by subclass."

        def _field_function(cls):
            raise NotImplementedError(error_message)

        _field_function.__module__ = __name__
        _field_function.__annotations__ = {"return": expected_type}

        for decorator in reversed(decorators):
            _field_function = decorator(_field_function)

        return _field_function

    def _create_meta_class(self):
        """
        Creates a Meta class for the model with default app label and managed options.

        Returns:
            class: The Meta class.
        """

        class Meta:
            app_label = "testapp"
            managed = True

        return Meta
