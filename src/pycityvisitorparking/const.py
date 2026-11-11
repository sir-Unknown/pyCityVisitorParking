"""Package-level constants for pyCityVisitorParking."""

from __future__ import annotations

from typing import Final

# Keys used in resolved_login_params — match the login() kwargs of the same name
# so callers can pass them back directly on subsequent starts.
RESOLVED_LOCATION: Final = "location"
RESOLVED_PERMIT_ID: Final = "permit_id"
RESOLVED_PERMIT_MEDIA_TYPE_ID: Final = "permit_media_type_id"
