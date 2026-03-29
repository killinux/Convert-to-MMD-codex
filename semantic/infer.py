from .types import SemanticBone


EXCLUDED_HEAD_TOKENS = {
    "hair",
    "bang",
    "tail",
    "twintail",
    "ponytail",
    "brow",
    "lash",
    "eyelid",
    "eyeball",
    "eyebrow",
    "mouth",
    "lip",
    "tongue",
    "cheek",
    "nose",
    "jaw",
}

GENERIC_CONTROL_TOKENS = (
    "_dummy_",
    "dummy",
    "ik",
    "twist",
    "捩",
    "操作中心",
    "全ての親",
    "センター",
    "グルーブ",
    "足d",
    "ひざd",
    "足首d",
    "腕d",
    "手d",
)

ROLE_RULES = {
    "pelvis_helper": {
        "patterns": ("unused bip001 pelvis",),
        "score": 1.0,
    },
    "pelvis": {
        "patterns": ("root hips", "hips", "pelvis", "hip", "下半身"),
        "exclude": ("spine", "helper", "unused"),
        "score": 0.9,
    },
    "spine_lower": {
        "patterns": ("spine lower", "lower spine", "spine1", "spine_01", "上半身"),
        "score": 0.95,
    },
    "spine_mid": {
        "patterns": ("spine middle", "spine mid", "spine2", "spine_02", "上半身1"),
        "score": 0.95,
    },
    "spine_upper": {
        "patterns": ("spine upper", "upper spine", "spine3", "spine_03", "chest", "上半身2", "上半身3"),
        "score": 0.95,
    },
    "neck": {
        "patterns": ("neck", "首"),
        "exclude": ("hair", "neck upper", "足首", "手首", "首d"),
        "score": 0.85,
    },
    "head": {
        "patterns": ("head neck upper", "head", "頭"),
        "exclude": tuple(EXCLUDED_HEAD_TOKENS),
        "score": 0.8,
    },
    "eye_l": {
        "patterns": ("eye_l", "left eye", "l eye", "left eyeball", "eyeball left", "左目", "目.l"),
        "score": 0.95,
    },
    "eye_r": {
        "patterns": ("eye_r", "right eye", "r eye", "right eyeball", "eyeball right", "右目", "目.r"),
        "score": 0.95,
    },
    "clavicle_l": {
        "patterns": ("left shoulder", "l shoulder", "clavicle_l", "shoulder.l", "左肩", "arm left shoulder", "肩.l"),
        "exclude": ("shoulder 2",),
        "score": 0.82,
    },
    "clavicle_r": {
        "patterns": ("right shoulder", "r shoulder", "clavicle_r", "shoulder.r", "右肩", "arm right shoulder", "肩.r"),
        "exclude": ("shoulder 2",),
        "score": 0.82,
    },
    "upper_arm_l": {
        "patterns": ("upperarm_l", "upper arm l", "left upper arm", "arm left upper", "arm left shoulder 2", "left arm", "左腕", "腕.l"),
        "exclude": ("forearm", "elbow", "hand", "wrist", "shoulder 1"),
        "score": 0.9,
    },
    "upper_arm_r": {
        "patterns": ("upperarm_r", "upper arm r", "right upper arm", "arm right upper", "arm right shoulder 2", "right arm", "右腕", "腕.r"),
        "exclude": ("forearm", "elbow", "hand", "wrist", "shoulder 1"),
        "score": 0.9,
    },
    "lower_arm_l": {
        "patterns": ("left elbow", "left forearm", "l forearm", "forearm_l", "elbow.l", "左ひじ", "arm left elbow", "ひじ.l"),
        "score": 0.95,
    },
    "lower_arm_r": {
        "patterns": ("right elbow", "right forearm", "r forearm", "forearm_r", "elbow.r", "右ひじ", "arm right elbow", "ひじ.r"),
        "score": 0.95,
    },
    "hand_l": {
        "patterns": ("left wrist", "left hand", "l hand", "hand_l", "wrist.l", "左手首", "arm left wrist", "手首.l"),
        "score": 0.9,
    },
    "hand_r": {
        "patterns": ("right wrist", "right hand", "r hand", "hand_r", "wrist.r", "右手首", "arm right wrist", "手首.r"),
        "score": 0.9,
    },
    "thigh_l": {
        "patterns": ("leg left thigh", "left thigh", "l thigh", "thigh_l", "左足", "足.l"),
        "score": 0.98,
    },
    "thigh_r": {
        "patterns": ("leg right thigh", "right thigh", "r thigh", "thigh_r", "右足", "足.r"),
        "score": 0.98,
    },
    "calf_l": {
        "patterns": ("leg left knee", "left knee", "left calf", "calf_l", "左ひざ", "ひざ.l"),
        "score": 0.98,
    },
    "calf_r": {
        "patterns": ("leg right knee", "right knee", "right calf", "calf_r", "右ひざ", "ひざ.r"),
        "score": 0.98,
    },
    "foot_l": {
        "patterns": ("leg left ankle", "left ankle", "left foot", "foot_l", "左足首", "足首.l"),
        "score": 0.98,
    },
    "foot_r": {
        "patterns": ("leg right ankle", "right ankle", "right foot", "foot_r", "右足首", "足首.r"),
        "score": 0.98,
    },
    "toe_l": {
        "patterns": ("leg left toes", "left toe", "left toes", "toe_l", "左足先ex", "左つま先", "足先ex.l"),
        "score": 0.98,
    },
    "toe_r": {
        "patterns": ("leg right toes", "right toe", "right toes", "toe_r", "右足先ex", "右つま先", "足先ex.r"),
        "score": 0.98,
    },
    "inner_thigh_helper_l": {
        "patterns": ("unused bip001 xtra04",),
        "score": 1.0,
    },
    "inner_thigh_helper_r": {
        "patterns": ("unused bip001 xtra02",),
        "score": 1.0,
    },
    "twist_helper_l": {
        "patterns": ("unused bip001 l foretwist", "unused bip001 l foretwist1"),
        "score": 1.0,
    },
    "twist_helper_r": {
        "patterns": ("unused bip001 r foretwist", "unused bip001 r foretwist1"),
        "score": 1.0,
    },
}


def _infer_role_from_name(bone_name: str):
    lowered = bone_name.strip().lower()
    best_role = "unknown"
    best_pattern = ""
    best_score = 0.0

    for role, rule in ROLE_RULES.items():
        if role.endswith("_helper") or "helper" in role:
            pass
        elif any(token in lowered for token in GENERIC_CONTROL_TOKENS):
            continue
        excludes = rule.get("exclude", ())
        if any(token in lowered for token in excludes):
            continue
        for pattern in rule["patterns"]:
            if pattern in lowered:
                score = rule["score"] + min(len(pattern) / 100.0, 0.1)
                if score > best_score:
                    best_role = role
                    best_pattern = pattern
                    best_score = score
    return best_role, best_pattern, best_score


def infer_semantic_bones(armature_obj) -> list[SemanticBone]:
    """Infer semantic bone roles from a Blender armature.

    Current implementation uses naming heuristics as the first layer.
    Later phases should augment this with topology and spatial inference.
    """
    if not armature_obj or armature_obj.type != 'ARMATURE':
        return []

    inferred = []
    for bone in armature_obj.data.bones:
        role, matched_pattern, confidence = _infer_role_from_name(bone.name)
        reasons = [f"name:{matched_pattern}"] if matched_pattern else ["name:no_match"]
        inferred.append(SemanticBone(
            source_name=bone.name,
            role=role,
            confidence=confidence,
            reasons=reasons,
        ))
    return inferred
