import bpy
import json

from ..canonical.normalize import build_canonical_body_model
from ..planning.builder import build_conversion_plan
from ..semantic.infer import infer_semantic_bones

ROLE_TO_SCENE_PROP = {
    "neck": "neck_bone",
    "head": "head_bone",
    "eye_l": "left_eye_bone",
    "eye_r": "right_eye_bone",
    "clavicle_l": "left_shoulder_bone",
    "clavicle_r": "right_shoulder_bone",
    "upper_arm_l": "left_upper_arm_bone",
    "upper_arm_r": "right_upper_arm_bone",
    "lower_arm_l": "left_lower_arm_bone",
    "lower_arm_r": "right_lower_arm_bone",
    "hand_l": "left_hand_bone",
    "hand_r": "right_hand_bone",
    "pelvis": "lower_body_bone",
    "spine_lower": "upper_body_bone",
    "spine_upper": "upper_body2_bone",
    "thigh_l": "left_thigh_bone",
    "thigh_r": "right_thigh_bone",
    "calf_l": "left_calf_bone",
    "calf_r": "right_calf_bone",
    "foot_l": "left_foot_bone",
    "foot_r": "right_foot_bone",
    "toe_l": "left_toe_bone",
    "toe_r": "right_toe_bone",
}


def _canonical_to_dict(canonical):
    return {
        "pelvis": canonical.pelvis,
        "spine_lower": canonical.spine_lower,
        "spine_mid": canonical.spine_mid,
        "spine_upper": canonical.spine_upper,
        "neck": canonical.neck,
        "head": canonical.head,
        "eye_l": canonical.eye_l,
        "eye_r": canonical.eye_r,
        "clavicle_l": canonical.clavicle_l,
        "clavicle_r": canonical.clavicle_r,
        "upper_arm_l": canonical.upper_arm_l,
        "upper_arm_r": canonical.upper_arm_r,
        "lower_arm_l": canonical.lower_arm_l,
        "lower_arm_r": canonical.lower_arm_r,
        "hand_l": canonical.hand_l,
        "hand_r": canonical.hand_r,
        "thigh_l": canonical.thigh_l,
        "thigh_r": canonical.thigh_r,
        "calf_l": canonical.calf_l,
        "calf_r": canonical.calf_r,
        "foot_l": canonical.foot_l,
        "foot_r": canonical.foot_r,
        "toe_l": canonical.toe_l,
        "toe_r": canonical.toe_r,
        "helpers": canonical.helpers,
    }


def _scan_armature(armature):
    semantic_bones = infer_semantic_bones(armature)
    canonical = build_canonical_body_model(semantic_bones)
    recognized = [bone for bone in semantic_bones if bone.role != "unknown"]
    preview = [f"{bone.source_name} -> {bone.role}" for bone in recognized[:20]]
    return {
        "semantic_bones": semantic_bones,
        "canonical": canonical,
        "canonical_dict": _canonical_to_dict(canonical),
        "recognized_count": len(recognized),
        "preview": preview,
    }
def _plan_to_summary_lines(plan):
    lines = []
    if plan.direct_mapping:
        lines.append("直接映射: " + " | ".join(plan.direct_mapping[:6]))
    if plan.missing_in_source:
        lines.append("需补角色: " + ", ".join(plan.missing_in_source[:8]))
    if plan.missing_in_target:
        lines.append("目标未识别: " + ", ".join(plan.missing_in_target[:8]))
    if plan.risks:
        lines.append("风险: " + " | ".join(risk.message for risk in plan.risks[:4]))
    if plan.manual_review_items:
        lines.append("人工确认: " + " | ".join(plan.manual_review_items[:3]))
    return lines


def _guess_source_armature(context):
    scene = context.scene
    armature = getattr(scene, "semantic_source_armature", None)
    if armature and armature.type == 'ARMATURE':
        return armature
    armature = context.active_object
    if armature and armature.type == 'ARMATURE':
        return armature
    return None


class OBJECT_OT_debug_infer_semantic(bpy.types.Operator):
    """扫描当前源/目标骨架并输出语义识别结果与计划摘要"""
    bl_idname = "object.debug_infer_semantic"
    bl_label = "调试：识别语义骨架"

    def execute(self, context):
        source_armature = _guess_source_armature(context)
        target_armature = getattr(context.scene, "semantic_target_armature", None)

        if not source_armature or source_armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择源骨架对象，或设置“源骨架”")
            return {'CANCELLED'}

        source_result = _scan_armature(source_armature)
        target_result = _scan_armature(target_armature) if target_armature and target_armature.type == 'ARMATURE' else None

        context.scene.semantic_debug_preview = " | ".join(source_result["preview"])
        context.scene.semantic_debug_count = source_result["recognized_count"]
        context.scene.semantic_debug_canonical = json.dumps(source_result["canonical_dict"], ensure_ascii=False)

        context.scene.semantic_target_preview = ""
        context.scene.semantic_target_count = 0
        context.scene.semantic_plan_preview = ""

        if target_result:
            context.scene.semantic_target_preview = " | ".join(target_result["preview"])
            context.scene.semantic_target_count = target_result["recognized_count"]
            plan = build_conversion_plan(
                source_armature_name=source_armature.name,
                source_recognized_count=source_result["recognized_count"],
                source_dict=source_result["canonical_dict"],
                target_armature_name=target_armature.name,
                target_recognized_count=target_result["recognized_count"],
                target_dict=target_result["canonical_dict"],
            )
        else:
            plan = build_conversion_plan(
                source_armature_name=source_armature.name,
                source_recognized_count=source_result["recognized_count"],
                source_dict=source_result["canonical_dict"],
            )

        context.scene.semantic_plan_preview = " || ".join(_plan_to_summary_lines(plan))
        context.scene.semantic_plan_json = json.dumps(plan.to_dict(), ensure_ascii=False)

        if plan and context.scene.semantic_plan_preview:
            if target_result:
                self.report({'INFO'}, f"源={source_result['recognized_count']} 目标={target_result['recognized_count']}，已生成计划预览")
            else:
                self.report({'INFO'}, f"源={source_result['recognized_count']}，已生成 source-only 计划")
        elif source_result["recognized_count"]:
            self.report({'INFO'}, f"识别到 {source_result['recognized_count']} 根源语义骨")
        else:
            self.report({'WARNING'}, "未识别到已知语义骨")
        return {'FINISHED'}


class OBJECT_OT_fill_mapping_from_semantic(bpy.types.Operator):
    """将源骨架语义识别结果自动填充到现有骨映射字段"""
    bl_idname = "object.fill_mapping_from_semantic"
    bl_label = "从语义结果自动填骨映射"

    def execute(self, context):
        source_armature = _guess_source_armature(context)
        if not source_armature or source_armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择源骨架对象，或设置“源骨架”")
            return {'CANCELLED'}

        result = _scan_armature(source_armature)
        canonical_dict = result["canonical_dict"]

        filled = []
        for role, prop_name in ROLE_TO_SCENE_PROP.items():
            value = canonical_dict.get(role)
            if value and hasattr(context.scene, prop_name):
                setattr(context.scene, prop_name, value)
                filled.append(f"{prop_name}={value}")

        if filled:
            self.report({'INFO'}, f"已自动填充 {len(filled)} 项骨映射")
        else:
            self.report({'WARNING'}, "未找到可自动填充的语义骨映射")
        return {'FINISHED'}
