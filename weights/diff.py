from dataclasses import dataclass, field


@dataclass
class WeightDiff:
    changed_bones: list[dict] = field(default_factory=list)
    changed_regions: list[dict] = field(default_factory=list)
    changed_vertices: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def diff_snapshots(before, after, top_n=20):
    """Build a coarse diff between two WeightSnapshot instances."""
    diff = WeightDiff()

    before_stats = before.bone_stats if before else {}
    after_stats = after.bone_stats if after else {}
    names = sorted(set(before_stats.keys()) | set(after_stats.keys()))

    for name in names:
        prev = before_stats.get(name)
        curr = after_stats.get(name)
        prev_count = prev.vertex_count if prev else 0
        curr_count = curr.vertex_count if curr else 0
        prev_sum = prev.weight_sum if prev else 0.0
        curr_sum = curr.weight_sum if curr else 0.0

        delta_count = curr_count - prev_count
        delta_sum = curr_sum - prev_sum
        if delta_count == 0 and abs(delta_sum) < 0.001:
            continue

        diff.changed_bones.append({
            "bone": name,
            "before_count": prev_count,
            "after_count": curr_count,
            "delta_count": delta_count,
            "before_sum": round(prev_sum, 3),
            "after_sum": round(curr_sum, 3),
            "delta_sum": round(delta_sum, 3),
        })

    diff.changed_bones.sort(key=lambda item: (abs(item["delta_sum"]), abs(item["delta_count"])), reverse=True)
    diff.changed_bones = diff.changed_bones[:top_n]

    before_regions = before.region_stats if before else {}
    after_regions = after.region_stats if after else {}
    region_names = sorted(set(before_regions.keys()) | set(after_regions.keys()))

    for name in region_names:
        prev = before_regions.get(name)
        curr = after_regions.get(name)
        prev_count = prev.vertex_count if prev else 0
        curr_count = curr.vertex_count if curr else 0
        prev_sum = prev.weight_sum if prev else 0.0
        curr_sum = curr.weight_sum if curr else 0.0

        delta_count = curr_count - prev_count
        delta_sum = curr_sum - prev_sum
        if delta_count == 0 and abs(delta_sum) < 0.001:
            continue

        diff.changed_regions.append({
            "region": name,
            "before_count": prev_count,
            "after_count": curr_count,
            "delta_count": delta_count,
            "before_sum": round(prev_sum, 3),
            "after_sum": round(curr_sum, 3),
            "delta_sum": round(delta_sum, 3),
        })

    diff.changed_regions.sort(key=lambda item: (abs(item["delta_sum"]), abs(item["delta_count"])), reverse=True)
    diff.changed_regions = diff.changed_regions[:top_n]

    if before and after:
        if after.conflict_count > before.conflict_count:
            diff.warnings.append(
                f"冲突顶点增加: {before.conflict_count} -> {after.conflict_count}"
            )
        if after.hip_left_binary > before.hip_left_binary + 20:
            diff.warnings.append(
                f"左髋硬切割增加: {before.hip_left_binary} -> {after.hip_left_binary}"
            )
        if after.hip_right_binary > before.hip_right_binary + 20:
            diff.warnings.append(
                f"右髋硬切割增加: {before.hip_right_binary} -> {after.hip_right_binary}"
            )

    return diff
