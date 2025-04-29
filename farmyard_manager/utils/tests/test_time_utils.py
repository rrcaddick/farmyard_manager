import calendar
import datetime
from unittest.mock import patch

from django.utils import timezone

from farmyard_manager.utils.time_utils import get_unix_timestamp


class TestGetUnixTimestamp:
    @patch("django.utils.timezone.now")
    def test_get_unix_timestamp(self, mock_now):
        mock_now.return_value = timezone.make_aware(
            datetime.datetime(2023, 1, 1, 12, 0, 0),  # noqa: DTZ001
            datetime.UTC,
        )

        expected_timestamp = calendar.timegm(
            datetime.datetime(2023, 1, 1, 12, 0, 0).utctimetuple(),  # noqa: DTZ001
        )

        timestamp = get_unix_timestamp()

        assert timestamp == expected_timestamp
