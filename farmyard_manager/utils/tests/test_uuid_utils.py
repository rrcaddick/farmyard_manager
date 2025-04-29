import datetime
import hashlib
import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone

from farmyard_manager.utils.uuid_utils import get_unique_ref


@pytest.fixture(autouse=True)
def mock_timezone_now():
    # Mock `now()` to return a fixed year for consistency in testing
    fixed_datetime = datetime.datetime(2025, 1, 1, 0, 0, 0)  # noqa: DTZ001
    with patch(
        "django.utils.timezone.now",
        return_value=timezone.make_aware(fixed_datetime, datetime.UTC),
    ):
        yield fixed_datetime


class TestGetUniqueRef:
    def test_get_unique_ref(self, mock_timezone_now):
        test_uuid = uuid.uuid4()  # Generate a random UUID
        expected_year_prefix = str(mock_timezone_now.year)[2:]

        # Get the unique reference from the function
        unique_ref = get_unique_ref(test_uuid)

        # Generate the expected SHA-256 hash based on the uuid
        sha1_hash = hashlib.sha256(str(test_uuid).encode()).digest()
        numeric_hash = str(int.from_bytes(sha1_hash, "big"))[:10]
        expected_ref = f"{expected_year_prefix}-{numeric_hash}"

        # Assert the generated unique reference matches the expected format
        assert unique_ref == expected_ref

    def test_get_unique_ref_with_same_uuid(self):
        test_uuid = uuid.uuid4()  # Generate a random UUID

        # Call the function twice with the same uuid
        ref_1 = get_unique_ref(test_uuid)
        ref_2 = get_unique_ref(test_uuid)

        # Assert that both calls return the same unique reference
        assert ref_1 == ref_2

    def test_get_unique_ref_diff_uuid(self):
        uuid_1 = uuid.uuid4()
        uuid_2 = uuid.uuid4()

        # Call the function with two different UUIDs
        ref_1 = get_unique_ref(uuid_1)
        ref_2 = get_unique_ref(uuid_2)

        # Assert that the two references are different for different UUIDs
        assert ref_1 != ref_2

    def test_get_unique_ref_invalid_uuid(self):
        invalid_uuid = "invalid_uuid_string"

        with pytest.raises(TypeError, match="Invalid UUID"):
            get_unique_ref(invalid_uuid)
