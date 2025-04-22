import hashlib

from django.utils import timezone


def get_unique_ref(uuid):
    year_prefix = str(timezone.now().year)[2:]  # "25" for 2025, "26" for 2026
    sha1_hash = hashlib.sha256(str(uuid).encode()).digest()
    numeric_hash = str(int.from_bytes(sha1_hash, "big"))[:10]  # First 10 digits
    return f"{year_prefix}-{numeric_hash}"
