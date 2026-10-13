"""Provider 实现占位。

M0 阶段三个 Provider 均不做实际识别：
- NoneExtractor：默认，明确告知未配置
- LocalOcrExtractor：预留本地 OCR 引擎（M2 接入）
- LlmVisionExtractor：预留云端多模态模型（M2 接入，需 API Key）

它们已实现 is_available()，因此设置页现在就能如实显示每种方案的配置状态，
而不必等到 M2。

注意：is_available() 返回的是 **i18n 词条 key**，不是已翻译的文案。
后端不做文案翻译（需求书 F10），否则界面切到日语/英语时这里会漏译。
"""

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
    """本地 OCR。M2 接入，届时在此实现：

    OCR 引擎取文本行与坐标 → 机构版式识别 → 对应版式解析器 → RawTransaction。
    需实现附录 A 的强制规则：交易状态过滤、汇总区排除、日期向上继承、
    年份推断、商家名跨行合并。
    """

    name = "local"

    def is_available(self) -> tuple[bool, str]:
        return False, "ocr.reason.localNotImplemented"

    def extract(self, image: bytes, filename: str = "") -> ExtractResult:  # noqa: ARG002
        raise ExtractorNotConfigured(self.is_available()[1])


class LlmVisionExtractor:
    """云端多模态模型。M2 接入。

    图片连同结构化输出 Schema 一并提交，直接返回 RawTransaction 列表，
    跳过本地版式解析。启用前必须由用户在设置中显式确认数据将离开本机。
    """

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
    """按配置取得 Provider 实例。未知取值退回 NoneExtractor。"""
    key = (provider or settings.ocr_provider or "none").strip()
    return _REGISTRY.get(key, NoneExtractor)()


def provider_status() -> list[dict]:
    """供设置页展示各方案的可用状态。reason_key 由前端翻译。"""
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
