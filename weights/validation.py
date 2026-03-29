from .snapshot import WeightSnapshot
from .diff import diff_snapshots


REGION_LABELS = {
    "torso": "躯干",
    "left_leg": "左腿",
    "right_leg": "右腿",
    "arms": "手臂",
}

CRITICAL_BONES = [
    "足D.L",
    "足D.R",
    "下半身",
]

STEP_CRITICAL_BONES = {
    "step_3": ["上半身", "上半身1", "上半身2", "上半身3"],
}


def _legacy_to_snapshot(metrics) -> WeightSnapshot:
    from .snapshot import BoneWeightStats

    bone_stats = {
        name: BoneWeightStats(vertex_count=metrics.get("bone_counts", {}).get(name, 0),
                              weight_sum=metrics.get("bone_sums", {}).get(name, 0.0))
        for name in set(metrics.get("bone_counts", {})) | set(metrics.get("bone_sums", {}))
    }
    region_stats = {
        name: BoneWeightStats(vertex_count=metrics.get("region_counts", {}).get(name, 0),
                              weight_sum=metrics.get("region_sums", {}).get(name, 0.0))
        for name in set(metrics.get("region_counts", {})) | set(metrics.get("region_sums", {}))
    }
    return WeightSnapshot(
        bone_stats=bone_stats,
        region_stats=region_stats,
        hip_left_binary=metrics.get("hip_left_binary", 0),
        hip_right_binary=metrics.get("hip_right_binary", 0),
        hip_left_blend=metrics.get("hip_left_blend", 0),
        hip_right_blend=metrics.get("hip_right_blend", 0),
        conflict_count=metrics.get("conflict_count", 0),
        total_verts=metrics.get("total_verts", 0),
    )


def _status_rank(status: str) -> int:
    return {"ok": 0, "warning": 1, "error": 2}.get(status, 0)


def _merge_status(*statuses: str) -> str:
    return max(statuses, key=_status_rank)


def evaluate_snapshot(metrics: dict):
    issues = []
    status = "ok"

    for bone in CRITICAL_BONES:
        count = metrics.get("bone_counts", {}).get(bone, 0)
        if count == 0:
            issues.append(f"{bone} 无权重")
            status = "error"

    lb = metrics.get("hip_left_binary", 0)
    rb = metrics.get("hip_right_binary", 0)
    if lb > 100 or rb > 100:
        issues.append(f"髋部硬切割: 左={lb} 右={rb}")
        status = _merge_status(status, "error")

    cc = metrics.get("conflict_count", 0)
    if cc > 50:
        issues.append(f"冲突顶点过多: {cc}")
        status = _merge_status(status, "warning")

    summary = (
        f"躯干={metrics.get('region_counts', {}).get('torso', 0)} "
        f"| 左腿={metrics.get('region_counts', {}).get('left_leg', 0)} "
        f"| 右腿={metrics.get('region_counts', {}).get('right_leg', 0)} "
        f"| 手臂={metrics.get('region_counts', {}).get('arms', 0)} "
        f"| 冲突={cc}"
    )
    return status, issues, summary


def compare_step_metrics(before_metrics: dict, after_metrics: dict, step_id: str | None = None):
    before = _legacy_to_snapshot(before_metrics)
    after = _legacy_to_snapshot(after_metrics)
    diff = diff_snapshots(before, after, top_n=6)

    issues = list(diff.warnings)
    status = "ok"

    critical_bones = STEP_CRITICAL_BONES.get(step_id, CRITICAL_BONES)

    for bone in critical_bones:
        prev_sum = before_metrics.get("bone_sums", {}).get(bone, 0.0)
        curr_sum = after_metrics.get("bone_sums", {}).get(bone, 0.0)
        if prev_sum > 10 and curr_sum < prev_sum * 0.35:
            issues.append(f"{bone} 权重骤降 {prev_sum:.0f}->{curr_sum:.0f}")
            status = _merge_status(status, "error")
        elif prev_sum > 10 and curr_sum < prev_sum * 0.7:
            issues.append(f"{bone} 权重下降 {prev_sum:.0f}->{curr_sum:.0f}")
            status = _merge_status(status, "warning")

    watched_regions = REGION_LABELS.keys()
    if step_id == "step_3":
        watched_regions = ("torso", "arms")

    for region_name in watched_regions:
        label = REGION_LABELS[region_name]
        prev_sum = before_metrics.get("region_sums", {}).get(region_name, 0.0)
        curr_sum = after_metrics.get("region_sums", {}).get(region_name, 0.0)
        if prev_sum > 20 and curr_sum < prev_sum * 0.45:
            issues.append(f"{label}区域权重骤降 {prev_sum:.0f}->{curr_sum:.0f}")
            status = _merge_status(status, "error")
        elif prev_sum > 20 and curr_sum < prev_sum * 0.75:
            issues.append(f"{label}区域权重下降 {prev_sum:.0f}->{curr_sum:.0f}")
            status = _merge_status(status, "warning")

    delta_conflict = after_metrics.get("conflict_count", 0) - before_metrics.get("conflict_count", 0)
    if delta_conflict > 50:
        issues.append(f"冲突顶点 +{delta_conflict}")
        status = _merge_status(status, "error")
    elif delta_conflict > 20:
        issues.append(f"冲突顶点 +{delta_conflict}")
        status = _merge_status(status, "warning")

    top_region = diff.changed_regions[0]["region"] if diff.changed_regions else None
    top_bone = diff.changed_bones[0]["bone"] if diff.changed_bones else None
    summary_parts = []
    if top_region:
        summary_parts.append(f"区域变化={REGION_LABELS.get(top_region, top_region)}")
    if top_bone:
        summary_parts.append(f"骨变化={top_bone}")
    summary_parts.append(
        f"冲突={before_metrics.get('conflict_count', 0)}->{after_metrics.get('conflict_count', 0)}"
    )
    summary = " | ".join(summary_parts)
    return status, issues, summary
