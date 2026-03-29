from collections import defaultdict

from ..profiles.registry import get_default_profile
from ..weights.snapshot import REGION_BONES, WATCHED_BONES
from .model import (
    BoneWeightEntry,
    StepChangeEntry,
    StepExpectationRule,
    TargetWeightEntry,
    WeightRelationshipSnapshot,
)


HELPER_KEYWORDS = (
    "unused ",
    "xtra",
    "foretwist",
    "muscle_",
    "_dummy_",
    "_shadow_",
)

# 腿根带属于过渡区，允许少量对侧/下半身残留，但不应超过这个比例。
THIGH_ROOT_OPPOSITE_RATIO_WARN = 0.40
THIGH_ROOT_LOWER_RATIO_WARN = 1.80

TARGET_BONES = set(WATCHED_BONES) | {
    "全ての親",
    "センター",
    "グルーブ",
    "腰",
    "下半身",
    "上半身",
    "上半身1",
    "上半身2",
    "上半身3",
    "首",
    "頭",
    "左足",
    "右足",
    "左ひざ",
    "右ひざ",
    "左足首",
    "右足首",
    "左足先EX",
    "右足先EX",
    "足D.L",
    "足D.R",
    "ひざD.L",
    "ひざD.R",
    "足首D.L",
    "足首D.R",
    "足先EX.L",
    "足先EX.R",
}


def _geometry_side(avg_x: float) -> str:
    if avg_x > 0.02:
        return "left"
    if avg_x < -0.02:
        return "right"
    return "center"


def _target_side(name: str) -> str:
    if not name:
        return "center"
    if name.endswith(".L") or name.endswith("_l") or name.startswith("左"):
        return "left"
    if name.endswith(".R") or name.endswith("_r") or name.startswith("右"):
        return "right"
    return "center"


def _collect_group_stats(mesh_objects):
    stats = defaultdict(lambda: {
        "vertex_count": 0,
        "weight_sum": 0.0,
        "weighted_x_sum": 0.0,
        "regions": set(),
    })

    for obj in mesh_objects:
        idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
        mw = obj.matrix_world
        for v in obj.data.vertices:
            group_names = []
            for g in v.groups:
                name = idx_to_name.get(g.group)
                if not name or g.weight <= 0.0005:
                    continue
                entry = stats[name]
                entry["vertex_count"] += 1
                entry["weight_sum"] += g.weight
                entry["weighted_x_sum"] += (mw @ v.co).x * g.weight
                group_names.append(name)

            if not group_names:
                continue

            for region_name, region_bones in REGION_BONES.items():
                if any(name in region_bones for name in group_names):
                    for name in group_names:
                        stats[name]["regions"].add(region_name)

    return stats


def _group_weight_on_band(mesh_objects, group_name, side: str, height_band: str = "upper") -> tuple[int, float]:
    matched_count = 0
    total_weight = 0.0

    for obj in mesh_objects:
        vg = obj.vertex_groups.get(group_name)
        if not vg:
            continue

        side_fk = "左足" if side == "left" else "右足"
        armature_obj = None
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object:
                armature_obj = mod.object
                break
        if not armature_obj:
            continue
        fk_bone = armature_obj.data.bones.get(side_fk)
        if not fk_bone:
            continue

        arm_mw = armature_obj.matrix_world
        hip = arm_mw @ fk_bone.head_local
        knee = arm_mw @ fk_bone.tail_local
        z_top = max(hip.z, knee.z)
        z_bottom = min(hip.z, knee.z)
        thigh_len = max(0.001, z_top - z_bottom)
        if height_band == "top":
            band_bottom = z_top - thigh_len * 0.12
            band_top = z_top + 0.001
        elif height_band == "mid":
            band_top = z_top - thigh_len * 0.18
            band_bottom = z_top - thigh_len * 0.58
        else:
            band_bottom = z_top - thigh_len * 0.32
            band_top = z_top + 0.001
        center_limit = max(0.02, abs(hip.x) * 0.18)

        idx = vg.index
        mw = obj.matrix_world
        for v in obj.data.vertices:
            co = mw @ v.co
            if co.z < band_bottom or co.z > band_top:
                continue
            if side == "left":
                if co.x <= center_limit:
                    continue
            else:
                if co.x >= -center_limit:
                    continue

            for g in v.groups:
                if g.group == idx and g.weight > 0.001:
                    matched_count += 1
                    total_weight += g.weight
                    break

    return matched_count, total_weight


