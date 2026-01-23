"""Constants for Amsterdam provider."""

DEFAULT_API_URI: str = "/api"

LOGIN_ENDPOINT: str = "/ssp/login_check"
CLIENT_PRODUCT_ENDPOINT: str = "/v1/client_product/{client_product_id}"
PERMIT_LIST_ENDPOINT: str = "/v1/permit/list"
PERMIT_LIST_FOR_CLIENT_ENDPOINT: str = "/v1/permit/list_for_client"
PERMIT_OVERVIEW_PRODUCT_LIST_ENDPOINT: str = "/v1/permit_overview/product_list"

PARKING_SESSION_LIST_ENDPOINT: str = "/v1/ssp/parking_session/list"
PARKING_SESSION_START_ENDPOINT: str = "/v1/ssp/parking_session/start"
PARKING_SESSION_COST_CALCULATOR_ENDPOINT: str = "/v1/ssp/parking_session/cost_calculator"
PARKING_SESSION_EDIT_ENDPOINT: str = "/v1/ssp/parking_session/{reservation_id}/edit"

FAVORITE_LIST_ENDPOINT: str = "/v1/ssp/favorite_vrn/list"
FAVORITE_ADD_ENDPOINT: str = "/v1/ssp/favorite_vrn/add"
FAVORITE_DELETE_ENDPOINT: str = "/v1/ssp/favorite_vrn/{favorite_id}/delete"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-amsterdam",
}

__all__ = [
    "CLIENT_PRODUCT_ENDPOINT",
    "DEFAULT_API_URI",
    "DEFAULT_HEADERS",
    "FAVORITE_ADD_ENDPOINT",
    "FAVORITE_DELETE_ENDPOINT",
    "FAVORITE_LIST_ENDPOINT",
    "LOGIN_ENDPOINT",
    "PARKING_SESSION_COST_CALCULATOR_ENDPOINT",
    "PARKING_SESSION_EDIT_ENDPOINT",
    "PARKING_SESSION_LIST_ENDPOINT",
    "PARKING_SESSION_START_ENDPOINT",
    "PERMIT_LIST_ENDPOINT",
    "PERMIT_LIST_FOR_CLIENT_ENDPOINT",
    "PERMIT_OVERVIEW_PRODUCT_LIST_ENDPOINT",
]
