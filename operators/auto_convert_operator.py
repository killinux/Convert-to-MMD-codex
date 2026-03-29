import bpy
import json
from . import weight_monitor


# 会修改权重的步骤（需要前后快照对比）
WEIGHT_STEPS = {
    "object.complete_missing_bones",
    "object.disable_xps_helper_bones",
    "object.split_spine_shoulder",
    "object.transfer_foretwist_weights",
    "object.check_fix_missing_weights",
}

STEP_IDS = {
    "object.complete_missing_bones": "step_2",
    "object.disable_xps_helper_bones": "step_2_5",
    "object.split_spine_shoulder": "step_3",
    "object.transfer_foretwist_weights": "step_6_5",
    "object.check_fix_missing_weights": "step_11",
}

HIGH_RISK_STEPS = {
    "object.disable_xps_helper_bones",
    "object.transfer_foretwist_weights",
    "object.check_fix_missing_weights",
}

# 这些步骤在某些场景里返回 CANCELLED 属于正常“无需执行”，不应中断全流程
BENIGN_CANCELLED_STEPS = {
    "object.merge_meshes",
}


def _resolve_source_armature(context):
    scene = context.scene
    source = getattr(scene, "semantic_source_armature", None)
    if source and source.type == 'ARMATURE' and source.name in scene.objects:
        return source
    active = context.active_object
    if active and active.type == 'ARMATURE':
        scene.semantic_source_armature = active
        return active
    return None


def _activate_armature(context, armature):
    if not armature or armature.type != 'ARMATURE':
        return False
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.view_layer.objects:
        o.select_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    return True

MMD_LIKE_BONE_TOKENS = (
    "全ての親",
    "センター",
    "グルーブ",
    "上半身",
    "下半身",
    "首",
    "頭",
    "肩.",
    "腕.",
    "ひじ.",
    "手首.",
    "左腕",
    "右腕",
    "左ひじ",
    "右ひじ",
    "左手首",
    "右手首",
    "足IK",
    "足ＩＫ",
    "IK親",
    "足首D",
    "ひざD",
    "足D.",
    "腕捩",
    "手捩",
)