def _band_weight_bundle(mesh_objects, side: str, height_band: str = "upper") -> dict:
    local_d = "足D.L" if side == "left" else "足D.R"
    opposite_d = "足D.R" if side == "left" else "足D.L"
    local_count, local_sum = _group_weight_on_band(mesh_objects, local_d, side, height_band)
    opposite_count, opposite_sum = _group_weight_on_band(mesh_objects, opposite_d, side, height_band)
    lower_count, lower_sum = _group_weight_on_band(mesh_objects, "下半身", side, height_band)
    return {
        "local_count": local_count,
        "local_sum": local_sum,
        "opposite_count": opposite_count,
        "opposite_sum": opposite_sum,
        "lower_count": lower_count,
        "lower_sum": lower_sum,
    }


def _build_source_entries(group_stats):
    entries = []
    for name, data in sorted(group_stats.items()):
        if name in TARGET_BONES:
            continue
        lowered = name.lower()
        entry_type = "helper" if any(key in lowered for key in HELPER_KEYWORDS) else "source"
        avg_x = data["weighted_x_sum"] / max(data["weight_sum"], 0.0001)
        entries.append(BoneWeightEntry(
            bone_name=name,
            current_group_name=name,
            vertex_count=data["vertex_count"],
            weight_sum=round(data["weight_sum"], 3),
            regions=sorted(data["regions"]),
            geometry_side=_geometry_side(avg_x),
            entry_type=entry_type,
            status="pending_transfer" if entry_type == "helper" else "normal",
        ))
    return entries


def _build_target_entries(group_stats):
    reverse_refs = defaultdict(list)
    profile = get_default_profile()
    for src_name, redirect in profile.helper_redirects.items():
        if isinstance(redirect, dict):
            target = redirect.get("target")
        else:
            target = redirect
        if target:
            reverse_refs[target].append(src_name)

    reverse_refs["足D.L"].append("左足")
    reverse_refs["ひざD.L"].append("左ひざ")
    reverse_refs["足首D.L"].append("左足首")
    reverse_refs["足先EX.L"].append("左足先EX")
    reverse_refs["足D.R"].append("右足")
    reverse_refs["ひざD.R"].append("右ひざ")
    reverse_refs["足首D.R"].append("右足首")
    reverse_refs["足先EX.R"].append("右足先EX")

    entries = []
    for name in sorted(TARGET_BONES):
        data = group_stats.get(name)
        entries.append(TargetWeightEntry(
            bone_name=name,
            bone_kind="control" if name in {"全ての親", "センター", "グルーブ", "腰"} else "deform",
            group_exists=data is not None,
            vertex_count=data["vertex_count"] if data else 0,
            weight_sum=round(data["weight_sum"], 3) if data else 0.0,
            regions=sorted(data["regions"]) if data else [],
            source_refs=sorted(set(reverse_refs.get(name, []))),
            status="empty" if data and data["weight_sum"] <= 0.001 else ("missing" if not data else "normal"),
        ))
    return entries


