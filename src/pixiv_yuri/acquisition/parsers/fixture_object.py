"""Generic object parser used only for offline contract regression."""

from __future__ import annotations

from pixiv_yuri.acquisition.models import EntityType, RawResponse
from pixiv_yuri.acquisition.parsers.base import ParsedEnvelope, ParserError, PayloadParser
from pixiv_yuri.schema_probe.analyzer import fingerprint_payload


class FixtureObjectParser(PayloadParser):
    """Prove parser selection without asserting production Pixiv fields."""

    @property
    def parser_id(self) -> str:
        return "fixture_object"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def supported_entity_types(self) -> frozenset[EntityType]:
        return frozenset(EntityType)

    def parse(self, response: RawResponse) -> ParsedEnvelope:
        payload = response.json_value()
        if not isinstance(payload, dict):
            raise ParserError("The offline fixture parser accepts JSON objects only.")
        return ParsedEnvelope(
            parser_id=self.parser_id,
            parser_version=self.version,
            entity_type=response.entity_type,
            source_id=response.source_id,
            observed_at=response.observed_at,
            schema_fingerprint=fingerprint_payload(payload),
            document=payload,
        )
