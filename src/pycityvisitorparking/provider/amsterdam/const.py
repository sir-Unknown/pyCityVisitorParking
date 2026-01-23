"""Constants for Amsterdam provider."""

DEFAULT_API_URI = "/api"

LOGIN_ENDPOINT = "/ssp/login_check"
CLIENT_PRODUCT_ENDPOINT = "/v1/client_product/{client_product_id}"
PERMIT_LIST_ENDPOINT = "/v1/permit/list"
PERMIT_LIST_FOR_CLIENT_ENDPOINT = "/v1/permit/list_for_client"
PERMIT_OVERVIEW_PRODUCT_LIST_ENDPOINT = "/v1/permit_overview/product_list"

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