def _build_expectation_rules(step_id: str | None):
    if not step_id:
        return []

    rules = {
        "step_1": StepExpectationRule(
            step_id="step_1",
            required_groups=["下半身", "上半身", "上半身2", "首", "頭"],
            forbidden_missing_groups=["下半身", "上半身"],
            note="重命名后主干 MMD 组应可见。",
        ),
        "step_2": StepExpectationRule(
            step_id="step_2",
            required_groups=["下半身", "足D.L", "足D.R", "ひざD.L", "ひざD.R", "足首D.L", "足首D.R"],
            forbidden_missing_groups=["下半身", "足D.L", "足D.R"],
            risky_regions=["torso", "left_leg", "right_leg"],
            required_band_checks=["left_thigh_root_d", "right_thigh_root_d"],
            note="补全缺失骨骼后，关键 deform 组应建立。",
        ),
        "step_3": StepExpectationRule(
            step_id="step_3",
            required_groups=["上半身", "上半身1", "上半身2", "上半身3"],
            forbidden_missing_groups=["上半身", "上半身2", "上半身3"],
            risky_regions=["torso", "arms"],
            note="骨骼切分应主要影响躯干链。",
        ),
        "step_2_5": StepExpectationRule(
            step_id="step_2_5",
            required_groups=["下半身", "足D.L", "足D.R"],
            forbidden_missing_groups=["下半身"],
            risky_regions=["torso", "left_leg", "right_leg"],
            note="helper 转移允许高风险变化，但关键 deform 组不应丢失。",
        ),
    }
    rule = rules.get(step_id)
    return [rule] if rule else []


