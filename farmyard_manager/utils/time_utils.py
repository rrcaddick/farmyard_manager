import calendar

from django.utils import timezone


def get_unix_timestamp():
    return calendar.timegm(timezone.now().utctimetuple())
