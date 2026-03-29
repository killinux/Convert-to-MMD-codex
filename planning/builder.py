from ..profiles.registry import get_default_profile
from .model import ConversionPlan, PlanRisk


PLAN_ROLE_ORDER = [
    "pelvis",
    "spine_lower",
    "spine_mid",
    "spine_upper",
    "neck",
    "head",
    "eye_l",
    "eye_r",
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
]


def _guess_profile(source_dict: dict) -> str:
    helper_roles = source_dict.get("helpers", {}) or {}
    helper_names = " ".join(name.lower() for names in helper_roles.values() for name in names)
    if "unused bip001" in helper_names or "foretwist" in helper_names or "xtra" in helper_names:
        return "xna_lara"
    return get_default_profile().name


def build_conversion_plan(
    source_armature_name: str,
    source_recognized_count: int,
    source_dict: dict,
    target_armature_name: str | None = None,
    target_recognized_count: int = 0,
    target_dict: dict | None = None,
) -> ConversionPlan:
    mode = "source_plus_reference" if target_armature_name and target_dict else "source_only"
    target_dict = target_dict or {}
    plan = ConversionPlan(
        mode=mode,
        source_armature_name=source_armature_name,
        target_armature_name=target_armature_name,
        source_profile_guess=_guess_profile(source_dict),
        source_recognized_count=source_recognized_count,
        target_recognized_count=target_recognized_count,
    )

    for role in PLAN_ROLE_ORDER:
        src = source_dict.get(role)
        tgt = target_dict.get(role)
        if mode == "source_plus_reference":
            if src and tgt:
                plan.direct_mapping.append(f"{role}: {src} -> {tgt}")
            elif tgt and not src:
                plan.missing_in_source.append(role)
            elif src and not tgt:
                plan.missing_in_target.append(role)
        else:
            if src:
                plan.direct_mapping.append(f"{role}: {src}")
            else:
                plan.missing_in_source.append(role)

    helper_roles = sorted((source_dict.get("helpers") or {}).keys())
    plan.helper_roles = helper_roles

    plan.recommended_stages = [
        "Stage A: 扫描源骨架语义",
        "Stage B: 自动填骨映射",
        "Stage C: 主干骨重命名 / 对齐",
        "Stage D: 缺失骨与基础结构生成",
        "Stage E: 脊柱 / 肩部结构细化",
        "Stage F: helper / twist / hip 权重细化",
        "Stage G: 验证与修复",
    ]

    if plan.missing_in_source:
        plan.manual_review_items.append(f"源骨架缺失 {len(plan.missing_in_source)} 个目标角色，需补骨或人工确认")
        plan.risks.append(PlanRisk("warning", f"缺失角色: {', '.join(plan.missing_in_source[:8])}"))

    if helper_roles:
        plan.manual_review_items.append("源骨架存在 helper / twist 辅助骨，建议保留 2.5 / 6.5 阶段人工确认")
        plan.risks.append(PlanRisk("info", f"helper 角色 {len(helper_roles)} 类"))

    if not source_dict.get("pelvis") or not source_dict.get("thigh_l") or not source_dict.get("thigh_r"):
        plan.risks.append(PlanRisk("error", "腿部主干语义不完整，自动转换风险高"))

    if mode == "source_plus_reference" and target_dict:
        if not target_dict.get("pelvis") or not target_dict.get("spine_lower"):
            plan.risks.append(PlanRisk("warning", "目标骨架主干语义不完整，参考对比可能不稳定"))
    else:
        plan.risks.append(PlanRisk("info", "当前为 source-only 计划，未使用参考骨架"))

    return plan
