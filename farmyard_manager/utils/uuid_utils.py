import hashlib
from uuid import UUID

from django.utils import timezone


def get_unique_ref(uuid):
    # Ensure the input is a valid UUID
    if not isinstance(uuid, UUID):
        error_message = "Invalid UUID"
        raise TypeError(error_message)

    # Proceed with the original logic
    year_prefix = str(timezone.now().year)[2:]  # "25" for 2025, "26" for 2026
    sha1_hash = hashlib.sha256(str(uuid).encode()).digest()
    numeric_hash = str(int.from_bytes(sha1_hash, "big"))[:10]  # First 10 digits
    return f"{year_prefix}-{numeric_hash}"
