"""Constants for the DVS Portal provider."""

DEFAULT_API_URI = "/DVSWebAPI/api"
API_TIMEZONE = "Europe/Amsterdam"

LOGIN_ENDPOINT = "/login"
LOGIN_GETBASE_ENDPOINT = "/login/getbase"
RESERVATION_CREATE_ENDPOINT = "/reservation/create"
RESERVATION_UPDATE_ENDPOINT = "/reservation/update"
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
