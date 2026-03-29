"""Constants for the 2park provider."""

DEFAULT_API_URI = "/gsmpark-app-www/json"
API_TIMEZONE = "Europe/Amsterdam"

AUTH_ENDPOINT = "/check_credentials.json"
CATEGORIES_ENDPOINT = "/get_categories.json"
PRODUCT_DETAILS_ENDPOINT = "/get_category_product_details.json"
BALANCE_ENDPOINT = "/get_balance.json"
START_ACTION_ENDPOINT = "/start_action.json"
EXTEND_ACTION_ENDPOINT = "/extend_action.json"
STOP_ACTION_ENDPOINT = "/stop_action.json"
HANDLE_FAVORITE_ENDPOINT = "/handle_favorite.json"

LOCALE = "nl_NL"
TIME_FORMAT = "%d-%m-%Y %H:%M:%S"

BALANCE_AMOUNT_LABEL = "AMOUNT"
PARAM_MBR_IDENT = "MBR_IDENT"
PARAM_TIMESTART = "TIMESTART"
PARAM_TIMEEND = "TIMEEND"
PARAM_VALID_UNTIL = "VALID_UNTIL"
PARAM_LOCATION = "LOCATION"
PARAM_NICKNAME = "NICKNAME"

MEMBER_TYPE_LPN = "LPN"

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pycityvisitorparking-2park",
}
