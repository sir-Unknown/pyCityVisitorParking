"""Constants for the DVS Portal provider."""

LOGIN_ENDPOINT = "/login"
LOGIN_GETBASE_ENDPOINT = "/login/getbase"
RESERVATION_CREATE_ENDPOINT = "/reservation/create"
RESERVATION_END_ENDPOINT = "/reservation/end"
FAVORITE_UPSERT_ENDPOINT = "/permitmedialicenseplate/upsert"
FAVORITE_REMOVE_ENDPOINT = "/permitmedialicenseplate/remove"

LOGIN_METHOD_PAS = "Pas"

AUTH_HEADER = "Authorization"
AUTH_PREFIX = "Token "
RETRY_AFTER_HEADER = "Retry-After"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-dvsportal",
}