def build_weight_relationship_snapshot(mesh_objects, step_id: str | None = None):
    group_stats = _collect_group_stats(mesh_objects)
    source_entries = _build_source_entries(group_stats)
    target_entries = _build_target_entries(group_stats)
    rules = _build_expectation_rules(step_id)
    profile = get_default_profile()

    changes = []
    for rule in rules:
        target_lookup = {entry.bone_name: entry for entry in target_entries}
        for group_name in rule.required_groups:
            entry = target_lookup.get(group_name)
            if not entry or not entry.group_exists:
                changes.append(StepChangeEntry(
                    step_id=rule.step_id,
                    item_type="vertex_group",
                    name=group_name,
                    before="missing",
                    after="missing",
                    expected="unexpected",
                    severity="error" if group_name in rule.forbidden_missing_groups else "warning",
                    note=f"{group_name} 顶点组缺失",
                ))
            elif entry.weight_sum <= 0.001:
                changes.append(StepChangeEntry(
                    step_id=rule.step_id,
                    item_type="weight_relation",
                    name=group_name,
                    before="exists",
                    after="empty",
                    expected="unexpected",
                    severity="error" if group_name in rule.forbidden_missing_groups else "warning",
                    note=f"{group_name} 顶点组为空权重",
                ))

        for band_check in rule.required_band_checks:
            if band_check == "left_thigh_root_d":
                metrics = _band_weight_bundle(mesh_objects, "left", "upper")
                count = metrics["local_count"]
                total = metrics["local_sum"]
                changes.append(StepChangeEntry(
                    step_id=rule.step_id,
                    item_type="weight_relation",
                    name="左腿根带",
                    before="measured",
                    after=(
                        f"local={metrics['local_sum']:.3f}, "
                        f"opp={metrics['opposite_sum']:.3f}, "
                        f"lower={metrics['lower_sum']:.3f}"
                    ),
                    expected="expected_risky",
                    severity="info",
                    note="左腿根上缘带权重测量",
                ))
                if count <= 0 or total <= 0.5:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="足D.L@左腿根",
                        before="unknown",
                        after=f"count={count},sum={total:.3f}",
                        expected="unexpected",
                        severity="error",
                        note="左腿根上缘缺少足D.L权重",
                    ))
                elif metrics["opposite_sum"] > total * THIGH_ROOT_OPPOSITE_RATIO_WARN:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="左腿根串侧",
                        before="clean",
                        after=f"opp={metrics['opposite_sum']:.3f},local={total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=(
                            "左腿根上缘混入过多足D.R权重 "
                            f"(>{THIGH_ROOT_OPPOSITE_RATIO_WARN:.0%})"
                        ),
                    ))
                elif metrics["lower_sum"] > total * THIGH_ROOT_LOWER_RATIO_WARN:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="左腿根下半身过强",
                        before="balanced",
                        after=f"lower={metrics['lower_sum']:.3f},local={total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=(
                            "左腿根上缘下半身权重明显高于足D.L "
                            f"(>{THIGH_ROOT_LOWER_RATIO_WARN:.2f}x)"
                        ),
                    ))
            elif band_check == "right_thigh_root_d":
                metrics = _band_weight_bundle(mesh_objects, "right", "upper")
                count = metrics["local_count"]
                total = metrics["local_sum"]
                changes.append(StepChangeEntry(
                    step_id=rule.step_id,
                    item_type="weight_relation",
                    name="右腿根带",
                    before="measured",
                    after=(
                        f"local={metrics['local_sum']:.3f}, "
                        f"opp={metrics['opposite_sum']:.3f}, "
                        f"lower={metrics['lower_sum']:.3f}"
                    ),
                    expected="expected_risky",
                    severity="info",
                    note="右腿根上缘带权重测量",
                ))
                if count <= 0 or total <= 0.5:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="足D.R@右腿根",
                        before="unknown",
                        after=f"count={count},sum={total:.3f}",
                        expected="unexpected",
                        severity="error",
                        note="右腿根上缘缺少足D.R权重",
                    ))
                elif metrics["opposite_sum"] > total * THIGH_ROOT_OPPOSITE_RATIO_WARN:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="右腿根串侧",
                        before="clean",
                        after=f"opp={metrics['opposite_sum']:.3f},local={total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=(
                            "右腿根上缘混入过多足D.L权重 "
                            f"(>{THIGH_ROOT_OPPOSITE_RATIO_WARN:.0%})"
                        ),
                    ))
                elif metrics["lower_sum"] > total * THIGH_ROOT_LOWER_RATIO_WARN:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name="右腿根下半身过强",
                        before="balanced",
                        after=f"lower={metrics['lower_sum']:.3f},local={total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=(
                            "右腿根上缘下半身权重明显高于足D.R "
                            f"(>{THIGH_ROOT_LOWER_RATIO_WARN:.2f}x)"
                        ),
                    ))

        if rule.step_id == "step_2":
            for side, label in (("left", "左大腿控制带"), ("right", "右大腿控制带")):
                metrics = _band_weight_bundle(mesh_objects, side, "mid")
                local_name = "足D.L" if side == "left" else "足D.R"
                opposite_name = "足D.R" if side == "left" else "足D.L"
                local_total = metrics["local_sum"]
                changes.append(StepChangeEntry(
                    step_id=rule.step_id,
                    item_type="weight_relation",
                    name=label,
                    before="measured",
                    after=(
                        f"local={metrics['local_sum']:.3f}, "
                        f"opp={metrics['opposite_sum']:.3f}, "
                        f"lower={metrics['lower_sum']:.3f}"
                    ),
                    expected="expected_risky",
                    severity="info",
                    note=f"{label}（上大腿中段）权重测量",
                ))
                if metrics["local_count"] <= 0 or local_total <= 1.0:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name=f"{local_name}@{label}",
                        before="unknown",
                        after=f"count={metrics['local_count']},sum={local_total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=f"{label} 缺少 {local_name} 实际控制权重",
                    ))
                elif metrics["opposite_sum"] > local_total * 0.20:
                    changes.append(StepChangeEntry(
                        step_id=rule.step_id,
                        item_type="weight_relation",
                        name=f"{label}串侧",
                        before="clean",
                        after=f"opp={metrics['opposite_sum']:.3f},local={local_total:.3f}",
                        expected="unexpected",
                        severity="warning",
                        note=f"{label} 混入过多 {opposite_name} 权重",
                    ))

    source_lookup = {entry.bone_name: entry for entry in source_entries}
    for src_name, redirect in profile.helper_redirects.items():
        entry = source_lookup.get(src_name)
        if not entry:
            continue
        if isinstance(redirect, dict):
            target_name = redirect.get("target")
        else:
            target_name = redirect
        if not target_name:
            continue
        src_side = entry.geometry_side
        dst_side = _target_side(target_name)
        if src_side in {"left", "right"} and dst_side in {"left", "right"} and src_side != dst_side:
            changes.append(StepChangeEntry(
                step_id=step_id or "profile",
                item_type="profile_mapping",
                name=src_name,
                before=src_side,
                after=target_name,
                expected="unexpected",
                severity="warning",
                note=f"{src_name} 几何侧为{src_side}，却映射到 {target_name}",
            ))

    return WeightRelationshipSnapshot(
        source_entries=source_entries,
        target_entries=target_entries,
        step_changes=changes,
        expectation_rules=rules,
    )
