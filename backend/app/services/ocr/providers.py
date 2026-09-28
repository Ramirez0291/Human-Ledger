from __future__ import annotations

from app.core.config import settings
from app.services.ocr.base import ExtractorNotConfigured, ExtractResult


class NoneExtractor:
    name = "none"

    def is_available(self) -> tuple[bool, str]:
        return False, "ocr.reason.notSelected"

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:  # noqa: ARG002
        raise ExtractorNotConfigured(self.is_available()[1])


class LocalOcrExtractor:
    name = "local"

    def is_available(self) -> tuple[bool, str]:
        return False, "ocr.reason.localNotImplemented"

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:  # noqa: ARG002
        raise ExtractorNotConfigured(self.is_available()[1])


class LlmVisionExtractor:
    name = "cloud_llm"

    def is_available(self) -> tuple[bool, str]:
        if not settings.ocr_api_key:
            return False, "ocr.reason.cloudNoApiKey"
        return False, "ocr.reason.cloudNotImplemented"

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:  # noqa: ARG002
        raise ExtractorNotConfigured(self.is_available()[1])


_REGISTRY = {
    "none": NoneExtractor,
    "local": LocalOcrExtractor,
    "cloud_llm": LlmVisionExtractor,
}


def get_extractor(provider: str | None = None):
    key = (provider or settings.ocr_provider or "none").strip()
    return _REGISTRY.get(key, NoneExtractor)()


def provider_status() -> list[dict]:
    out = []
    for key, cls in _REGISTRY.items():
        available, reason_key = cls().is_available()
        out.append(
            {
                "key": key,
                "available": available,
                "reason_key": reason_key,
                "active": key == (settings.ocr_provider or "none"),
            }
        )
    return out
