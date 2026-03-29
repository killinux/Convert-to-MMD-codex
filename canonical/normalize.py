from .model import CanonicalBodyModel
from ..semantic.types import SemanticBone


ROLE_TO_FIELD = {
    "pelvis": "pelvis",
    "spine_lower": "spine_lower",
    "spine_mid": "spine_mid",
    "spine_upper": "spine_upper",
    "neck": "neck",
    "head": "head",
    "eye_l": "eye_l",
    "eye_r": "eye_r",
    "clavicle_l": "clavicle_l",
    "clavicle_r": "clavicle_r",
    "thigh_l": "thigh_l",
    "thigh_r": "thigh_r",
    "calf_l": "calf_l",
    "calf_r": "calf_r",
    "foot_l": "foot_l",
    "foot_r": "foot_r",
    "toe_l": "toe_l",
    "toe_r": "toe_r",
    "upper_arm_l": "upper_arm_l",
    "upper_arm_r": "upper_arm_r",
    "lower_arm_l": "lower_arm_l",
    "lower_arm_r": "lower_arm_r",
    "hand_l": "hand_l",
    "hand_r": "hand_r",
}


def build_canonical_body_model(semantic_bones: list[SemanticBone]) -> CanonicalBodyModel:
    """Normalize inferred semantic bones into a canonical humanoid model."""
    model = CanonicalBodyModel()
    helper_roles = {}
    best_candidates = {}

    for bone in semantic_bones:
        field_name = ROLE_TO_FIELD.get(bone.role)
        if field_name:
            current = best_candidates.get(field_name)
            if current is None or bone.confidence > current.confidence:
                best_candidates[field_name] = bone
            continue

        if bone.role.endswith("_helper") or "helper" in bone.role:
            helper_roles.setdefault(bone.role, []).append(bone.source_name)

    for field_name, bone in best_candidates.items():
        setattr(model, field_name, bone.source_name)

    model.helpers = helper_roles
    return model
