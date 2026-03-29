"""权重健康监控系统 — 每步执行后自动拍快照，检测权重退化。"""

import bpy
import json
import time

from ..planning.relationship_builder import build_weight_relationship_snapshot
from ..weights.diff import diff_snapshots
from ..weights.snapshot import get_mesh_objects as _snapshot_get_mesh_objects
from ..weights.snapshot import take_weight_snapshot as _snapshot_take_weight_snapshot
from ..weights.validation import _legacy_to_snapshot
from ..weights.validation import compare_step_metrics, evaluate_snapshot

EXPECTED_INTERMEDIATE_RISK_STEPS = {
    "step_2_5": "已知中间风险",
    "step_6_5": "中间波动",
}


def _get_mesh_objects(context, armature):
    return _snapshot_get_mesh_objects(context, armature)


def take_weight_snapshot(armature, mesh_objects):
    """兼容旧调用：返回历史上使用的 dict 结构。"""
    return _snapshot_take_weight_snapshot(armature, mesh_objects).to_legacy_dict()


def evaluate_health(snapshot):
    """绝对健康评估（不需要前后对比），返回 (status, issues)。"""
    status, issues, _summary = evaluate_snapshot(snapshot)
    return status, issues


def compare_snapshots(pre, post):
    """对比前后快照，返回 (status, issues)。"""
    status, issues, _summary = compare_step_metrics(pre, post)
    return status, issues


def store_snapshot(armature, step_id, step_label, metrics, status, issues, summary=""):
    """将快照存入骨架自定义属性。"""
    try:
        existing = json.loads(armature.get("wm_snapshots", "{}"))
    except (json.JSONDecodeError, TypeError):
        existing = {}

    existing[step_id] = {
        "label": step_label,
        "status": status,
        "issues": issues,
        "time": time.strftime("%H:%M:%S"),
        "timestamp": time.time(),
        "hip_l_bin": metrics.get("hip_left_binary", 0),
        "hip_r_bin": metrics.get("hip_right_binary", 0),
        "hip_l_blend": metrics.get("hip_left_blend", 0),
        "hip_r_blend": metrics.get("hip_right_blend", 0),
        "conflict": metrics.get("conflict_count", 0),
        "summary": summary,
        "metrics": metrics,
    }
    armature["wm_snapshots"] = json.dumps(existing, ensure_ascii=False)


def _merge_relationship_issues(snapshot, status, issues):
    rel = build_weight_relationship_snapshot([], None)
    if snapshot:
        rel = snapshot

    for change in rel.step_changes:
        if change.expected != "unexpected":
            continue
        issues.append(change.note or change.name)
        if change.severity == "error":
            status = "error"
        elif change.severity == "warning" and status != "error":
            status = "warning"
    return status, issues, rel


def _latest_non_manual_step(existing: dict) -> str | None:
    candidates = [
        (key, value) for key, value in existing.items()
        if key != "manual"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            item[1].get("timestamp", 0.0),
            item[1].get("time", ""),
            item[0],
        )
    )
    return candidates[-1][0]


def _latest_snapshot_key(existing: dict) -> str | None:
    if not existing:
        return None
    ordered = sorted(
        existing.items(),
        key=lambda item: (
            item[1].get("timestamp", 0.0),
            item[1].get("time", ""),
            item[0],
        ),
    )
    return ordered[-1][0]


def _store_relationship_snapshot(armature, snapshot_key, relationship_snapshot, relationship_step_id=None, diff=None):
    try:
        existing = json.loads(armature.get("wm_snapshots", "{}"))
    except (json.JSONDecodeError, TypeError):
        existing = {}
    if snapshot_key not in existing:
        return

    existing[snapshot_key]["relationship_snapshot"] = relationship_snapshot.to_dict()
    if relationship_step_id:
        existing[snapshot_key]["relationship_step_id"] = relationship_step_id
    if diff:
        existing[snapshot_key]["weight_diff"] = {
            "changed_bones": diff.changed_bones,
            "changed_regions": diff.changed_regions,
            "warnings": diff.warnings,
        }
    armature["wm_snapshots"] = json.dumps(existing, ensure_ascii=False)


