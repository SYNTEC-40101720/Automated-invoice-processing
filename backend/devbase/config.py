"""Default, business-neutral configuration template."""

from __future__ import annotations

from copy import deepcopy
from configparser import ConfigParser
from typing import Mapping

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "app": {
        "name": "DevBase",
        "config_version": "1",
    }
}


def default_values() -> dict[str, dict[str, str]]:
    """Return a mutable copy of the default [app] template."""
    return deepcopy(DEFAULT_CONFIG)


def create_default_parser(
    values: Mapping[str, Mapping[str, str]] | None = None,
) -> ConfigParser:
    """Create a parser populated with business-neutral defaults."""
    parser = ConfigParser(interpolation=None)
    for section, options in (values or DEFAULT_CONFIG).items():
        parser[section] = dict(options)
    return parser


__all__ = ["DEFAULT_CONFIG", "create_default_parser", "default_values"]
