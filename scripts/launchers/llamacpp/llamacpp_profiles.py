from dataclasses import dataclass, field, replace
from enum import StrEnum

from scripts.config import models as model_cfg


class ContextSize(StrEnum):
    K16 = "16384"
    K32 = "32768"
    K48 = "49152"
    K64 = "65536"
    K80 = "81920"
    K96 = "98304"
    K128 = "131072"
    K160 = "163840"
    K192 = "196608"
    K200 = "204800"
    K256 = "262144"


@dataclass
class LLMProfile:
    model: str
    ini: str
    extra_args: dict[str, str] = field(default_factory=dict)


def with_extra(base: LLMProfile, **extra: str) -> LLMProfile:
    return replace(base, extra_args={**base.extra_args, **extra})


def model_base(model: str, ini: str) -> LLMProfile:
    return LLMProfile(model=model, ini=ini)


# --- common bases ------------------------------------------------------

BASE: dict[str, str] = {"ctx-size": ContextSize.K96}

MTP_BASE = {**BASE, "spec-type": "draft-mtp", "spec-draft-n-max": "3"}

ADAPTIVE_MTP_BASE = {**BASE, "spec-type": "draft-mtp-adaptive"}

NGRAM_BASE = {
    **BASE,
    "spec-type": "draft-mtp,ngram-mod",
    "spec-draft-n-max": "2",
    "spec-ngram-mod-n-min": "48",
    "spec-ngram-mod-n-max": "64",
    "spec-ngram-mod-n-match": "24",
}


# --- Swift 1.5 ---------------------------------------------------------

SWIFT15_BASE = model_base(model_cfg.path("llamacpp/Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp").name, "swift-q3.ini")

SWIFT15_MTP = with_extra(SWIFT15_BASE, **MTP_BASE)
SWIFT15_ADAPTIVE = with_extra(SWIFT15_BASE, **ADAPTIVE_MTP_BASE)
SWIFT15_MTP_NGRAM = with_extra(SWIFT15_BASE, **NGRAM_BASE)
SWIFT15_MTP_NGRAM_8K = with_extra(SWIFT15_MTP_NGRAM, **{"ctx-size": "8192"})
SWIFT15_MTP_NGRAM_LEGACY = with_extra(
    SWIFT15_MTP_NGRAM, **{"spec-ngram-mod-n-min": "4", "spec-ngram-mod-n-max": "8", "spec-ngram-mod-n-match": "32"}
)
SWIFT15_MTP_NOTEMPLATE = SWIFT15_BASE
SWIFT15_MTP_MEDIUM = with_extra(SWIFT15_BASE, **{"reasoning-effort": "medium"})
SWIFT15_NOSPEC = with_extra(SWIFT15_BASE, **{"spec-type": "none"})
SWIFT15_HRX = with_extra(
    SWIFT15_BASE,
    **{"ctx-size": "8192", "cache-type-k": "f16", "cache-type-v": "f16", "spec-type": "none", "reasoning": "off"},
)


# --- selected ----------------------------------------------------------


LLAMACPP_PROFILES: dict[str, LLMProfile] = {
    "swift15": SWIFT15_MTP_NGRAM,
    "swift15-8k": SWIFT15_MTP_NGRAM_8K,
    "swift15-hrx": SWIFT15_HRX,
}

LLAMACPP_BENCHMARK_PROFILES: dict[str, LLMProfile] = {
    "swift15-ngram-legacy": SWIFT15_MTP_NGRAM_LEGACY,
    "swift15-ngram-upstream": SWIFT15_MTP_NGRAM,
    "swift15-mtp-notemplate": SWIFT15_MTP_NOTEMPLATE,
    "swift15-mtp-medium": SWIFT15_MTP_MEDIUM,
    "swift15-nospec": SWIFT15_NOSPEC,
}
