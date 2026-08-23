"""Exact-version parser registry used by the schema policy gate."""

from __future__ import annotations

from collections.abc import Iterable

from pixiv_yuri.acquisition.models import EntityType
from pixiv_yuri.acquisition.parsers.base import PayloadParser
from pixiv_yuri.acquisition.parsers.fixture_object import FixtureObjectParser


class ParserRegistryError(LookupError):
    """Raised when parser routing is missing, ambiguous, or incompatible."""


class ParserRegistry:
    """Resolve parsers by stable identifier and exact version."""

    def __init__(self, parsers: Iterable[PayloadParser] = ()) -> None:
        self._parsers: dict[tuple[str, str], PayloadParser] = {}
        for parser in parsers:
            key = (parser.parser_id, parser.version)
            if key in self._parsers:
                raise ParserRegistryError(
                    f"Duplicate parser registration: {parser.parser_id}@{parser.version}"
                )
            self._parsers[key] = parser

    def resolve(
        self,
        parser_id: str,
        parser_version: str,
        entity_type: EntityType,
    ) -> PayloadParser:
        """Return an exact compatible parser or fail closed."""
        parser = self._parsers.get((parser_id, parser_version))
        if parser is None:
            raise ParserRegistryError(f"Parser is unavailable: {parser_id}@{parser_version}")
        if entity_type not in parser.supported_entity_types:
            raise ParserRegistryError(
                f"Parser {parser_id}@{parser_version} does not support {entity_type.value}."
            )
        return parser


def build_offline_fixture_registry() -> ParserRegistry:
    """Build the only parser set allowed before production schema approval."""
    return ParserRegistry((FixtureObjectParser(),))
