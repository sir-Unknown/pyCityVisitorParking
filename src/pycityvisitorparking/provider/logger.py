"""Shared logging helpers for provider modules."""

from __future__ import annotations

import logging

_PROVIDER_LOGGER_NAME = "pycityvisitorparking.provider"


def get_provider_logger(module_name: str | None = None) -> logging.Logger:
    """Return a provider logger using a consistent logger hierarchy."""
    if not module_name:
        return logging.getLogger(_PROVIDER_LOGGER_NAME)
    if module_name == _PROVIDER_LOGGER_NAME:
        return logging.getLogger(module_name)
    if module_name.startswith(f"{_PROVIDER_LOGGER_NAME}."):
        return logging.getLogger(module_name)
    return logging.getLogger(f"{_PROVIDER_LOGGER_NAME}.{module_name}")