def _parse_plan(scene):
    raw = getattr(scene, "semantic_plan_json", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _looks_like_converted_or_mixed_armature(obj) -> bool:
    if not obj or obj.type != 'ARMATURE':
        return False

    names = [bone.name for bone in obj.data.bones]
    hit_count = sum(
        1
        for name in names
        if any(token in name for token in MMD_LIKE_BONE_TOKENS)
    )
    return hit_count >= 6


def _has_direct_role(plan_data: dict, role: str) -> bool:
    for item in plan_data.get("direct_mapping", []) or []:
        if item.startswith(f"{role}:"):
            return True
    return False


def _build_steps_from_plan(plan_data: dict):
    helper_roles = set(plan_data.get("helper_roles", []) or [])

    steps = [
        ("object.merge_meshes", "网格合并"),
        ("object.clear_unweighted_bones", "清理无权重骨骼"),
        ("object.convert_to_apose", "转换为A-Pose"),
        ("object.rename_to_mmd", "重命名为MMD"),
        ("object.complete_missing_bones", "补全缺失骨骼"),
        ("object.split_spine_shoulder", "骨骼切分"),
    ]

    if helper_roles:
        steps.append(("object.disable_xps_helper_bones", "转移腿/腰辅助骨权重"))

    has_arm_chain = all(
        _has_direct_role(plan_data, role)
        for role in ("upper_arm_l", "upper_arm_r", "lower_arm_l", "lower_arm_r")
    )
    if has_arm_chain:
        steps.append(("object.add_twist_bones", "添加扭转骨骼"))
    if "twist_helper_l" in helper_roles or "twist_helper_r" in helper_roles:
        steps.append(("object.transfer_foretwist_weights", "转移前臂扭转权重"))

    steps.extend([
        ("object.add_mmd_ik", "添加MMD IK"),
        ("object.create_bone_group", "创建骨骼集合"),
        ("object.convert_materials_to_mmd", "材质转换"),
        ("object.check_fix_missing_weights", "权重修复（孤立骨+缺失骨+髋部渐变）"),
        ("object.verify_weights", "权重验证"),
    ])
    return steps


def summarize_execution_plan(plan_data: dict, allow_risky: bool) -> dict:
    runnable = []
    pending_manual = []
    skipped = []

    helper_roles = set(plan_data.get("helper_roles", []) or [])
    has_arm_chain = all(
        _has_direct_role(plan_data, role)
        for role in ("upper_arm_l", "upper_arm_r", "lower_arm_l", "lower_arm_r")
    )

    if not helper_roles:
        skipped.append("转移腿/腰辅助骨权重")
    if not has_arm_chain:
        skipped.append("添加扭转骨骼")
    if "twist_helper_l" not in helper_roles and "twist_helper_r" not in helper_roles:
        skipped.append("转移前臂扭转权重")

    for op_idname, step_name in _build_steps_from_plan(plan_data):
        if op_idname in HIGH_RISK_STEPS and not allow_risky:
            pending_manual.append(step_name)
        else:
            runnable.append(step_name)

    return {
        "runnable": runnable,
        "pending_manual": pending_manual,
        "skipped": skipped,
    }


class OBJECT_OT_auto_convert(bpy.types.Operator):
    """一键全流程：依次执行所有转换步骤（可单独执行各步调试）"""
    bl_idname = "object.auto_convert_to_mmd"
    bl_label = "一键全流程转换"

    def execute(self, context):
        obj = _resolve_source_armature(context)
        if not obj:
            self.report({'ERROR'}, "请选择源骨架对象（ARMATURE）")
            return {'CANCELLED'}
        if not _activate_armature(context, obj):
            self.report({'ERROR'}, "无法激活源骨架")
            return {'CANCELLED'}

        scene = context.scene
        scene.semantic_source_armature = obj
        scene["wm_last_check_result"] = ""

        # Stage A/B: 先生成语义计划并自动填充主干骨映射。
        try:
            scan_result = bpy.ops.object.debug_infer_semantic()
            if 'CANCELLED' in scan_result:
                self.report({'WARNING'}, "语义扫描被取消，继续按传统流程执行")
            else:
                bpy.ops.object.fill_mapping_from_semantic()
        except Exception as e:
            self.report({'WARNING'}, f"语义扫描/自动填骨映射失败，将继续按传统流程执行: {e}")

        plan_data = _parse_plan(scene)
        plan_mode = plan_data.get("mode", "unknown")
        profile_guess = plan_data.get("source_profile_guess", "unknown")
        plan_risks = plan_data.get("risks", []) or []
        has_plan_error = any(risk.get("level") == "error" for risk in plan_risks if isinstance(risk, dict))

        if has_plan_error:
            if _looks_like_converted_or_mixed_armature(obj):
                scene["wm_last_check_result"] = "❌ 一键流程中断: 当前骨架不是干净源骨架（含已有MMD/IK/补骨结果）"
                self.report(
                    {'ERROR'},
                    "当前骨架已包含较多 MMD/IK/补骨结果，不像干净的原始 XPS 源骨架；请换一个未转换的源骨架再执行一键流程"
                )
            else:
                scene["wm_last_check_result"] = "❌ 一键流程中断: ConversionPlan 判定骨架主干不完整"
                self.report({'ERROR'}, "ConversionPlan 判定当前骨架主干不完整，建议先手动检查语义识别结果")
            return {'CANCELLED'}

        execution_summary = summarize_execution_plan(plan_data, getattr(scene, "auto_convert_allow_risky", False))
        skipped = execution_summary["skipped"]
        pending_manual = execution_summary["pending_manual"]

        steps = []
        for op_idname, step_name in _build_steps_from_plan(plan_data):
            if op_idname in HIGH_RISK_STEPS and not getattr(scene, "auto_convert_allow_risky", False):
                continue
            steps.append((op_idname, step_name))

        # 清除旧的监控记录
        if "wm_snapshots" in obj:
            del obj["wm_snapshots"]
        context.scene["wm_step_status"] = "{}"

        failed = []
        weight_warnings = []

        for op_idname, step_name in steps:
            # 确保每步开始前活动对象固定为源骨架，避免误操作到目标骨架
            if not _activate_armature(context, obj):
                failed.append(f"{step_name}: 无法激活源骨架")
                break

            # 权重步骤：拍前快照
            pre_snapshot = None
            if op_idname in WEIGHT_STEPS:
                mesh_objects = weight_monitor._get_mesh_objects(context, obj)
                if mesh_objects:
                    pre_snapshot = weight_monitor.take_weight_snapshot(obj, mesh_objects)

            try:
                namespace, operator = op_idname.split(".", 1)
                result = getattr(getattr(bpy.ops, namespace), operator)()
                if 'CANCELLED' in result:
                    if op_idname in BENIGN_CANCELLED_STEPS:
                        self.report({'INFO'}, f"步骤「{step_name}」无需执行，已跳过")
                        continue
                    failed.append(f"{step_name}: CANCELLED")
                    self.report({'ERROR'}, f"步骤「{step_name}」被取消，已中断一键流程")
                    break
            except Exception as e:
                failed.append(f"{step_name}: {e}")
                self.report({'ERROR'}, f"步骤「{step_name}」失败，已中断一键流程: {e}")
                break

            # 权重步骤：拍后快照并对比
            # 注意：各 operator 的 execute() 末尾已有 auto_check 调用，
            # 这里额外做一次对比检查，报告给用户
            if pre_snapshot and op_idname in WEIGHT_STEPS:
                mesh_objects = weight_monitor._get_mesh_objects(context, obj)
                if mesh_objects:
                    post_snapshot = weight_monitor.take_weight_snapshot(obj, mesh_objects)
                    status, issues = weight_monitor.compare_snapshots(pre_snapshot, post_snapshot)
                    if status in ("warning", "error"):
                        weight_warnings.append(f"{step_name}: {'; '.join(issues)}")
                        self.report({'WARNING'}, f"⚠️ {step_name}: {'; '.join(issues)}")

        # 汇总报告
        summary_parts = []
        if pending_manual:
            summary_parts.append("待人工确认: " + " / ".join(pending_manual))
        if skipped:
            summary_parts.append("已跳过: " + " / ".join(skipped))
        if plan_mode != "unknown":
            summary_parts.append(f"plan={plan_mode}")
        if profile_guess != "unknown":
            summary_parts.append(f"profile={profile_guess}")
        if summary_parts:
            context.scene["wm_last_check_result"] = " | ".join(summary_parts)

        if failed:
            context.scene["wm_last_check_result"] = f"❌ 一键流程中断: {failed[0]}"
            self.report({'ERROR'}, f"一键流程已中断: {failed[0]}")
            return {'CANCELLED'}
        elif weight_warnings:
            self.report({'WARNING'},
                f"全流程完成，权重警告 {len(weight_warnings)} 处: {' | '.join(weight_warnings[:3])}")
        elif pending_manual:
            self.report({'INFO'}, f"已完成安全阶段，剩余高风险步骤待人工确认: {' / '.join(pending_manual)}")
        else:
            if plan_mode == "source_plus_reference":
                self.report({'INFO'}, f"✅ 全流程转换完成！按参考骨架计划执行（profile={profile_guess}）")
            elif plan_mode == "source_only":
                self.report({'INFO'}, f"✅ 全流程转换完成！按 source-only 计划执行（profile={profile_guess}）")
            else:
                self.report({'INFO'}, "✅ 全流程转换完成！权重监控全部通过")

        return {'FINISHED'}
