from dataclasses import dataclass, field


@dataclass
class CanonicalBodyModel:
    pelvis: str | None = None
    spine_lower: str | None = None
    spine_mid: str | None = None
    spine_upper: str | None = None
    neck: str | None = None
    head: str | None = None
    eye_l: str | None = None
    eye_r: str | None = None
    clavicle_l: str | None = None
    clavicle_r: str | None = None
    thigh_l: str | None = None
    thigh_r: str | None = None
    calf_l: str | None = None
    calf_r: str | None = None
    foot_l: str | None = None
    foot_r: str | None = None
    toe_l: str | None = None
    toe_r: str | None = None
    upper_arm_l: str | None = None
    upper_arm_r: str | None = None
    lower_arm_l: str | None = None
    lower_arm_r: str | None = None
    hand_l: str | None = None
    hand_r: str | None = None
    helpers: dict[str, list[str]] = field(default_factory=dict)
