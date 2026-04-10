"""Constants for the refactored DVS Portal provider."""

DEFAULT_API_URI = "/DVSWebAPI/api"
API_TIMEZONE = "Europe/Amsterdam"

LOGIN_ENDPOINT = "/login"
LOGIN_INFO_ENDPOINT = "/login/info"
LOGIN_GETBASE_ENDPOINT = "/login/getbase"
FLOW_INFO_ENDPOINT = "/resource/getflowinfo"
RESERVATION_CREATE_ENDPOINT = "/reservation/create"
RESERVATION_UPDATE_ENDPOINT = "/reservation/update"
RESERVATION_END_ENDPOINT = "/reservation/end"
FAVORITE_UPSERT_ENDPOINT = "/permitmedialicenseplate/upsert"
FAVORITE_REMOVE_ENDPOINT = "/permitmedialicenseplate/remove"
PERMIT_LICENSE_PLATE_UPSERT_ENDPOINT = "/permitlicenseplate/upsert"
PERMIT_LICENSE_PLATE_REMOVE_ENDPOINT = "/permitlicenseplate/remove"

LOGIN_METHOD_PAS = 2

AUTH_HEADER = "Authorization"
AUTH_PREFIX = "Token "
XSRF_HEADER = "X-XSRF-TOKEN"
DEFAULT_XSRF_COOKIE_NAMES = ("XSRF-TOKEN",)
RETRY_AFTER_HEADER = "Retry-After"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-dvsportal-new",
}
