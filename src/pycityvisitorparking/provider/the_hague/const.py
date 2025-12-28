"""Constants for The Hague provider."""

SESSION_ENDPOINT = "/session/0"
ACCOUNT_ENDPOINT = "/account/0"
RESERVATION_ENDPOINT = "/reservation"
FAVORITE_ENDPOINT = "/favorite"

REQUESTED_WITH_HEADER = "x-requested-with"
PERMIT_MEDIA_TYPE_HEADER = "x-permit-media-type-id"

DEFAULT_REQUESTED_WITH = "angular"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-the-hague",
    REQUESTED_WITH_HEADER: DEFAULT_REQUESTED_WITH,
}
