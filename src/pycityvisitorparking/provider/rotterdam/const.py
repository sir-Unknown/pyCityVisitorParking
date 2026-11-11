"""Constants for the Rotterdam provider.

The Rotterdam visitor parking portal is a Mendix application. All data access goes
through the Mendix runtime endpoint (``/xas/``). Entity and attribute names below come
from the application's published metamodel; the Dutch names are provider-native and
must stay inside this provider.
"""

from __future__ import annotations

from typing import Final, NamedTuple

XAS_ENDPOINT: Final = "/xas/"
# Page definitions are served per locale. Their structure is locale independent.
PAGE_ENDPOINT: Final = "/pages/nl_NL"
CSRF_HEADER: Final = "X-Csrf-Token"

DEFAULT_HEADERS: Final = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "pycityvisitorparking-rotterdam",
}

SESSION_PARAMS: Final = {
    "timezoneoffset": 0,
    "referrer": "/login.html",
    "profile": "Responsive",
    "hybrid": False,
}

# Channel identifier the web application reports for parking actions.
CHANNEL: Final = "WEB_APP"

# Timezone in which the portal books monthly business-hours balances.
LOCAL_TIMEZONE: Final = "Europe/Amsterdam"

# Application constant: minutes represented by one balance unit.
CONSTANT_MINUTES_PER_UNIT: Final = "Parkeren.MinutenPerEenheid"

# Enumeration values.
PERMIT_STATUS_ACTIVE: Final = "Actief"
PERMIT_TYPE_BUSINESS_HOURS: Final = "Bedrijfsurenvergunning"
ZONE_TYPE_ZONE: Final = "Zone"
LANDCODE_NL: Final = "NL"
LANDCODE_EU: Final = "EU"

# Foreign plates may use up to 10 characters; Dutch plates use exactly 6.
NL_PLATE_LENGTH: Final = 6
EU_PLATE_MAX_LENGTH: Final = 10

# Entities.
ENTITY_PERMIT_AUTHORIZATION: Final = "Parkeren.Machtiging"
ENTITY_PERMIT: Final = "Parkeren.Vergunning"
ENTITY_BALANCE: Final = "Parkeren.Saldo"
ENTITY_PARKING_ACTION: Final = "Parkeren.Parkeeractie"
ENTITY_PARKING_ACTION_HELPER: Final = "Parkeren.ParkeeractieHelper"
ENTITY_PLATE: Final = "Parkeren.Kenteken"
ENTITY_PLATE_HELPER: Final = "Parkeren.KentekenHelper"
ENTITY_API_RESULT: Final = "General.APIResultaat"
ENTITY_ZONE_RELATION: Final = "Masterdata.ZoneVergunningRelatie"
ENTITY_ZONE: Final = "Masterdata.Zone"
ENTITY_PARKING_TIME: Final = "Masterdata.Parkeertijd"

# Associations (used in XPath constraints and as attribute keys of retrieved objects).
ASSOC_AUTHORIZATION_ACCOUNT: Final = "Parkeren.Machtiging_Account"
ASSOC_AUTHORIZATION_PERMIT: Final = "Parkeren.Machtiging_Vergunning"
ASSOC_BALANCE_PERMIT: Final = "Parkeren.Saldo_Vergunning"
ASSOC_BALANCE_AUTHORIZATION: Final = "Parkeren.SaldoZakelijk_Machtiging"
ASSOC_ACTION_PERMIT: Final = "Parkeren.Parkeeractie_Vergunning"
ASSOC_PLATE_ACCOUNT: Final = "Parkeren.Kenteken_Account"
ASSOC_ZONE_RELATION_PERMIT: Final = "Masterdata.ZoneVergunningRelatie_Vergunning"
ASSOC_ZONE_RELATION_ZONE: Final = "Masterdata.ZoneVergunningRelatie_Zone"
ASSOC_PARKING_TIME_ZONE: Final = "Masterdata.Parkeertijd_Zone"


class OperationSpec(NamedTuple):
    """Locator for a Mendix microflow call inside a published page definition.

    Microflows are addressed by opaque operation ids that are only published inside
    the page definitions, so they are resolved at runtime from the nanoflow that calls
    the microflow (identified by name and parameter names) instead of being hardcoded.
    """

    page: str
    nanoflow: str
    parameters: frozenset[str]


_ACTION_PAGE: Final = "ParkerenWeb/ParkeeractieAanmakenBewerken.page.xml"
_PLATE_PAGE: Final = "ParkerenWeb/KentekenToevoegenBewerken.page.xml"
_ACTION_PARAMETERS: Final = frozenset(
    {"ParkeeractieHelper", "Kanaal", "APIResultaat", "MachtigingId"}
)

OPERATION_PLATE_SAVE: Final = "plate_save"
OPERATION_PLATE_DELETE: Final = "plate_delete"
OPERATION_ACTION_SAVE: Final = "action_save"
OPERATION_ACTION_CANCEL: Final = "action_cancel"
OPERATION_ACTION_COST: Final = "action_cost"

OPERATIONS: Final = {
    OPERATION_PLATE_SAVE: OperationSpec(
        _PLATE_PAGE, "Parkeren.KentekenOpslaan", frozenset({"KentekenHelper"})
    ),
    OPERATION_PLATE_DELETE: OperationSpec(
        _PLATE_PAGE, "Parkeren.KentekenVerwijderen", frozenset({"KentekenHelper"})
    ),
    OPERATION_ACTION_SAVE: OperationSpec(
        _ACTION_PAGE, "Parkeren.ParkeeractieStarten", _ACTION_PARAMETERS
    ),
    OPERATION_ACTION_CANCEL: OperationSpec(
        _ACTION_PAGE, "Parkeren.ParkeeractieGeplandAnnuleren", _ACTION_PARAMETERS
    ),
    OPERATION_ACTION_COST: OperationSpec(
        _ACTION_PAGE,
        "Parkeren.ParkeerkostenBerekening",
        frozenset({"ParkeeractieHelper", "MachtigingId"}),
    ),
}
