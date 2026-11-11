"""Helpers for the Mendix runtime protocol used by the Rotterdam portal."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ...exceptions import ProviderError, ValidationError

_NANOFLOWS_RE = re.compile(r"<m:nanoflows>(.*?)</m:nanoflows>", re.DOTALL)
_GUID_RE = re.compile(r"\d{1,20}")
_OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")


@dataclass(frozen=True, slots=True)
class MendixObject:
    """A retrieved Mendix object with its raw attribute payloads."""

    guid: str
    entity: str
    attributes: Mapping[str, Any]

    def value(self, name: str) -> Any:
        """Return the raw value of an attribute or association, or ``None``."""
        attribute = self.attributes.get(name)
        if isinstance(attribute, Mapping):
            return attribute.get("value")
        return None

    def text(self, name: str) -> str | None:
        """Return a non-empty string attribute value, or ``None``."""
        raw = self.value(name)
        if raw is None or isinstance(raw, bool):
            return None
        text = str(raw).strip()
        return text or None


def parse_objects(response: Any) -> list[MendixObject]:
    """Return the objects contained in a Mendix runtime response."""
    if not isinstance(response, Mapping):
        raise ProviderError("Provider response was not an object.")
    raw_objects = response.get("objects")
    if raw_objects is None:
        return []
    if not isinstance(raw_objects, list):
        raise ProviderError("Provider response included invalid objects.")
    objects: list[MendixObject] = []
    for raw in raw_objects:
        if not isinstance(raw, Mapping):
            raise ProviderError("Provider response included invalid objects.")
        guid = raw.get("guid")
        entity = raw.get("objectType")
        attributes = raw.get("attributes")
        if not isinstance(guid, str) or not isinstance(entity, str):
            raise ProviderError("Provider response included invalid objects.")
        objects.append(
            MendixObject(
                guid=guid,
                entity=entity,
                attributes=attributes if isinstance(attributes, Mapping) else {},
            )
        )
    return objects


def xpath_guid(value: str | None, field: str) -> str:
    """Return a provider object id that is safe to embed in an XPath constraint."""
    if value is None or not _GUID_RE.fullmatch(value):
        raise ProviderError(f"Provider response included an invalid {field}.")
    return value


def xpath_opaque_id(value: str, field: str) -> str:
    """Validate a caller-supplied identifier before it is embedded in an XPath constraint.

    Identifiers are opaque, but they end up inside a quoted XPath literal, so quotes,
    backslashes, and whitespace are rejected instead of escaped.
    """
    if not _OPAQUE_ID_RE.fullmatch(value):
        raise ValidationError(f"{field} contains unsupported characters.")
    return value


def parse_integer(value: Any) -> int:
    """Parse a Mendix integer (delivered as a number or a numeric string)."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


def datetime_from_milliseconds(value: Any) -> datetime | None:
    """Convert a Mendix datetime (epoch milliseconds) to an aware UTC datetime."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(int(str(value).strip()) / 1000, tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise ProviderError("Provider returned an invalid timestamp.") from exc


def milliseconds_from_datetime(value: datetime) -> int:
    """Convert an aware datetime to Mendix epoch milliseconds."""
    return int(value.timestamp() * 1000)


def _walk(node: Any) -> Iterator[Mapping[str, Any]]:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def find_operation_id(page_xml: str, nanoflow: str, parameters: frozenset[str]) -> str | None:
    """Return the operation id of the microflow a nanoflow calls with the given parameters.

    Page definitions embed the nanoflows they use as HTML-escaped JSON. The id is only
    returned when exactly one matching microflow call exists, so an ambiguous page
    never resolves to a guess.
    """
    match = _NANOFLOWS_RE.search(page_xml)
    if match is None:
        return None
    try:
        definitions = json.loads(html.unescape(match.group(1)))
    except ValueError:
        return None
    if not isinstance(definitions, Mapping):
        return None
    found: set[str] = set()
    for node in _walk(definitions.get(nanoflow)):
        if node.get("type") != "microflowCall":
            continue
        raw_parameters = node.get("parameters")
        names = frozenset(
            item.get("name")
            for item in (raw_parameters if isinstance(raw_parameters, list) else [])
            if isinstance(item, Mapping)
        )
        operation_id = node.get("operationId")
        if names == parameters and isinstance(operation_id, str) and operation_id:
            found.add(operation_id)
    return next(iter(found)) if len(found) == 1 else None
