"""Immutable, allowlisted presentation vocabulary. No raw display payloads."""
from dataclasses import dataclass
from enum import Enum


class Semantic(str, Enum):
    NEUTRAL = 'neutral'
    VERIFIED = 'verified'
    EXCEPTIONS = 'exceptions'
    INCOMPLETE = 'incomplete'
    WARNING = 'warning'
    BLOCKED = 'blocked'
    VALIDATION_FAILED = 'validation_failed'
    NEEDS_ATTENTION = 'needs_attention'
    UNAVAILABLE = 'unavailable'


SEMANTIC_LABELS = {semantic: 32130 + i for i, semantic in enumerate(Semantic)}


# Localized identifiers are the only supported text inputs. Domain objects,
# imported names, exception text, URLs and private dictionaries cannot enter.
TEXT_IDS = frozenset([32000, 32001] + list(range(32100, 32106)) +
                     list(range(32110, 32128)) + list(range(32130, 32139)) +
                     list(range(32140, 32150)) + list(range(32200, 32210)) +
                     list(range(32300, 32310)))


@dataclass(frozen=True)
class PageModel:
    title_id: int
    body_id: int
    semantic: Semantic = Semantic.NEUTRAL

    def __post_init__(self):
        if type(self.title_id) is not int or self.title_id not in TEXT_IDS:
            raise ValueError('unsupported presentation title')
        if type(self.body_id) is not int or self.body_id not in TEXT_IDS:
            raise ValueError('unsupported presentation content')
        if not isinstance(self.semantic, Semantic):
            raise ValueError('unsupported presentation category')