def auto_check_after_step(context, armature, step_id, step_label):
    """步骤执行后调用：拍快照 → 评估 → 存储 → 更新 UI。"""
    mesh_objects = _get_mesh_objects(context, armature)
    if not mesh_objects:
        return

    snapshot = take_weight_snapshot(armature, mesh_objects)

    # 尝试与上一步对比
    try:
        existing = json.loads(armature.get("wm_snapshots", "{}"))
    except (json.JSONDecodeError, TypeError):
        existing = {}

    latest_prev_key = _latest_snapshot_key(existing)
    prev_keys = list(existing.keys())
    if latest_prev_key and "metrics" not in existing.get(latest_prev_key, {}):
        # 旧格式没有完整 metrics，只做绝对评估
        status, issues = evaluate_health(snapshot)
    elif latest_prev_key:
        # 用最近一步的 metrics 对比
        prev_entry = existing[latest_prev_key]
        # 构造伪 pre snapshot 用于对比
        pre_approx = {
            "hip_left_binary": prev_entry.get("hip_l_bin", 0),
            "hip_right_binary": prev_entry.get("hip_r_bin", 0),
            "conflict_count": prev_entry.get("conflict", 0),
            "bone_sums": {},
            "bone_counts": {},
        }
        status, issues, _cmp_summary = compare_step_metrics(pre_approx, snapshot, step_id=step_id)
        # 同时做绝对评估，取更严重的
        abs_status, abs_issues = evaluate_health(snapshot)
        if abs_status == "error" and status != "error":
            status = abs_status
        issues = list(set(issues + abs_issues))
    else:
        status, issues = evaluate_health(snapshot)

    if latest_prev_key and "metrics" in existing.get(latest_prev_key, {}):
        _cmp_status, _cmp_issues, summary = compare_step_metrics(
            existing[latest_prev_key]["metrics"],
            snapshot,
            step_id=step_id,
        )
        diff = diff_snapshots(
            _legacy_to_snapshot(existing[latest_prev_key]["metrics"]),
            _legacy_to_snapshot(snapshot),
            top_n=5,
        )
    else:
        _abs_status, _abs_issues, summary = evaluate_snapshot(snapshot)
        diff = None

    relationship_snapshot = build_weight_relationship_snapshot(mesh_objects, step_id=step_id)
    status, issues, relationship_snapshot = _merge_relationship_issues(
        relationship_snapshot, status, issues
    )

    store_snapshot(armature, step_id, step_label, snapshot, status, issues, summary)
    _store_relationship_snapshot(
        armature,
        step_id,
        relationship_snapshot,
        relationship_step_id=step_id,
        diff=diff,
    )

    # 更新 Scene 属性供 UI 显示
    try:
        step_status = json.loads(context.scene.get("wm_step_status", "{}"))
    except (json.JSONDecodeError, TypeError):
        step_status = {}
    step_status[step_id] = status
    context.scene["wm_step_status"] = json.dumps(step_status, ensure_ascii=False)

    # 更新最近一次检查结果
    rel_unexpected = len([c for c in relationship_snapshot.step_changes if c.expected == "unexpected"])
    summary_with_rel = summary
    if rel_unexpected:
        summary_with_rel = f"{summary} | 关系异常={rel_unexpected}" if summary else f"关系异常={rel_unexpected}"

    if issues:
        risk_prefix = EXPECTED_INTERMEDIATE_RISK_STEPS.get(step_id)
        if risk_prefix and status == "warning":
            base = f"⚠️ {step_label}: {risk_prefix}，{'；'.join(issues[:2])}"
        else:
            base = f"⚠️ {step_label}: {'; '.join(issues[:2])}"
        context.scene["wm_last_check_result"] = f"{base} | {summary_with_rel}" if summary_with_rel else base
    else:
        context.scene["wm_last_check_result"] = f"✅ {step_label}: {summary_with_rel or '权重健康'}"


class OBJECT_OT_weight_health_check(bpy.types.Operator):
    """手动运行全局权重健康检查"""
    bl_idname = "object.weight_health_check"
    bl_label = "权重体检"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = _get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        snapshot = take_weight_snapshot(armature, mesh_objects)
        status, issues, summary = evaluate_snapshot(snapshot)
        try:
            existing = json.loads(armature.get("wm_snapshots", "{}"))
        except (json.JSONDecodeError, TypeError):
            existing = {}
        rel_step_id = _latest_non_manual_step(existing) or "manual"
        relationship_snapshot = build_weight_relationship_snapshot(mesh_objects, step_id=rel_step_id)
        status, issues, relationship_snapshot = _merge_relationship_issues(
            relationship_snapshot, status, issues
        )
        store_snapshot(armature, "manual", "手动体检", snapshot, status, issues, summary)
        _store_relationship_snapshot(
            armature,
            "manual",
            relationship_snapshot,
            relationship_step_id=rel_step_id,
        )

        # 更新 UI
        try:
            step_status = json.loads(context.scene.get("wm_step_status", "{}"))
        except (json.JSONDecodeError, TypeError):
            step_status = {}
        step_status["manual"] = status
        context.scene["wm_step_status"] = json.dumps(step_status, ensure_ascii=False)

        # 构建详细报告
        rel_unexpected = len([c for c in relationship_snapshot.step_changes if c.expected == "unexpected"])
        result_text = f"{summary} | 关系异常={rel_unexpected}" if rel_unexpected else summary
        context.scene["wm_last_check_result"] = result_text

        if issues:
            self.report({'WARNING'}, f"⚠️ {'; '.join(issues)}")
        else:
            self.report({'INFO'}, f"✅ 权重健康 | {result_text}")
        return {'FINISHED'}


class OBJECT_OT_weight_clear_monitor(bpy.types.Operator):
    """清除权重监控历史记录"""
    bl_idname = "object.weight_clear_monitor"
    bl_label = "清除监控记录"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = context.active_object
        if armature and armature.type == 'ARMATURE':
            if "wm_snapshots" in armature:
                del armature["wm_snapshots"]
        context.scene["wm_step_status"] = "{}"
        context.scene["wm_last_check_result"] = ""
        self.report({'INFO'}, "已清除监控记录")
        return {'FINISHED'}
