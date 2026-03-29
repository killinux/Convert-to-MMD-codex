from dataclasses import dataclass, field
from typing import Literal

SemanticRole = Literal[
    "root",
    "pelvis",
    "spine_lower",
    "spine_mid",
    "spine_upper",
    "neck",
    "head",
    "clavicle_l",
    "clavicle_r",
    "upper_arm_l",
    "upper_arm_r",
    "lower_arm_l",
    "lower_arm_r",
    "hand_l",
    "hand_r",
    "thigh_l",
    "thigh_r",
    "calf_l",
    "calf_r",
    "foot_l",
    "foot_r",
    "toe_l",
    "toe_r",
    "eye_l",
    "eye_r",
    "pelvis_helper",
    "inner_thigh_helper_l",
    "inner_thigh_helper_r",
    "twist_helper_l",
    "twist_helper_r",
    "unknown",
]


@dataclass
class SemanticBone:
    source_name: str
    role: SemanticRole
    confidence: float
    reasons: list[str] = field(default_factory=list)

