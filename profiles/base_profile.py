from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversionProfile:
    name: str
    helper_redirects: dict[str, Any] = field(default_factory=dict)
    foretwist_redirects: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
