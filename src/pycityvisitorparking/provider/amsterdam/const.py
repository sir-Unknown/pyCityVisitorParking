"""Constants for Amsterdam provider."""

DEFAULT_API_URI = "/api"

LOGIN_ENDPOINT = "/ssp/login_check"
CLIENT_PRODUCT_ENDPOINT = "/v1/client_product/{client_product_id}"
PAID_PARKING_ZONE_BY_MACHINE_ENDPOINT = "/v1/ssp/paid_parking_zone/get_by_machine_number"
PAID_PARKING_ZONE_LIST_ENDPOINT = (
    "/v1/ssp/paid_parking_zone/list/client_product/{client_product_id}"
)

PARKING_SESSION_LIST_ENDPOINT = "/v1/ssp/parking_session/list"
PARKING_SESSION_START_ENDPOINT = "/v1/ssp/parking_session/start"
PARKING_SESSION_EDIT_ENDPOINT = "/v1/ssp/parking_session/{reservation_id}/edit"

FAVORITE_LIST_ENDPOINT = "/v1/ssp/favorite_vrn/list"
FAVORITE_ADD_ENDPOINT = "/v1/ssp/favorite_vrn/add"
FAVORITE_DELETE_ENDPOINT = "/v1/ssp/favorite_vrn/{favorite_id}/delete"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-amsterdam",
}
