import bpy
import json
from mathutils import Vector
from .. import bone_map_and_group
from .. import bone_utils
from .. import preset_operator
from ..planning.step2_report import build_step2_execution_report
from ..profiles.registry import get_default_profile
from ..weights.refine_hip import create_hip_blend_zone as _refine_hip_blend_zone
from ..weights.redirects import cleanup_inner_thigh_d_weights as _redirect_cleanup_inner_thigh_d_weights
from ..weights.redirects import absorb_helper_thigh_twist_to_d as _redirect_absorb_helper_thigh_twist_to_d
from ..weights.redirects import enforce_upper_leg_d_mastery as _redirect_enforce_upper_leg_d_mastery
from ..weights.redirects import reinforce_mid_thigh_d_influence as _redirect_reinforce_mid_thigh_d_influence
from ..weights.redirects import restore_upper_thigh_d_influence as _redirect_restore_upper_thigh_d_influence
from ..weights.redirects import transfer_helper_weights as _redirect_transfer_helper_weights
from . import weight_monitor

CONTROL_ONLY_PROPS = {
    "all_parents_bone",
    "center_bone",
    "groove_bone",
    "hip_bone",
    "control_center_bone",
}


def _sync_scene_mapping_to_existing_mmd_names(scene, obj):
    """Refresh scene mapping props when the armature already has MMD names."""
    fixed = []
    for prop_name, new_name in bone_map_and_group.mmd_bone_map.items():
        current = getattr(scene, prop_name, None)
        if obj.pose.bones.get(new_name) and current != new_name:
            setattr(scene, prop_name, new_name)
            fixed.append(f"{prop_name}:{current}->{new_name}")
    control_aliases = {
        "center_bone": "センター",
        "groove_bone": "グルーブ",
        "all_parents_bone": "全ての親",
    }
    for prop_name, new_name in control_aliases.items():
        current = getattr(scene, prop_name, None)
        if obj.pose.bones.get(new_name) and current != new_name:
            setattr(scene, prop_name, new_name)
            fixed.append(f"{prop_name}:{current}->{new_name}")
    return fixed


def _vertex_group_has_weight(obj, group_name, threshold=0.0005):
    vg = obj.vertex_groups.get(group_name)
    if not vg:
        return False
    idx = vg.index
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == idx and g.weight > threshold:
                return True
    return False


def _split_single_leg_template_into_d_chain(armature, mesh_objects):
    """Fallback: split a single FK leg template into 足D/ひざD/足首D bands.

    Some XPS rigs put nearly the whole leg into one group (e.g. 右足) while
    source knee/ankle groups are empty. In that case the normal FK->D copy
    leaves ひざD / 足首D empty. We rebuild the D chain from the preserved
    __CTMMD_SRC__ templates using simple height bands along the leg.
    """
    pairs = (
        ("左足", "左ひざ", "左足首", "足D.L", "ひざD.L", "足首D.L"),
        ("右足", "右ひざ", "右足首", "足D.R", "ひざD.R", "足首D.R"),
    )
    arm_mw = armature.matrix_world
    modified = 0

    for fk_name, knee_name, ankle_name, d_name, knee_d_name, ankle_d_name in pairs:
        fk_bone = armature.data.bones.get(fk_name)
        knee_bone = armature.data.bones.get(knee_name)
        ankle_bone = armature.data.bones.get(ankle_name)
        if not fk_bone or not knee_bone or not ankle_bone:
            continue

        hip_z = (arm_mw @ fk_bone.head_local).z
        knee_z = (arm_mw @ knee_bone.head_local).z
        ankle_z = (arm_mw @ ankle_bone.head_local).z
        leg_top = max(hip_z, knee_z, ankle_z)
        leg_bottom = min(hip_z, knee_z, ankle_z)
        if leg_top - leg_bottom < 0.001:
            continue

        upper_cut = leg_top - (leg_top - leg_bottom) * 0.42
        lower_cut = leg_top - (leg_top - leg_bottom) * 0.78

        for obj in mesh_objects:
            src_template = obj.vertex_groups.get(f"__CTMMD_SRC__{fk_name}")
            vg_d = obj.vertex_groups.get(d_name)
            vg_knee_d = obj.vertex_groups.get(knee_d_name)
            vg_ankle_d = obj.vertex_groups.get(ankle_d_name)
            if not src_template or not vg_d or not vg_knee_d or not vg_ankle_d:
                continue

            # Only fallback when downstream D bones are effectively empty.
            if _vertex_group_has_weight(obj, knee_d_name) or _vertex_group_has_weight(obj, ankle_d_name):
                continue

            src_idx = src_template.index
            mw = obj.matrix_world
            for v in obj.data.vertices:
                src_w = 0.0
                for g in v.groups:
                    if g.group == src_idx and g.weight > 0.001:
                        src_w = g.weight
                        break
                if src_w <= 0.001:
                    continue

                z = (mw @ v.co).z
                if z >= upper_cut:
                    vg_d.add([v.index], src_w, 'REPLACE')
                elif z >= lower_cut:
                    vg_knee_d.add([v.index], src_w, 'REPLACE')
                else:
                    vg_ankle_d.add([v.index], src_w, 'REPLACE')
                modified += 1

    return modified


def _restore_empty_d_groups_from_templates(mesh_objects):
    """Restore D-chain groups directly from preserved source templates.

    If Step 2 ends up with empty ひざD / 足首D groups even though the original
    source groups existed, prefer restoring them directly from
    __CTMMD_SRC__ templates before falling back to geometric splitting.
    """
    restore_pairs = (
        ("__CTMMD_SRC__左ひざ", "ひざD.L"),
        ("__CTMMD_SRC__右ひざ", "ひざD.R"),
        ("__CTMMD_SRC__左足首", "足首D.L"),
        ("__CTMMD_SRC__右足首", "足首D.R"),
        ("__CTMMD_SRC__左足先EX", "足先EX.L"),
        ("__CTMMD_SRC__右足先EX", "足先EX.R"),
    )
    restored = 0
    for obj in mesh_objects:
        for src_name, dst_name in restore_pairs:
            src_vg = obj.vertex_groups.get(src_name)
            dst_vg = obj.vertex_groups.get(dst_name)
            if not src_vg or not dst_vg:
                continue
            if _vertex_group_has_weight(obj, dst_name):
                continue

            src_idx = src_vg.index
            copied_any = False
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == src_idx and g.weight > 0.001:
                        dst_vg.add([v.index], g.weight, 'REPLACE')
                        restored += 1
                        copied_any = True
                        break
            if copied_any:
                # no-op marker for readability when debugging
                pass
    return restored


def _topup_d_joint_groups_from_templates(mesh_objects, ratio_threshold=0.72):
    """Top up knee/ankle D groups when they are much weaker than source templates.

    On some XPS rigs, Step 2 ends with 足D usable but ひざD/足首D too weak.
    We preserve source joint semantics by ensuring D-joint totals are not far
    below the preserved __CTMMD_SRC__ joint templates.
    """
    pairs = (
        ("__CTMMD_SRC__左ひざ", "ひざD.L"),
        ("__CTMMD_SRC__右ひざ", "ひざD.R"),
        ("__CTMMD_SRC__左足首", "足首D.L"),
        ("__CTMMD_SRC__右足首", "足首D.R"),
    )
    modified = 0
    for obj in mesh_objects:
        for src_name, dst_name in pairs:
            src_vg = obj.vertex_groups.get(src_name)
            dst_vg = obj.vertex_groups.get(dst_name)
            if not src_vg or not dst_vg:
                continue

            src_idx = src_vg.index
            dst_idx = dst_vg.index
            src_total = 0.0
            dst_total = 0.0
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == src_idx and g.weight > 0.001:
                        src_total += g.weight
                    elif g.group == dst_idx and g.weight > 0.001:
                        dst_total += g.weight

            if src_total <= 0.001:
                continue
            # 目标组已接近模板强度，不做额外干预
            if dst_total >= src_total * ratio_threshold:
                continue

            for v in obj.data.vertices:
                src_w = 0.0
                dst_w = 0.0
                for g in v.groups:
                    if g.group == src_idx:
                        src_w = g.weight
                    elif g.group == dst_idx:
                        dst_w = g.weight
                if src_w <= 0.001:
                    continue
                target_w = src_w * 0.95
                if dst_w >= target_w - 0.001:
                    continue
                dst_vg.add([v.index], target_w, 'REPLACE')
                modified += 1
    return modified

class OBJECT_OT_rename_to_mmd(bpy.types.Operator):
    """将选定的骨骼重命名为 MMD 格式"""
    bl_idname = "object.rename_to_mmd"
    bl_label = "Rename to MMD"

    mmd_bone_map = bone_map_and_group.mmd_bone_map  # 使用导入的bone_map模块

    @staticmethod
    def _sync_stale_mapping(scene, obj, prop_name, bone_name, new_name):
        """Handle stale scene mappings after a previous partial rename.

        Example: scene still stores `root hips`, but the current armature
        already contains `下半身`. In that case we refresh the property instead
        of emitting a misleading "bone not found" warning.
        """
        if obj.pose.bones.get(new_name):
            setattr(scene, prop_name, new_name)
            return True
        return False

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "没有选择骨架对象")
            return {'CANCELLED'}

        scene = context.scene
        _sync_scene_mapping_to_existing_mmd_names(scene, obj)
        # 检查选择框里是否有骨骼设置
        has_bone_set = False
        for prop_name in preset_operator.get_bones_list():  # 从operations.py中获取骨骼属性名称列表
            if getattr(scene, prop_name, None):
                has_bone_set = True
                break
        if not has_bone_set:
            self.report({'WARNING'}, "未设置骨骼")
            return {'CANCELLED'}

        assigned = {}
        duplicate_skipped = []
        for prop_name in preset_operator.get_bones_list():
            bone_name = getattr(scene, prop_name, None)
            if not bone_name:
                continue
            assigned.setdefault(bone_name, []).append(prop_name)

        stale_fixed = []
        stale_missing = []
        for prop_name, new_name in self.mmd_bone_map.items():
            bone_name = getattr(scene, prop_name, None)
            if bone_name:
                dup_props = assigned.get(bone_name, [])
                if len(dup_props) > 1 and prop_name in CONTROL_ONLY_PROPS:
                    duplicate_skipped.append(f"{prop_name}:{bone_name}")
                    continue
                bone = obj.pose.bones.get(bone_name)
                if bone:
                    # 检查骨骼是否已经重命名为 MMD 格式名称
                    if bone.name != new_name:
                        old_name = bone.name
                        bone.name = new_name
                        # 同步所有网格对象的顶点组名称，防止权重断链
                        for mesh_obj in context.scene.objects:
                            if mesh_obj.type == 'MESH':
                                vg = mesh_obj.vertex_groups.get(old_name)
                                if vg:
                                    vg.name = new_name
                        # 更新场景中的骨骼属性值
                        setattr(scene, prop_name, new_name)
                    else:
                        self.report({'INFO'}, f"骨骼 '{bone_name}' 已经重命名为 {new_name}")
                else:
                    if self._sync_stale_mapping(scene, obj, prop_name, bone_name, new_name):
                        stale_fixed.append(f"{bone_name}->{new_name}")
                    else:
                        stale_missing.append(f"{bone_name}->{new_name}")

        if stale_fixed:
            preview = " / ".join(stale_fixed[:4])
            self.report({'INFO'}, f"已自动同步过期映射: {preview}")
        if stale_missing:
            preview = " / ".join(stale_missing[:4])
            self.report({'WARNING'}, f"部分映射已过期，请先重新扫描并自动填骨映射: {preview}")
        if duplicate_skipped:
            preview = " / ".join(duplicate_skipped[:4])
            self.report({'INFO'}, f"已跳过控制骨重名映射: {preview}")

        # 打开骨骼名称显示
        bpy.context.object.data.show_names = True

        return {'FINISHED'}

    def rename_finger_bone(self, context, obj, scene, base_finger_name, segment):
        for side in ["left", "right"]:
            prop_name = f"{side}_{base_finger_name}_{segment}"
            if prop_name in self.mmd_bone_map:
                new_name = self.mmd_bone_map.get(prop_name)
                bone_name = getattr(scene, prop_name, None)
                if bone_name:
                    bone = obj.pose.bones.get(bone_name)
                    if bone:
                        # Check if the bone has already been renamed to the MMD format name
                        if bone.name != new_name:
                            bone.name = new_name
                            # Update the bone property value in the scene
                            setattr(scene, prop_name, new_name)
                        else:
                            self.report({'INFO'}, f"Bone '{bone_name}' is already renamed to {new_name}")
                    else:
                        self.report({'WARNING'}, f"Bone '{bone_name}' not found for renaming to {new_name}")

class OBJECT_OT_complete_missing_bones(bpy.types.Operator):
    """补充缺失的 MMD 格式骨骼"""
    bl_idname = "object.complete_missing_bones"
    bl_label = "Complete Missing Bones"

    def execute(self, context):
        scene = context.scene
        obj = context.active_object
        preferred = getattr(scene, "semantic_source_armature", None)
        if preferred and preferred.type == 'ARMATURE' and preferred.name in scene.objects:
            if obj != preferred:
                bpy.ops.object.mode_set(mode='OBJECT') if context.object and context.object.mode != 'OBJECT' else None
                for o in context.view_layer.objects:
                    o.select_set(False)
                preferred.select_set(True)
                context.view_layer.objects.active = preferred
                obj = preferred
                self.report({'INFO'}, f"已自动切换到源骨架: {obj.name}")
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "没有选择骨架")
            return {'CANCELLED'}

        _sync_scene_mapping_to_existing_mmd_names(context.scene, obj)

        # 确保当前处于编辑模式 (EDIT mode)
        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')
        
        edit_bones = obj.data.edit_bones
        # 获取需要修改的骨骼
        left_foot_bone = edit_bones.get("左足")
        right_foot_bone = edit_bones.get("右足")
        upper_body_bone = edit_bones.get("上半身")
        lower_body_bone = edit_bones.get("下半身")
        upper_body_2_bone = edit_bones.get("上半身2")
        left_shoulder_bone = edit_bones.get("左肩")
        right_shoulder_bone = edit_bones.get("右肩")
        left_arm_bone = edit_bones.get("左腕")
        right_arm_bone = edit_bones.get("右腕")
        left_elbow_bone = edit_bones.get("左ひじ")
        right_elbow_bone = edit_bones.get("右ひじ")
        left_wrist_bone = edit_bones.get("左手首")
        right_wrist_bone = edit_bones.get("右手首")
        # 兼容两种命名：标准 目.L/目.R 和 日文 左目/右目
        left_eye_bone = edit_bones.get("目.L") or edit_bones.get("左目")
        right_eye_bone = edit_bones.get("目.R") or edit_bones.get("右目")
        head_bone = edit_bones.get("頭")

        # 清除 左足 和 右足 骨骼的父级
        if left_foot_bone:
            left_foot_bone.use_connect = False
            left_foot_bone.parent = None
        if right_foot_bone:
            right_foot_bone.use_connect = False
            right_foot_bone.parent = None
        # 清除 上半身 骨骼的父级
        if upper_body_bone and upper_body_bone.parent:
            upper_body_bone.use_connect = False
            upper_body_bone.parent = None
        # 清除 下半身 骨骼的父级
        if lower_body_bone and lower_body_bone.parent:
            lower_body_bone.use_connect = False
            lower_body_bone.parent = None
        # 确认上半身骨骼存在
        if not upper_body_bone:
            self.report({'ERROR'}, "上半身骨骼不存在")
            return {'CANCELLED'}
        # 获取 上半身 骨骼的坐标
        upper_body_head = upper_body_bone.head.copy()
        upper_body_tail = upper_body_bone.tail.copy()

        # 计算 上半身1 的位置
        # head = 上半身的实际 tail（脊椎中段顶部），tail = spine_upper 下三分之一处
        upper1_head = upper_body_tail.copy()
        if upper_body_2_bone:
            ub2_head_z = upper_body_2_bone.head.z
            ub2_tail_z = upper_body_2_bone.tail.z
            step = (ub2_tail_z - ub2_head_z) / 3.0 if ub2_tail_z > ub2_head_z else 0.05
            upper1_tail = Vector((0, upper_body_2_bone.head.y, ub2_head_z + step))
        else:
            upper1_tail = upper1_head + Vector((0, 0, 0.05))

        # 计算 腰キャンセル 的位置（与足的头部相同）
        if left_foot_bone:
            left_koshi_head = left_foot_bone.head.copy()
        else:
            left_koshi_head = Vector((-0.1, 0, upper_body_head.z - 0.15))
        if right_foot_bone:
            right_koshi_head = right_foot_bone.head.copy()
        else:
            right_koshi_head = Vector((0.1, 0, upper_body_head.z - 0.15))

        # 计算脚尖（足先）位置：优先使用真实骨骼，回退到偏移量
        left_toe_ex  = edit_bones.get("左足先EX") or edit_bones.get("左つま先")
        right_toe_ex = edit_bones.get("右足先EX") or edit_bones.get("右つま先")
        if left_toe_ex:
            left_ankle_tail = left_toe_ex.head.copy()
        else:
            left_ankle_tail = Vector((edit_bones["左足首"].head.x, edit_bones["左足首"].head.y - 0.08, 0))
        if right_toe_ex:
            right_ankle_tail = right_toe_ex.head.copy()
        else:
            right_ankle_tail = Vector((edit_bones["右足首"].head.x, edit_bones["右足首"].head.y - 0.08, 0))

        # 计算 両目 的位置（两眼之间）
        if left_eye_bone and right_eye_bone:
            ryome_head = (left_eye_bone.head + right_eye_bone.head) / 2
            ryome_head = Vector((0, ryome_head.y, ryome_head.z))
        elif head_bone:
            ryome_head = head_bone.head + Vector((0, -0.1, 0.1))
        else:
            ryome_head = Vector((0, upper_body_head.y, upper_body_head.z + 0.5))
        ryome_tail = ryome_head + Vector((0, -0.1, 0))

        # 基于角色实际骨骼高度计算控制骨位置
        waist_z    = upper_body_head.z        # 腰（上半身起点）的 Z 高度
        center_z   = waist_z * 0.72           # センター/グルーブ：腰高度的 72%（参考 MMD 标准比例）
        bone_unit  = waist_z * 0.05           # 控制骨短边长度（腰高度的 5%）
        root_unit  = waist_z * 0.08           # 全ての親 的长度

        # 定义基本骨骼的属性（有序字典，按父子关系排列）
        bone_properties = {
            "全ての親": {"head": Vector((0, 0, 0)), "tail": Vector((0, 0, root_unit)), "parent": None, "use_deform": False, "use_connect": False},
            "センター": {"head": Vector((0, 0, center_z)), "tail": Vector((0, 0, center_z + bone_unit)), "parent": "全ての親", "use_deform": False, "use_connect": False},
            "グルーブ": {"head": Vector((0, 0, center_z)), "tail": Vector((0, 0, center_z + bone_unit)), "parent": "センター", "use_deform": False, "use_connect": False},
            "腰": {"head": Vector((0, upper_body_head.y + 0.1, upper_body_head.z - 0.12)), "tail": Vector((0, upper_body_head.y, upper_body_head.z)),
                "parent": "グルーブ", "use_deform": False, "use_connect": False},
            # 上半身：保留实际骨骼位置（spine_middle），只重置父级
            "上半身": {"head": upper_body_head, "tail": upper_body_tail, "parent": "腰", "use_connect": False},
            # 上半身1：从 上半身 tail 到 spine_upper 下三分之一处，朝上的桥接骨骼（deform=True 与 MMD 参考一致）
            "上半身1": {"head": upper1_head, "tail": upper1_tail, "parent": "上半身", "use_deform": True, "use_connect": False},
            # 上半身2：从 上半身1 tail 到 spine_upper 顶部，连接成完整链
            "上半身2": {
                "head": upper1_tail,
                "tail": Vector((0, upper_body_2_bone.tail.y, upper_body_2_bone.tail.z)) if upper_body_2_bone else upper1_tail + Vector((0, 0, 0.15)),
                "parent": "上半身1", "use_connect": False},

            # 下半身
            "下半身": {"head": Vector((0, upper_body_head.y, upper_body_head.z)), "tail": Vector((0, upper_body_head.y, upper_body_head.z - 0.15)), "parent": "腰", "use_connect": False},
            "腰キャンセル.L": {"head": left_koshi_head, "tail": left_koshi_head + Vector((0, 0, -0.05)), "parent": "下半身", "use_deform": False, "use_connect": False},
            "腰キャンセル.R": {"head": right_koshi_head, "tail": right_koshi_head + Vector((0, 0, -0.05)), "parent": "下半身", "use_deform": False, "use_connect": False},

            # 腿部（足→腰キャンセル）
            "左足": {"head": edit_bones["左足"].head, "tail": edit_bones["左ひざ"].head, "parent": "腰キャンセル.L", "use_connect": False},
            "右足": {"head": edit_bones["右足"].head, "tail": edit_bones["右ひざ"].head, "parent": "腰キャンセル.R", "use_connect": False},
            "左ひざ": {"head": edit_bones["左ひざ"].head, "tail": edit_bones["左足首"].head, "parent": "左足", "use_connect": False},
            "右ひざ": {"head": edit_bones["右ひざ"].head, "tail": edit_bones["右足首"].head, "parent": "右足", "use_connect": False},
            "左足首": {"head": edit_bones["左足首"].head, "tail": left_ankle_tail, "parent": "左ひざ", "use_connect": False},
            "右足首": {"head": edit_bones["右足首"].head, "tail": right_ankle_tail, "parent": "右ひざ", "use_connect": False},

            # D 系变形骨骼：沿用原腿骨方向和长度。
            # 之前用固定 0.082 的短 stub，会导致“有权重但旋转位移极小”，
            # 大腿视觉上像是没被足D真正控制到。
            "足D.L": {"head": edit_bones["左足"].head.copy(), "tail": edit_bones["左ひざ"].head.copy(), "parent": "腰キャンセル.L", "use_deform": True, "use_connect": False},
            "ひざD.L": {"head": edit_bones["左ひざ"].head.copy(), "tail": edit_bones["左足首"].head.copy(), "parent": "足D.L", "use_deform": True, "use_connect": False},
            "足首D.L": {"head": edit_bones["左足首"].head.copy(), "tail": left_ankle_tail.copy(), "parent": "ひざD.L", "use_deform": True, "use_connect": False},
            "足先EX.L": {"head": left_ankle_tail, "tail": left_ankle_tail + Vector((0, -0.082, 0)), "parent": "足首D.L", "use_deform": True, "use_connect": False},
            "足D.R": {"head": edit_bones["右足"].head.copy(), "tail": edit_bones["右ひざ"].head.copy(), "parent": "腰キャンセル.R", "use_deform": True, "use_connect": False},
            "ひざD.R": {"head": edit_bones["右ひざ"].head.copy(), "tail": edit_bones["右足首"].head.copy(), "parent": "足D.R", "use_deform": True, "use_connect": False},
            "足首D.R": {"head": edit_bones["右足首"].head.copy(), "tail": right_ankle_tail.copy(), "parent": "ひざD.R", "use_deform": True, "use_connect": False},
            "足先EX.R": {"head": right_ankle_tail, "tail": right_ankle_tail + Vector((0, -0.082, 0)), "parent": "足首D.R", "use_deform": True, "use_connect": False},

            # 上肢骨骼链
            "左肩": {
                "head": left_shoulder_bone.head if left_shoulder_bone else Vector((-0.08, upper_body_head.y, upper_body_head.z + 0.16)),
                "tail": (left_arm_bone.head if left_arm_bone else (left_shoulder_bone.head + Vector((-0.12, 0, 0)) if left_shoulder_bone else Vector((-0.20, upper_body_head.y, upper_body_head.z + 0.16)))),
                "parent": left_shoulder_bone.parent.name if left_shoulder_bone and left_shoulder_bone.parent else "上半身2",
                "use_connect": False
            },
            "左腕": {
                "head": left_arm_bone.head if left_arm_bone else (left_shoulder_bone.tail if left_shoulder_bone else Vector((-0.20, upper_body_head.y, upper_body_head.z + 0.16))),
                "tail": left_elbow_bone.head if left_elbow_bone else (left_arm_bone.tail if left_arm_bone else Vector((-0.32, upper_body_head.y, upper_body_head.z + 0.12))),
                "parent": "左肩",
                "use_connect": False
            },
            "左ひじ": {
                "head": left_elbow_bone.head if left_elbow_bone else (left_arm_bone.tail if left_arm_bone else Vector((-0.32, upper_body_head.y, upper_body_head.z + 0.12))),
                "tail": left_wrist_bone.head if left_wrist_bone else (left_elbow_bone.tail if left_elbow_bone else Vector((-0.42, upper_body_head.y, upper_body_head.z + 0.10))),
                "parent": "左腕",
                "use_connect": False
            },
            "右肩": {
                "head": right_shoulder_bone.head if right_shoulder_bone else Vector((0.08, upper_body_head.y, upper_body_head.z + 0.16)),
                "tail": (right_arm_bone.head if right_arm_bone else (right_shoulder_bone.head + Vector((0.12, 0, 0)) if right_shoulder_bone else Vector((0.20, upper_body_head.y, upper_body_head.z + 0.16)))),
                "parent": right_shoulder_bone.parent.name if right_shoulder_bone and right_shoulder_bone.parent else "上半身2",
                "use_connect": False
            },
            "右腕": {
                "head": right_arm_bone.head if right_arm_bone else (right_shoulder_bone.tail if right_shoulder_bone else Vector((0.20, upper_body_head.y, upper_body_head.z + 0.16))),
                "tail": right_elbow_bone.head if right_elbow_bone else (right_arm_bone.tail if right_arm_bone else Vector((0.32, upper_body_head.y, upper_body_head.z + 0.12))),
                "parent": "右肩",
                "use_connect": False
            },
            "右ひじ": {
                "head": right_elbow_bone.head if right_elbow_bone else (right_arm_bone.tail if right_arm_bone else Vector((0.32, upper_body_head.y, upper_body_head.z + 0.12))),
                "tail": right_wrist_bone.head if right_wrist_bone else (right_elbow_bone.tail if right_elbow_bone else Vector((0.42, upper_body_head.y, upper_body_head.z + 0.10))),
                "parent": "右腕",
                "use_connect": False
            },

            # 両目（双眼父骨）
            "両目": {"head": ryome_head, "tail": ryome_tail, "parent": "頭" if edit_bones.get("頭") else None, "use_deform": False, "use_connect": False},
        }

        # 按顺序检查并创建或更新骨骼
        for bone_name, properties in bone_properties.items():
            bone_utils.create_or_update_bone(
                edit_bones, bone_name,
                properties["head"], properties["tail"],
                properties.get("use_connect", False),
                properties["parent"],
                properties.get("use_deform", True)
            )

        # 调用函数设置 roll 值
        bone_utils.set_roll_values(edit_bones, bone_utils.DEFAULT_ROLL_VALUES)

        # 切回 Object 模式，执行权重修复
        bpy.ops.object.mode_set(mode='OBJECT')
        _sync_scene_mapping_to_existing_mmd_names(context.scene, obj)
        self._setup_new_bone_weights(context, obj)
        _sync_scene_mapping_to_existing_mmd_names(context.scene, obj)

        weight_monitor.auto_check_after_step(context, obj, "step_2", "补全缺失骨骼")
        return {'FINISHED'}

    def _setup_new_bone_weights(self, context, armature):
        """
        补全缺失骨骼后的权重修复：
        1. 将腿部常规骨骼（左足/左ひざ/左足首）权重复制到 D 系骨骼，并将常规腿骨设为非变形骨
        2. 将 上半身2 在 上半身1 区间内的权重按高度比例分配给 上半身1
        """
        # ── 1. D 系腿骨权重 ──────────────────────────────────────────────
        # 常规腿骨 → D 系骨骼 的映射（左右对称）
        leg_copy_map = [
            ("左足",    "足D.L"),
            ("左ひざ",  "ひざD.L"),
            ("左足首",  "足首D.L"),
            ("左足先EX","足先EX.L"),
            ("右足",    "足D.R"),
            ("右ひざ",  "ひざD.R"),
            ("右足首",  "足首D.R"),
            ("右足先EX","足先EX.R"),
        ]
        # 仅把“足”本体降为 IK-only，保留 ひざ/足首 的 FK 变形能力。
        # 参考模型中 FK+D 是并存的：膝/踝仍可直接参与变形。
        # 之前把 ひざ/足首 也设为非变形，会导致“膝盖控制不到”的体感问题。
        leg_ik_only = {"左足", "右足"}

        mesh_objects = [
            o for o in context.scene.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == armature for m in o.modifiers)
        ]

        copied_pairs = 0
        for src_name, dst_name in leg_copy_map:
            for obj in mesh_objects:
                src_vg = obj.vertex_groups.get(src_name)
                if not src_vg:
                    continue
                template_name = f"__CTMMD_SRC__{src_name}"
                template_vg = obj.vertex_groups.get(template_name)
                if not template_vg:
                    template_vg = obj.vertex_groups.new(name=template_name)
                dst_vg = obj.vertex_groups.get(dst_name)
                if not dst_vg:
                    dst_vg = obj.vertex_groups.new(name=dst_name)
                for v in obj.data.vertices:
                    for g in v.groups:
                        if g.group == src_vg.index and g.weight > 0:
                            template_vg.add([v.index], g.weight, 'REPLACE')
                            dst_vg.add([v.index], g.weight, 'REPLACE')
                            break
                # 仅清零“足”FK源权重，避免大腿/髋部被足骨双控；
                # 膝/踝保留 FK 权重，与参考模型一致（FK+D 并存）。
                if src_name in {"左足", "右足"}:
                    src_vg.remove([v.index for v in obj.data.vertices])
                copied_pairs += 1

        # 将常规腿骨设为非变形骨（PMX 中它们只做 IK 控制）
        for bname in leg_ik_only:
            bone = armature.data.bones.get(bname)
            if bone:
                bone.use_deform = False

        # ── 1.2. 优先从原始模板恢复空的 D 系腿链 ───────────────────────────
        d_template_restored = _restore_empty_d_groups_from_templates(mesh_objects)

        # ── 1.25. 单一腿组兜底拆分 ────────────────────────────────────────
        # 某些 XPS 模型只有“左足/右足”整条腿权重，没有独立的膝盖/脚踝组。
        # 先从保留下来的原始腿模板里按高度拆出 D 系腿链，避免 ひざD/足首D 为空。
        d_chain_rebuilt = _split_single_leg_template_into_d_chain(armature, mesh_objects)
        d_joint_topped = _topup_d_joint_groups_from_templates(mesh_objects)
        helper_absorbed = _redirect_absorb_helper_thigh_twist_to_d(mesh_objects)

        # ── 1.5. 下半身基础权重初始化 ─────────────────────────────────────
        # 某些 XPS 模型没有直接对应到“下半身”的顶点组，骨盆/裆部权重仍停留在
        # pelvis / xtra08 / xtra08opp 等 helper 上。若此时不先建立下半身，
        # 后续的髋部渐变和腿根足D补回都会整步跳过。
        lower_body_seed_redirects = {}
        profile = get_default_profile()
        for src_name, redirect in profile.helper_redirects.items():
            if isinstance(redirect, dict):
                target_name = redirect.get("target")
            else:
                target_name = redirect
            if target_name == "下半身":
                lower_body_seed_redirects[src_name] = redirect

        lower_body_seeded = 0
        lower_body_seed_details = []
        if lower_body_seed_redirects:
            needs_seed = any(
                not _vertex_group_has_weight(obj, "下半身")
                for obj in mesh_objects
            )
            if needs_seed:
                lower_body_seeded, lower_body_seed_details = _redirect_transfer_helper_weights(
                    mesh_objects, lower_body_seed_redirects
                )

        # ── D 系骨骼设置 mmd_tools 付与（additional_transform）──────────────
        # 通过 mmd_bone.additional_transform_bone + FnBone.apply_additional_transformation
        # 生成标准的 shadow/dummy 骨骼和约束，PMX 导出时会正确转换为付与関係
        d_series_follow = [
            ("足D.L",   "左足"),
            ("ひざD.L", "左ひざ"),
            ("足首D.L", "左足首"),
            ("足D.R",   "右足"),
            ("ひざD.R", "右ひざ"),
            ("足首D.R", "右足首"),
        ]
        d_follow_applied = False
        try:
            from mmd_tools.core.bone import FnBone
            needs_apply = False
            for d_name, src_name in d_series_follow:
                pb = armature.pose.bones.get(d_name)
                if not pb:
                    continue
                mb = pb.mmd_bone
                if mb.additional_transform_bone != src_name:
                    mb.additional_transform_bone = src_name
                    mb.has_additional_rotation = True
                    mb.additional_transform_influence = 1.0
                    needs_apply = True
            if needs_apply:
                bpy.ops.object.mode_set(mode='POSE')
                FnBone.apply_additional_transformation(armature)
                bpy.ops.object.mode_set(mode='OBJECT')
                d_follow_applied = True
        except Exception as e:
            self.report({'WARNING'}, f"D系付与设置失败（需要mmd_tools）: {e}")

        # ── 2. 上半身1 权重重分配 ─────────────────────────────────────────
        ub1_bone = armature.data.bones.get("上半身1")
        ub2_bone = armature.data.bones.get("上半身2")
        spine_redistributed = False
        if not ub1_bone or not ub2_bone:
            self.report({'INFO'}, "D系骨骼权重已复制（上半身1/2不存在，跳过脊柱重分配）")
            report = build_step2_execution_report(
                copied_pairs=copied_pairs,
                lower_body_seeded=lower_body_seeded,
                lower_body_seed_details=lower_body_seed_details,
                d_follow_applied=d_follow_applied,
                spine_redistributed=spine_redistributed,
                hip_modified=0,
                thigh_root_restored=0,
                mid_thigh_reinforced=0,
                normalized=0,
            )
            armature["step2_execution_report"] = json.dumps(report.to_dict(), ensure_ascii=False)
            context.scene["step2_execution_report"] = report.summary
            return

        mw = armature.matrix_world
        ub1_head_z = (mw @ ub1_bone.head_local).z
        ub1_tail_z = (mw @ ub1_bone.tail_local).z  # = 上半身2.head.z
        span = ub1_tail_z - ub1_head_z
        if span <= 0:
            self.report({'INFO'}, "D系骨骼权重已复制（上半身1 高度为0，跳过重分配）")
            report = build_step2_execution_report(
                copied_pairs=copied_pairs,
                lower_body_seeded=lower_body_seeded,
                lower_body_seed_details=lower_body_seed_details,
                d_follow_applied=d_follow_applied,
                spine_redistributed=spine_redistributed,
                hip_modified=0,
                thigh_root_restored=0,
                mid_thigh_reinforced=0,
                normalized=0,
            )
            armature["step2_execution_report"] = json.dumps(report.to_dict(), ensure_ascii=False)
            context.scene["step2_execution_report"] = report.summary
            return

        for obj in mesh_objects:
            vg2 = obj.vertex_groups.get("上半身2")
            if not vg2:
                continue
            vg1 = obj.vertex_groups.get("上半身1")
            if not vg1:
                vg1 = obj.vertex_groups.new(name="上半身1")

            for v in obj.data.vertices:
                w2 = 0.0
                for g in v.groups:
                    if g.group == vg2.index:
                        w2 = g.weight
                        break
                if w2 <= 0:
                    continue

                world_z = (obj.matrix_world @ v.co).z
                # 在 上半身1 Z 范围内的顶点才重分配
                if world_z >= ub1_tail_z:
                    continue  # 完全在 上半身2 区域，不动

                # ratio_to_ub1：越靠近 ub1_head_z 越多给 上半身1
                t = max(0.0, min(1.0, (world_z - ub1_head_z) / span))
                ratio_ub2 = t          # 靠近 ub2 侧保留给 上半身2
                ratio_ub1 = 1.0 - t   # 靠近 ub1 侧分给 上半身1

                if ratio_ub2 > 0:
                    vg2.add([v.index], w2 * ratio_ub2, 'REPLACE')
                else:
                    vg2.remove([v.index])

                if ratio_ub1 > 0:
                    cur_w1 = 0.0
                    for g in v.groups:
                        if g.group == vg1.index:
                            cur_w1 = g.weight
                            break
                    vg1.add([v.index], min(1.0, cur_w1 + w2 * ratio_ub1), 'REPLACE')
        spine_redistributed = True

        # ── 3. 髋部渐变过渡区 ───────────────────────────────────────────────
        # XPS 权重是二值的（足D在髋部全是1.0），没有腰腿过渡混合，
        # 会导致骨骼运动时出现硬切割（裂口感）。
        # 在 足D.L/R 权重范围顶部做渐变，将边界处的足D权重逐步转移给下半身。
        hip_modified = _create_hip_blend_zone(armature, mesh_objects, transition_height=1.5)
        thigh_root_restored = _restore_upper_thigh_d_influence(armature, mesh_objects)
        mid_thigh_reinforced = _redirect_reinforce_mid_thigh_d_influence(armature, mesh_objects)
        upper_leg_hard_fixed = _redirect_enforce_upper_leg_d_mastery(armature, mesh_objects)
        knee_reinforced = _reinforce_knee_d_influence(armature, mesh_objects)
        template_rescued = _rescue_leg_template_residuals(armature, mesh_objects)
        normalized = _normalize_deform_weights(armature, mesh_objects)
        right_fk_count, right_fk_sum = _vertex_group_nonzero_stats(mesh_objects, "右足")
        right_d_count, right_d_sum = _vertex_group_nonzero_stats(mesh_objects, "足D.R")
        left_fk_count, left_fk_sum = _vertex_group_nonzero_stats(mesh_objects, "左足")
        left_d_count, left_d_sum = _vertex_group_nonzero_stats(mesh_objects, "足D.L")
        extra_reinforce = 0
        if right_fk_sum > 1.0 and right_d_sum < right_fk_sum * 0.72:
            # 兜底：右腿仍明显偏向 FK 时，再补一轮中段强化并重新归一化。
            extra_reinforce = _redirect_reinforce_mid_thigh_d_influence(armature, mesh_objects)
            if extra_reinforce > 0:
                normalized += _normalize_deform_weights(armature, mesh_objects)
                right_fk_count, right_fk_sum = _vertex_group_nonzero_stats(mesh_objects, "右足")
                right_d_count, right_d_sum = _vertex_group_nonzero_stats(mesh_objects, "足D.R")
                left_fk_count, left_fk_sum = _vertex_group_nonzero_stats(mesh_objects, "左足")
                left_d_count, left_d_sum = _vertex_group_nonzero_stats(mesh_objects, "足D.L")
        leg_control_summary = (
            f"右足={right_fk_count}/{right_fk_sum:.1f} vs 足D.R={right_d_count}/{right_d_sum:.1f} | "
            f"左足={left_fk_count}/{left_fk_sum:.1f} vs 足D.L={left_d_count}/{left_d_sum:.1f}"
        )
        context.scene["step2_leg_control_report"] = leg_control_summary
        if hip_modified > 0 or thigh_root_restored > 0 or d_chain_rebuilt > 0 or d_template_restored > 0:
            parts = ["补全完成：D系腿骨已复制，上半身1已分配"]
            if d_template_restored > 0:
                parts.append(f"D系模板已恢复（{d_template_restored}顶点）")
            if d_chain_rebuilt > 0:
                parts.append(f"D系腿链已重建（{d_chain_rebuilt}顶点）")
            if d_joint_topped > 0:
                parts.append(f"膝/踝D已回填（{d_joint_topped}顶点）")
            if helper_absorbed > 0:
                parts.append(f"helper腿扭转已并入足D（{helper_absorbed}顶点）")
            if lower_body_seeded > 0:
                preview = " / ".join(lower_body_seed_details[:3])
                parts.append(f"下半身已初始化（{lower_body_seeded}顶点）")
                if preview:
                    parts.append(preview)
            if hip_modified > 0:
                parts.append(f"髋部渐变区已创建（{hip_modified}顶点）")
            if thigh_root_restored > 0:
                parts.append(f"腿根足D已补回（{thigh_root_restored}顶点）")
            if mid_thigh_reinforced > 0:
                parts.append(f"大腿控制带已加强（{mid_thigh_reinforced}顶点）")
            if upper_leg_hard_fixed > 0:
                parts.append(f"腿根硬修复已执行（{upper_leg_hard_fixed}顶点）")
            if knee_reinforced > 0:
                parts.append(f"膝盖D已加强（{knee_reinforced}顶点）")
            if template_rescued > 0:
                parts.append(f"模板残留已回收（{template_rescued}顶点）")
            if extra_reinforce > 0:
                parts.append(f"右腿兜底补偿已执行（{extra_reinforce}顶点）")
            parts.append(f"腿控摘要：{leg_control_summary}")
            self.report({'INFO'}, "，".join(parts))
        else:
            parts = ["补全骨骼权重完成：D系腿骨已复制，上半身1已分配"]
            if d_template_restored > 0:
                parts.append(f"D系模板已恢复（{d_template_restored}顶点）")
            if d_chain_rebuilt > 0:
                parts.append(f"D系腿链已重建（{d_chain_rebuilt}顶点）")
            if d_joint_topped > 0:
                parts.append(f"膝/踝D已回填（{d_joint_topped}顶点）")
            if helper_absorbed > 0:
                parts.append(f"helper腿扭转已并入足D（{helper_absorbed}顶点）")
            if lower_body_seeded > 0:
                parts.append(f"下半身已初始化（{lower_body_seeded}顶点）")
            if mid_thigh_reinforced > 0:
                parts.append(f"大腿控制带已加强（{mid_thigh_reinforced}顶点）")
            if upper_leg_hard_fixed > 0:
                parts.append(f"腿根硬修复已执行（{upper_leg_hard_fixed}顶点）")
            if knee_reinforced > 0:
                parts.append(f"膝盖D已加强（{knee_reinforced}顶点）")
            if template_rescued > 0:
                parts.append(f"模板残留已回收（{template_rescued}顶点）")
            if extra_reinforce > 0:
                parts.append(f"右腿兜底补偿已执行（{extra_reinforce}顶点）")
            parts.append(f"腿控摘要：{leg_control_summary}")
            self.report({'INFO'}, "，".join(parts))

        report = build_step2_execution_report(
            copied_pairs=copied_pairs,
            lower_body_seeded=lower_body_seeded,
            lower_body_seed_details=lower_body_seed_details,
            d_follow_applied=d_follow_applied,
            spine_redistributed=spine_redistributed,
            hip_modified=hip_modified,
            thigh_root_restored=thigh_root_restored,
            mid_thigh_reinforced=mid_thigh_reinforced,
            normalized=normalized,
        )
        armature["step2_execution_report"] = json.dumps(report.to_dict(), ensure_ascii=False)
        context.scene["step2_execution_report"] = report.summary


# ─────────────────────────────────────────────────────────────────────────────
# 共享工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _create_hip_blend_zone(armature, mesh_objects, transition_height=1.5):
    return _refine_hip_blend_zone(armature, mesh_objects, transition_height)


def _normalize_deform_weights(armature, mesh_objects):
    """将每个顶点的所有变形骨权重双向归一化到1.0。
    XPS/DAZ 等来源模型的权重叠加常超过1.0（过度变形）；
    cleanup 删除下半身后可能留下 <1.0 的欠权重（变形不足），一并修正。
    仅处理总权重 > 0.3 的顶点（0~0.3 视为边界/未绑定顶点，不强制归一化）。"""
    deform_set = {b.name for b in armature.data.bones if b.use_deform}
    normalized = 0
    for obj in mesh_objects:
        vg_idx_map = {vg.index: vg for vg in obj.vertex_groups if vg.name in deform_set}
        if not vg_idx_map:
            continue
        for v in obj.data.vertices:
            total = sum(g.weight for g in v.groups if g.group in vg_idx_map and g.weight > 0)
            if total < 0.3 or abs(total - 1.0) <= 0.001:
                continue
            for g in v.groups:
                if g.group in vg_idx_map and g.weight > 0:
                    vg_idx_map[g.group].add([v.index], g.weight / total, 'REPLACE')
            normalized += 1
    return normalized


def _vertex_group_nonzero_stats(mesh_objects, vg_name, threshold=0.001):
    """Return (vertex_count, weight_sum) for a vertex group across all meshes."""
    count = 0
    total = 0.0
    for obj in mesh_objects:
        vg = obj.vertex_groups.get(vg_name)
        if not vg:
            continue
        idx = vg.index
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == idx and g.weight > threshold:
                    count += 1
                    total += g.weight
                    break
    return count, total


def _reinforce_knee_d_influence(armature, mesh_objects):
    """Strengthen ひざD influence in knee band to improve knee control feel.

    In some XPS rigs, knee-region vertices are dominated by 足D / FK-knee,
    so rotating ひざD appears too weak. This pass transfers part of that
    influence into ひざD in a side-aware knee band.
    """
    pairs = (
        ("左ひざ", "足D.L", "ひざD.L", "下半身"),
        ("右ひざ", "足D.R", "ひざD.R", "下半身"),
    )
    arm_mw = armature.matrix_world
    modified = 0

    left_knee = armature.data.bones.get("左ひざ")
    right_knee = armature.data.bones.get("右ひざ")
    center_x = 0.0
    if left_knee and right_knee:
        center_x = ((arm_mw @ left_knee.head_local).x + (arm_mw @ right_knee.head_local).x) * 0.5

    for fk_knee_name, d_parent_name, d_knee_name, lower_name in pairs:
        fk_knee_bone = armature.data.bones.get(fk_knee_name)
        if not fk_knee_bone:
            continue

        knee_h = arm_mw @ fk_knee_bone.head_local
        knee_t = arm_mw @ fk_knee_bone.tail_local
        z_top = max(knee_h.z, knee_t.z)
        z_bottom = min(knee_h.z, knee_t.z)
        seg_len = max(0.001, z_top - z_bottom)
        # 覆盖膝盖上下邻近带，避免只命中极窄区域
        band_top = z_top + seg_len * 0.22
        band_bottom = z_bottom - seg_len * 0.18
        side_sign = -1.0 if knee_h.x < 0 else 1.0
        center_exclude = max(0.008, abs(knee_h.x) * 0.06)
        side_extent = max(center_exclude * 2.8, abs(knee_h.x) * 1.55)

        for obj in mesh_objects:
            vg_fk = obj.vertex_groups.get(fk_knee_name)
            vg_parent = obj.vertex_groups.get(d_parent_name)
            vg_knee = obj.vertex_groups.get(d_knee_name)
            vg_lower = obj.vertex_groups.get(lower_name)
            if not vg_knee:
                continue

            idx_fk = vg_fk.index if vg_fk else -1
            idx_parent = vg_parent.index if vg_parent else -1
            idx_knee = vg_knee.index
            idx_lower = vg_lower.index if vg_lower else -1
            mw = obj.matrix_world

            for v in obj.data.vertices:
                co = mw @ v.co
                if co.z < band_bottom or co.z > band_top:
                    continue
                if co.x * side_sign < -center_exclude or abs(co.x) > side_extent:
                    continue

                w_fk = w_parent = w_knee = w_lower = 0.0
                for g in v.groups:
                    if g.group == idx_fk:
                        w_fk = g.weight
                    elif g.group == idx_parent:
                        w_parent = g.weight
                    elif g.group == idx_knee:
                        w_knee = g.weight
                    elif g.group == idx_lower:
                        w_lower = g.weight

                # 提高膝盖D最低占比；越靠近膝盖中心，目标越高
                t = (co.z - band_bottom) / max(0.001, (band_top - band_bottom))
                t = max(0.0, min(1.0, t))
                half_span = max(0.02, abs(knee_h.x - center_x))
                near_center = 1.0 - min(1.0, abs(co.x - center_x) / half_span)
                target = max(
                    0.50 + 0.20 * (1.0 - abs(t - 0.5) * 2.0),
                    w_fk * (0.98 + 0.22 * near_center),
                    w_parent * (0.58 + 0.20 * near_center),
                )
                if w_knee >= target - 0.01:
                    continue

                need = target - w_knee
                if need < 0.001:
                    continue

                take_fk = min(w_fk, need)
                remain = need - take_fk
                take_parent = min(w_parent, remain) if remain > 0 else 0.0
                remain -= take_parent
                take_lower = min(w_lower, remain) if remain > 0 else 0.0

                if take_fk > 0.0 and vg_fk:
                    vg_fk.add([v.index], max(0.0, w_fk - take_fk), 'REPLACE')
                if take_parent > 0.0 and vg_parent:
                    vg_parent.add([v.index], max(0.0, w_parent - take_parent), 'REPLACE')
                if take_lower > 0.0 and vg_lower:
                    vg_lower.add([v.index], max(0.0, w_lower - take_lower), 'REPLACE')
                new_knee = min(1.0, w_knee + take_fk + take_parent + take_lower)

                # 二段强化：对中线/内侧区域进一步抑制 FK 膝骨，让 D 骨成为主控。
                if vg_fk and w_fk > 0.05:
                    desired_fk_max = max(0.10, new_knee * (0.42 - 0.12 * near_center))
                    extra_take = max(0.0, w_fk - desired_fk_max)
                    if extra_take > 0.001:
                        fk_after = max(0.0, w_fk - extra_take)
                        vg_fk.add([v.index], fk_after, 'REPLACE')
                        new_knee = min(1.0, new_knee + extra_take)
                vg_knee.add([v.index], new_knee, 'REPLACE')
                modified += 1

    return modified


def _rescue_leg_template_residuals(armature, mesh_objects):
    """Rescue residual leg template weights back to deform D-chain groups.

    Some vertices may still be dominated by __CTMMD_SRC__ leg templates, which
    are only intermediate references and should not remain as final controllers.
    This pass remaps template residuals to 足D/ひざD/足首D using spatial side.
    """
    arm_mw = armature.matrix_world
    lb = armature.data.bones.get("左足")
    rb = armature.data.bones.get("右足")
    if not lb or not rb:
        return 0
    left_x = (arm_mw @ lb.head_local).x
    right_x = (arm_mw @ rb.head_local).x

    template_specs = (
        ("__CTMMD_SRC__左足", "foot"),
        ("__CTMMD_SRC__右足", "foot"),
        ("__CTMMD_SRC__左ひざ", "knee"),
        ("__CTMMD_SRC__右ひざ", "knee"),
        ("__CTMMD_SRC__左足首", "ankle"),
        ("__CTMMD_SRC__右足首", "ankle"),
    )
    target_by_segment = {
        "foot": ("足D.L", "足D.R"),
        "knee": ("ひざD.L", "ひざD.R"),
        "ankle": ("足首D.L", "足首D.R"),
    }
    modified = 0

    for obj in mesh_objects:
        idx_by_name = {vg.name: vg.index for vg in obj.vertex_groups}
        template_entries = []
        for t_name, seg in template_specs:
            idx = idx_by_name.get(t_name)
            vg = obj.vertex_groups.get(t_name)
            if idx is not None and vg:
                template_entries.append((t_name, seg, idx, vg))
        if not template_entries:
            continue

        target_vgs = {}
        for seg, (left_name, right_name) in target_by_segment.items():
            lv = obj.vertex_groups.get(left_name) or obj.vertex_groups.new(name=left_name)
            rv = obj.vertex_groups.get(right_name) or obj.vertex_groups.new(name=right_name)
            target_vgs[(seg, "L")] = lv
            target_vgs[(seg, "R")] = rv

        mw = obj.matrix_world
        for v in obj.data.vertices:
            best = None  # (weight, seg, template_vg)
            for _, seg, t_idx, t_vg in template_entries:
                w = 0.0
                for g in v.groups:
                    if g.group == t_idx:
                        w = g.weight
                        break
                if w > 0.20 and (best is None or w > best[0]):
                    best = (w, seg, t_vg)
            if not best:
                continue

            w_tmp, seg, t_vg = best
            vx = (mw @ v.co).x
            side = "L" if abs(vx - left_x) <= abs(vx - right_x) else "R"
            dst_vg = target_vgs[(seg, side)]

            dst_w = 0.0
            for g in v.groups:
                if g.group == dst_vg.index:
                    dst_w = g.weight
                    break
            target = max(dst_w, min(1.0, w_tmp * 0.95))
            if target > dst_w + 0.001:
                dst_vg.add([v.index], target, 'REPLACE')
                modified += 1

            # 清掉该顶点在模板组上的残留，避免模板继续“假主控”
            t_vg.add([v.index], 0.0, 'REPLACE')

    return modified


def _weight_is_orphan(bone_name):
    """判断骨骼是否为非MMD孤立骨。
    规则：重命名为MMD后，所有标准MMD骨骼名含日文字符（下半身/足D.L/腕捩.L等）。
    纯ASCII名称 = 非MMD骨（unused bip001 pelvis / root ground / breast.L 等），
    权重需转移到最近的有效MMD变形骨。
    适配 XPS / Mixamo / DAZ / CC3 / BVH 等任意来源模型。"""
    return all(ord(c) < 128 for c in bone_name)


def _weight_collect_weighted_vgs(mesh_objects):
    """收集所有网格中有顶点权重（>0.001）的顶点组名称集合。"""
    weighted = set()
    for obj in mesh_objects:
        for vg in obj.vertex_groups:
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.001:
                        weighted.add(vg.name)
                        break
                else:
                    continue
                break
    return weighted


def _weight_get_mesh_objects(context, armature):
    return [o for o in context.scene.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == armature for m in o.modifiers)]


def _weight_compute_orphan_targets(armature, mesh_objects, orphan_bones, valid_deform_bones):
    """为每个孤立骨计算目标MMD骨。
    策略（优先级从高到低）：
    1. 父级链优先：沿父级链向上，找到第一个有效MMD变形骨（含日文名且use_deform=True）
    2. D系骨映射：若父级是非变形的IK腿骨（左足/右ひざ等），
       自动映射到对应D系骨（足D.L/ひざD.R等）
    3. 几何距离兜底：父级链走到根部仍无结果，
       用顶点重心到骨骼中点的3D距离找最近有效MMD骨
    返回 dict: {orphan_bone → (target_bone, method_str)}"""

    # D系骨映射表：非变形IK腿骨 → 对应变形D系骨
    D_SERIES = {
        '左足': '足D.L',   '右足': '足D.R',
        '左ひざ': 'ひざD.L', '右ひざ': 'ひざD.R',
        '左足首': '足首D.L', '右足首': '足首D.R',
        '左足先EX': '足先EX.L', '右足先EX': '足先EX.R',
    }
    valid_bone_set = {b.name: b for b in valid_deform_bones}
    mw = armature.matrix_world
    results = {}

    for bone in orphan_bones:
        target = None
        method = ''

        # ── 策略1+2：沿父级链查找 ────────────────────────────────
        cur = bone.parent
        while cur:
            if not _weight_is_orphan(cur.name) and cur.use_deform:
                # 找到有效MMD变形骨
                target = cur
                method = f'parent({cur.name})'
                break
            if not cur.use_deform:
                # 非变形骨：检查D系映射
                d_name = D_SERIES.get(cur.name)
                if d_name and d_name in valid_bone_set:
                    target = valid_bone_set[d_name]
                    method = f'D-series({cur.name}→{d_name})'
                    break
            cur = cur.parent

        # ── 策略3：几何距离兜底 ──────────────────────────────────
        if not target:
            centroid = Vector((0.0, 0.0, 0.0))
            total_w = 0.0
            for obj in mesh_objects:
                vg = obj.vertex_groups.get(bone.name)
                if not vg:
                    continue
                mw_obj = obj.matrix_world
                for v in obj.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index and g.weight > 0.001:
                            centroid += (mw_obj @ v.co) * g.weight
                            total_w += g.weight
            if total_w < 0.001:
                continue
            centroid /= total_w

            best_dist = float('inf')
            for cand in valid_deform_bones:
                mid = (mw @ cand.head_local + mw @ cand.tail_local) * 0.5
                d = (mid - centroid).length
                if d < best_dist:
                    best_dist = d
                    target = cand
            method = f'geometry({target.name if target else "?"})'

        if target:
            results[bone] = (target, method)
    return results


def _weight_execute_orphan_transfer(mesh_objects, orphan_target_map, armature=None):
    """执行孤立骨权重转移：顶点级别的解剖区间覆盖。
    当目标骨为 下半身/腰 等躯干骨时，检查顶点所处Z区间：
    若顶点位于大腿/小腿/脚踝区间，则按X位置重定向到对应D系骨骼。
    """
    # 构建腿部区间信息（从骨架骨骼位置获取）
    leg_zones = []  # [(min_z, max_z, d_bone_left, d_bone_right), ...]
    torso_targets = {"下半身", "腰", "上半身", "センター", "グルーブ"}
    if armature:
        mw = armature.matrix_world
        zone_map = [
            ("左足",  "左ひざ",  "足D.L",  "足D.R"),
            ("左ひざ","左足首",  "ひざD.L","ひざD.R"),
            ("左足首","左足先EX","足首D.L","足首D.R"),
        ]
        for top_name, bot_name, dl, dr in zone_map:
            bt = armature.data.bones.get(top_name)
            bb = armature.data.bones.get(bot_name)
            if bt and bb:
                z_top = (mw @ bt.head_local).z
                z_bot = (mw @ bb.head_local).z
                z_min = min(z_top, z_bot) - 0.05
                z_max = max(z_top, z_bot) + 0.05
                # 只在D系骨骼存在时才用此区间
                if armature.data.bones.get(dl) and armature.data.bones.get(dr):
                    leg_zones.append((z_min, z_max, dl, dr))

    redirected = []
    for src_bone, (dst_bone, _) in orphan_target_map.items():
        for obj in mesh_objects:
            src_vg = obj.vertex_groups.get(src_bone.name)
            if not src_vg:
                continue
            # 预先缓存所有VG索引
            vg_cache = {}
            for v in obj.data.vertices:
                w = 0.0
                for g in v.groups:
                    if g.group == src_vg.index:
                        w = g.weight
                        break
                if w <= 0.001:
                    continue

                # 确定实际目标：对躯干目标做顶点级区间覆盖
                actual_dst_name = dst_bone.name
                if leg_zones and dst_bone.name in torso_targets:
                    world_z = (obj.matrix_world @ v.co).z
                    world_x = (obj.matrix_world @ v.co).x
                    for z_min, z_max, dl, dr in leg_zones:
                        if z_min <= world_z <= z_max:
                            actual_dst_name = dl if world_x >= 0 else dr
                            break

                if actual_dst_name not in vg_cache:
                    vg = obj.vertex_groups.get(actual_dst_name)
                    if not vg:
                        vg = obj.vertex_groups.new(name=actual_dst_name)
                    vg_cache[actual_dst_name] = vg
                actual_vg = vg_cache[actual_dst_name]

                cur = 0.0
                for g in v.groups:
                    if g.group == actual_vg.index:
                        cur = g.weight
                        break
                actual_vg.add([v.index], min(1.0, cur + w), 'REPLACE')
                src_vg.add([v.index], 0.0, 'REPLACE')

                # 区间覆盖发生时，同步清除原躯干目标骨骼（如下半身）上该顶点的权重，
                # 防止顶点同时被躯干骨和D系骨各拉一份造成形变错误
                if actual_dst_name != dst_bone.name:
                    if dst_bone.name not in vg_cache:
                        orig_vg = obj.vertex_groups.get(dst_bone.name)
                        if orig_vg:
                            vg_cache[dst_bone.name] = orig_vg
                    orig_torso_vg = vg_cache.get(dst_bone.name)
                    if orig_torso_vg:
                        orig_torso_vg.add([v.index], 0.0, 'REPLACE')
        redirected.append(f"{src_bone.name}→{dst_bone.name}")
    return redirected


def _weight_cleanup_leg_torso_conflict(armature, mesh_objects, z_max=None):
    """清理 D系腿骨 与 躯干骨 之间的真实冲突权重。

    ⚠️ 只处理 D系骨权重 >= 0.6（明确处于腿部区域）的顶点，
    保留 D系骨权重 < 0.6 的混合过渡区（腰臀部自然渐变，不应清除）。

    z_max：Zone 边界（世界坐标 Z）。若指定，只清理 Z < z_max 的顶点，
           即只处理 Zone 3（纯腿部），跳过 Zone 2（髋部过渡区）。
           不传则处理所有顶点（向后兼容，独立按钮用）。

    参考模型（Purifier Inase）中，腰臀过渡区有约3000个顶点
    同时具有 下半身 和 足D 权重，这是正常的权重混合，不是冲突。

    返回清理的顶点数量。"""
    D_DOMINANT_THRESHOLD = 0.6   # 只在D系权重占主导时才清躯干骨
    d_series = {"足D.L","足D.R","ひざD.L","ひざD.R","足首D.L","足首D.R","足先EX.L","足先EX.R"}
    torso_bones = {"下半身","腰"}
    cleaned = 0
    for obj in mesh_objects:
        mw = obj.matrix_world
        d_idx_set = {obj.vertex_groups[vg.name].index
                     for n in d_series if (vg := obj.vertex_groups.get(n))}
        torso_vgs = {n: obj.vertex_groups.get(n) for n in torso_bones}
        torso_vgs = {n: vg for n, vg in torso_vgs.items() if vg}
        if not d_idx_set or not torso_vgs:
            continue
        for v in obj.data.vertices:
            # Zone 边界过滤：只清 Zone 3（z_max 以下），跳过 Zone 2 过渡区
            if z_max is not None:
                vz = (mw @ v.co).z
                if vz >= z_max:
                    continue
            d_total = sum(g.weight for g in v.groups
                          if g.group in d_idx_set and g.weight > 0.001)
            # 只有D系占主导（>= 阈值）才清除躯干骨权重
            if d_total < D_DOMINANT_THRESHOLD:
                continue
            for vg in torso_vgs.values():
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.001:
                        vg.add([v.index], 0.0, 'REPLACE')
                        cleaned += 1
                        break
    return cleaned


def _get_blend_zone_z_max(armature):
    """计算髋部过渡区（Zone 2）的下边界 Z（世界坐标）。
    Zone 3 cleanup 只处理此 Z 以下的顶点。"""
    mw = armature.matrix_world
    z_maxes = []
    for fk_name in ("右足", "左足"):
        b = armature.data.bones.get(fk_name)
        if not b:
            continue
        z_top  = max((mw @ b.head_local).z, (mw @ b.tail_local).z)
        z_bot  = min((mw @ b.head_local).z, (mw @ b.tail_local).z)
        thigh_len = z_top - z_bot
        if thigh_len > 0.001:
            # 过渡区下边界 = 骨头顶端 - 46% 大腿长
            z_maxes.append(z_top - 0.46 * thigh_len)
    return min(z_maxes) if z_maxes else None


def _weight_execute_missing_fill(armature, mesh_objects, missing_bones, weighted_vgs, protect_torso=False):
    """对无权重的MMD变形骨执行bell-curve分配（从最近有权重祖先）。"""
    # D系腿骨：若祖先搜索到达躯干骨（下半身/腰），跳过填充，
    # 避免踝关节骨权重被错误扩散到腰部/大腿区域
    D_SERIES_LEG = {"足D.L","足D.R","ひざD.L","ひざD.R","足首D.L","足首D.R","足先EX.L","足先EX.R"}
    TORSO_LIMIT  = {"下半身","腰","グルーブ","センター","全ての親"}
    # Step 11 安全模式：保护躯干/头颈/肩骨，避免“缺失补权重”把上半身区域改脏。
    # 这些骨骼优先由步骤化流程（重分配/切分/扭转骨步骤）建立，不在自动兜底里盲补。
    TORSO_PROTECTED = {
        "上半身", "上半身1", "上半身2", "上半身3",
        "首", "頭", "左肩", "右肩", "左目", "右目", "両目",
    }
    mw = armature.matrix_world
    fixed, unfixed = [], []
    for bone in missing_bones:
        if protect_torso and bone.name in TORSO_PROTECTED:
            unfixed.append(f"{bone.name}(躯干保护跳过)")
            continue
        ancestor = bone.parent
        while ancestor and ancestor.name not in weighted_vgs:
            ancestor = ancestor.parent
        if not ancestor:
            unfixed.append(bone.name)
            continue
        # D系腿骨不允许从躯干骨继承，留给后续手动修复
        if bone.name in D_SERIES_LEG and ancestor.name in TORSO_LIMIT:
            unfixed.append(bone.name)
            continue

        anc_h = mw @ ancestor.head_local
        anc_t = mw @ ancestor.tail_local
        anc_vec = anc_t - anc_h
        anc_len = anc_vec.length
        if anc_len < 1e-6:
            unfixed.append(bone.name)
            continue
        anc_dir = anc_vec / anc_len

        bone_h_world = mw @ bone.head_local
        t_center = max(0.0, min(1.0, (bone_h_world - anc_h).dot(anc_dir) / anc_len))
        radius = 0.20
        success = False

        for obj in mesh_objects:
            src_vg = obj.vertex_groups.get(ancestor.name)
            if not src_vg:
                continue
            dst_vg = obj.vertex_groups.get(bone.name) or obj.vertex_groups.new(name=bone.name)
            for v in obj.data.vertices:
                w_src = 0.0
                for g in v.groups:
                    if g.group == src_vg.index:
                        w_src = g.weight
                        break
                if w_src <= 0.001:
                    continue
                v_world = obj.matrix_world @ v.co
                t_v = (v_world - anc_h).dot(anc_dir) / anc_len
                dist = abs(t_v - t_center)
                if dist >= radius:
                    continue
                influence = (1.0 - dist / radius) * w_src
                cur = 0.0
                for g in v.groups:
                    if g.group == dst_vg.index:
                        cur = g.weight
                        break
                dst_vg.add([v.index], min(1.0, cur + influence), 'REPLACE')
                success = True

        (fixed if success else unfixed).append(bone.name)
    return fixed, unfixed


# ─────────────────────────────────────────────────────────────────────────────
def _transfer_helper_weights(mesh_objects, redirect_map):
    return _redirect_transfer_helper_weights(mesh_objects, redirect_map)


def _cleanup_inner_thigh_d_weights(armature, mesh_objects):
    return _redirect_cleanup_inner_thigh_d_weights(armature, mesh_objects)


def _restore_upper_thigh_d_influence(armature, mesh_objects):
    return _redirect_restore_upper_thigh_d_influence(armature, mesh_objects)


class OBJECT_OT_disable_xps_helper_bones(bpy.types.Operator):
    """Step 4：将 XPS 腿/腰辅助骨权重合并到对应 MMD 骨骼，然后禁用辅助骨。

    处理范围（腿/腰部分）：
      unused bip001 xtra02  → 足D.R     （右大腿扭转辅助）
      unused bip001 xtra04  → 足D.L     （左大腿扭转辅助）
      unused bip001 pelvis  → 下半身    （骨盆）
      unused bip001 xtra08  → 下半身    （内裆辅助）
      unused bip001 xtra08opp → 下半身  （内裆辅助对侧）
      unused muscle_elbow_l → 左腕      （肘部肌肉）
      unused muscle_elbow_r → 右腕      （肘部肌肉）
    前臂扭转骨（foretwist）请在 Step 6 添加腕捩骨后执行「6.5 转移前臂扭转权重」。
    """
    bl_idname = "object.disable_xps_helper_bones"
    bl_label = "Disable XPS Helper Bones (Step 4)"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        _sync_scene_mapping_to_existing_mmd_names(context.scene, armature)

        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        # 1. 转移权重
        profile = get_default_profile()
        helper_redirects = dict(profile.helper_redirects)

        # Step2 已经做过“下半身初始化”时，Step4 不再重复把 pelvis/xtra08 全量灌入下半身，
        # 否则会在归一化后稀释腿部D链，出现“点到4后权重回退”。
        step2_done = bool(context.scene.get("step2_execution_report")) or bool(armature.get("step2_execution_report"))
        if step2_done:
            filtered = {}
            skipped_lower = []
            for src_name, redirect in helper_redirects.items():
                if isinstance(redirect, dict):
                    target_name = redirect.get("target")
                else:
                    target_name = redirect
                if target_name == "下半身":
                    skipped_lower.append(src_name)
                    continue
                filtered[src_name] = redirect
            helper_redirects = filtered
        else:
            skipped_lower = []

        total_verts, details = _transfer_helper_weights(mesh_objects, helper_redirects)

        # 2. 清理内侧上缘/中线区域残留的 D 骨污染，并把腿根上缘的本侧足D参与带补回来
        cleanup_modified = _cleanup_inner_thigh_d_weights(armature, mesh_objects)
        restored_modified = _restore_upper_thigh_d_influence(armature, mesh_objects)
        mid_thigh_reinforced = _redirect_reinforce_mid_thigh_d_influence(armature, mesh_objects)
        upper_leg_hard_fixed = _redirect_enforce_upper_leg_d_mastery(armature, mesh_objects)
        knee_reinforced = _reinforce_knee_d_influence(armature, mesh_objects)
        template_rescued = _rescue_leg_template_residuals(armature, mesh_objects)

        # 3. 归一化（防止合并后超过 1.0）
        _normalize_deform_weights(armature, mesh_objects)

        # 4. 禁用所有 unused 骨骼（含 foretwist，但 foretwist 权重此时未转移，仅禁用变形）
        disabled = []
        for bone in armature.data.bones:
            if bone.use_deform and "unused" in bone.name.lower():
                bone.use_deform = False
                disabled.append(bone.name)

        msg_parts = []
        if details:
            msg_parts.append(f"转移：{'; '.join(details)}")
        if cleanup_modified:
            msg_parts.append(f"清理大腿内侧 {cleanup_modified} 顶点")
        if restored_modified:
            msg_parts.append(f"恢复腿根足D {restored_modified} 顶点")
        if mid_thigh_reinforced:
            msg_parts.append(f"大腿控制带已加强 {mid_thigh_reinforced} 顶点")
        if upper_leg_hard_fixed:
            msg_parts.append(f"腿根硬修复已执行 {upper_leg_hard_fixed} 顶点")
        if knee_reinforced:
            msg_parts.append(f"膝盖D已加强 {knee_reinforced} 顶点")
        if template_rescued:
            msg_parts.append(f"模板残留已回收 {template_rescued} 顶点")
        if disabled:
            msg_parts.append(f"禁用 {len(disabled)} 根辅助骨")
        if skipped_lower:
            msg_parts.append(f"跳过下半身重复转移 {len(skipped_lower)} 项")
        if msg_parts:
            self.report({'INFO'}, "✅ " + " | ".join(msg_parts))
        else:
            self.report({'INFO'}, "未找到需要处理的 XPS 辅助骨")
        weight_monitor.auto_check_after_step(context, armature, "step_2_5", "辅助骨权重转移")
        return {'FINISHED'}


class OBJECT_OT_transfer_foretwist_weights(bpy.types.Operator):
    """Step 8：将 XPS 前臂扭转骨权重合并到 MMD 腕捩骨，然后禁用前臂扭转骨。

    需在「Step 6 添加扭转骨（腕捩/手捩）」之后执行，否则腕捩骨不存在。
      unused bip001 l foretwist  → 左腕捩
      unused bip001 l foretwist1 → 左腕捩
      unused bip001 r foretwist  → 右腕捩
      unused bip001 r foretwist1 → 右腕捩
      unused bip001 xtra07pp     → 左肩
      unused bip001 xtra07       → 右肩
    """
    bl_idname = "object.transfer_foretwist_weights"
    bl_label = "Transfer Foretwist Weights (Step 8)"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        # 检查手捩骨是否已创建（Step 6 生成的命名为 手捩.L / 手捩.R）
        if not armature.data.bones.get("手捩.L") and not armature.data.bones.get("手捩.R"):
            self.report({'WARNING'}, "未找到手捩骨（手捩.L/R），请先执行 Step 6「添加扭转骨骼」")
            return {'CANCELLED'}

        profile = get_default_profile()
        total_verts, details = _transfer_helper_weights(mesh_objects, profile.foretwist_redirects)
        _normalize_deform_weights(armature, mesh_objects)

        # 禁用前臂扭转骨
        disabled = []
        for src_name in profile.foretwist_redirects:
            bone = armature.data.bones.get(src_name)
            if bone and bone.use_deform:
                bone.use_deform = False
                disabled.append(src_name)

        msg_parts = []
        if details:
            msg_parts.append(f"转移：{'; '.join(details)}")
        if disabled:
            msg_parts.append(f"禁用 {len(disabled)} 根前臂辅助骨")
        if msg_parts:
            self.report({'INFO'}, "✅ " + " | ".join(msg_parts))
        else:
            self.report({'INFO'}, "未找到需要处理的前臂扭转骨")
        weight_monitor.auto_check_after_step(context, armature, "step_6_5", "前臂扭转权重转移")
        return {'FINISHED'}


# Phase 1 — 孤立骨：检查
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_check_orphan_weights(bpy.types.Operator):
    """检查纯ASCII名称的孤立变形骨（非MMD骨有顶点权重），预览将转移到哪个MMD骨。
    不修改任何数据，仅在UI中显示结果。"""
    bl_idname = "object.check_orphan_weights"
    bl_label = "检查孤立骨（非MMD骨有权重）"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        valid_bones = [b for b in armature.data.bones
                       if b.use_deform and not _weight_is_orphan(b.name)]
        orphan_bones = [b for b in armature.data.bones
                        if b.use_deform and _weight_is_orphan(b.name)
                        and b.name in weighted_vgs]

        targets = _weight_compute_orphan_targets(armature, mesh_objects, orphan_bones, valid_bones)

        scene = context.scene
        scene.weight_orphan_check_done = True
        scene.weight_orphan_count = len(targets)
        preview_parts = [f"{b.name}→{t.name}[{m}]" for b, (t, m) in list(targets.items())[:8]]
        scene.weight_orphan_preview = ' | '.join(preview_parts)
        if len(targets) > 8:
            scene.weight_orphan_preview += f' ...共{len(targets)}个'

        if targets:
            self.report({'WARNING'}, f"发现 {len(targets)} 个孤立骨待转移")
        else:
            self.report({'INFO'}, "✅ 无孤立骨（所有变形骨名称均含日文）")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — 孤立骨：修复
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_fix_orphan_weights(bpy.types.Operator):
    """将孤立变形骨（纯ASCII名称）的顶点权重，按顶点重心距骨骼中点最近原则，
    转移到最近的有效MMD变形骨。操作不可逆，建议先运行检查确认目标骨。"""
    bl_idname = "object.fix_orphan_weights"
    bl_label = "修复：转移孤立骨权重到最近MMD骨"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        valid_bones = [b for b in armature.data.bones
                       if b.use_deform and not _weight_is_orphan(b.name)]
        orphan_bones = [b for b in armature.data.bones
                        if b.use_deform and _weight_is_orphan(b.name)
                        and b.name in weighted_vgs]

        targets = _weight_compute_orphan_targets(armature, mesh_objects, orphan_bones, valid_bones)
        redirected = _weight_execute_orphan_transfer(mesh_objects, targets, armature)

        # 清理 Zone 3（纯腿部）的冲突权重，跳过 Zone 2 髋部过渡区
        z_max = _get_blend_zone_z_max(armature)
        cleaned = _weight_cleanup_leg_torso_conflict(armature, mesh_objects, z_max=z_max)

        # 重置检查状态（权重已变，结果过期）
        context.scene.weight_orphan_check_done = False
        context.scene.weight_orphan_count = 0

        if redirected:
            names = ' | '.join(redirected[:6]) + ('...' if len(redirected) > 6 else '')
            self.report({'INFO'}, f"已转移 {len(redirected)} 个孤立骨: {names}  清理冲突顶点: {cleaned}")
        else:
            self.report({'INFO'}, f"✅ 无孤立骨需要处理  清理冲突顶点: {cleaned}")
        weight_monitor.auto_check_after_step(context, armature, "step_7", "孤立骨修复")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — 缺失权重：检查
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_check_missing_weights(bpy.types.Operator):
    """检查有效MMD变形骨（含日文名称）中无顶点权重的骨骼，预览将从哪个祖先分配。
    不修改任何数据，仅在UI中显示结果。"""
    bl_idname = "object.check_missing_weights"
    bl_label = "检查MMD骨骼缺失权重"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        missing = [b for b in armature.data.bones
                   if b.use_deform and not _weight_is_orphan(b.name)
                   and b.name not in weighted_vgs]

        # 预览每个骨骼将从哪个祖先接收权重
        preview_parts = []
        for bone in missing[:10]:
            ancestor = bone.parent
            while ancestor and ancestor.name not in weighted_vgs:
                ancestor = ancestor.parent
            src = ancestor.name if ancestor else "无祖先"
            preview_parts.append(f"{bone.name}←{src}")

        scene = context.scene
        scene.weight_missing_check_done = True
        scene.weight_missing_count = len(missing)
        scene.weight_missing_names = ' | '.join(preview_parts)
        if len(missing) > 10:
            scene.weight_missing_names += f' ...共{len(missing)}个'

        if missing:
            self.report({'WARNING'}, f"发现 {len(missing)} 个MMD骨骼无权重")
        else:
            self.report({'INFO'}, "✅ 所有MMD变形骨骼均有顶点权重")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — 缺失权重：修复
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_fix_missing_weights(bpy.types.Operator):
    """对无顶点权重的MMD变形骨（D系骨/扭转骨/桥接骨等），从最近有权重的祖先骨骼
    按骨骼轴投影+bell-curve衰减（半径20%）分配权重。不减少祖先权重，
    由MMD导出时自动归一化。"""
    bl_idname = "object.fix_missing_weights"
    bl_label = "修复：从祖先骨骼分配缺失权重"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        missing = [b for b in armature.data.bones
                   if b.use_deform and not _weight_is_orphan(b.name)
                   and b.name not in weighted_vgs]

        fixed, unfixed = _weight_execute_missing_fill(armature, mesh_objects, missing, weighted_vgs)

        # 清理 Zone 3（纯腿部）的冲突权重，跳过 Zone 2 髋部过渡区
        z_max = _get_blend_zone_z_max(armature)
        cleaned = _weight_cleanup_leg_torso_conflict(armature, mesh_objects, z_max=z_max)

        # 重置检查状态
        context.scene.weight_missing_check_done = False
        context.scene.weight_missing_count = 0

        parts = []
        if fixed:
            parts.append(f"补全 {len(fixed)} 个: {', '.join(fixed[:6])}{'...' if len(fixed)>6 else ''}")
        if unfixed:
            parts.append(f"无祖先跳过 {len(unfixed)} 个: {', '.join(unfixed[:4])}")
        if cleaned:
            parts.append(f"清理冲突 {cleaned} 顶点")
        if not parts:
            parts.append("✅ 所有MMD变形骨均有权重，无需操作")
        self.report({'INFO'}, ' | '.join(parts))
        weight_monitor.auto_check_after_step(context, armature, "step_8", "缺失权重修复")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# 独立的腿部权重冲突清理（D系骨 vs 下半身/腰）
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_cleanup_leg_conflict(bpy.types.Operator):
    """清理腿部D系骨（足D/ひざD/足首D）与躯干骨（下半身/腰）的权重冲突。
    当同一顶点同时被D系骨和躯干骨影响时，移除躯干骨权重。"""
    bl_idname = "object.cleanup_leg_conflict"
    bl_label = "清理腿部权重冲突（D系 vs 下半身）"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        cleaned = _weight_cleanup_leg_torso_conflict(armature, mesh_objects)
        if cleaned:
            self.report({'INFO'}, f"✅ 已清理 {cleaned} 个冲突权重（D系骨区域移除下半身/腰权重）")
        else:
            self.report({'INFO'}, "✅ 无冲突权重，无需清理")
        return {'FINISHED'}


# ─────────────────────────────────────────────────────────────────────────────
# 独立的髋部渐变过渡区 检查 + 修复（通用，适用于任何 XPS/DAZ/CC3 等来源模型）
# ─────────────────────────────────────────────────────────────────────────────

class OBJECT_OT_check_hip_blend_zone(bpy.types.Operator):
    """检查髋部（下半身↔足D.L/R）是否存在权重渐变过渡区。
    XPS/DAZ 等来源模型的权重通常是二值的，会导致腰骨运动时出现硬切割。"""
    bl_idname = "object.check_hip_blend_zone"
    bl_label = "检查髋部渐变区"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        result = _check_hip_blend_zone(mesh_objects)
        scene = context.scene
        scene.hip_blend_check_done  = True
        scene.hip_blend_left_count  = result["left_blend"]
        scene.hip_blend_right_count = result["right_blend"]
        scene.hip_blend_left_binary = result["left_binary"]
        scene.hip_blend_right_binary = result["right_binary"]

        if result["left_binary"] > 100 or result["right_binary"] > 100:
            self.report({'WARNING'},
                f"髋部过渡区为二值权重：左={result['left_binary']}个硬边顶点  右={result['right_binary']}个  "
                f"（过渡混合顶点：左={result['left_blend']}  右={result['right_blend']}）"
                f" → 建议点「修复」")
        else:
            self.report({'INFO'},
                f"✅ 髋部渐变区正常（混合顶点：左={result['left_blend']}  右={result['right_blend']}）")
        return {'FINISHED'}


class OBJECT_OT_fix_hip_blend_zone(bpy.types.Operator):
    """修复髋部渐变区：在足D.L/R权重范围顶部创建下半身权重渐变，
    解决 XPS/DAZ/CC3 等来源模型的腰骨运动硬切割问题。"""
    bl_idname = "object.fix_hip_blend_zone"
    bl_label = "修复髋部渐变区"

    transition_height: bpy.props.FloatProperty(
        name="渐变高度",
        description="足D顶部往下多少单位开始渐变（默认1.5，可根据模型比例调整）",
        default=1.5, min=0.3, max=5.0
    )

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        # 直接建立渐变区，不做 cleanup
        # cleanup 会把 足D>=0.6 的顶点的下半身清零，破坏渐变区中间段（足D=0.6~1.0 区域有意保留下半身）
        modified = _create_hip_blend_zone(armature, mesh_objects, self.transition_height)
        context.scene.hip_blend_check_done = False  # 重置，需重新检查

        if modified > 0:
            self.report({'INFO'},
                f"✅ 髋部渐变区已创建（修改 {modified} 个顶点，渐变高度={self.transition_height:.1f}）")
        else:
            self.report({'WARNING'}, "未找到需要渐变的顶点（足D.L/R 或 下半身 不存在）")
        weight_monitor.auto_check_after_step(context, armature, "hip_fix", "髋部渐变修复")
        return {'FINISHED'}


def _check_hip_blend_zone(mesh_objects):
    """统计髋部过渡区的状态：有多少顶点已经混合，有多少还是二值。"""
    result = {"left_blend": 0, "right_blend": 0, "left_binary": 0, "right_binary": 0}
    for obj in mesh_objects:
        for d_bone, key_blend, key_binary in [
            ("足D.L", "left_blend",  "left_binary"),
            ("足D.R", "right_blend", "right_binary"),
        ]:
            vg_d = obj.vertex_groups.get(d_bone)
            vg_s = obj.vertex_groups.get("下半身")
            if not vg_d or not vg_s:
                continue
            idx_d, idx_s = vg_d.index, vg_s.index
            mw = obj.matrix_world

            z_vals = [(mw @ v.co).z for v in obj.data.vertices
                      for g in v.groups if g.group == idx_d and g.weight > 0.001]
            if not z_vals:
                continue
            z_max = max(z_vals)
            z_top_zone = z_max - 1.5  # 只检查顶部 1.5 单位

            for v in obj.data.vertices:
                vz = (mw @ v.co).z
                if vz < z_top_zone:
                    continue
                wd = ws = 0.0
                for g in v.groups:
                    if g.group == idx_d: wd = g.weight
                    if g.group == idx_s: ws = g.weight
                if wd <= 0.001:
                    continue
                if ws > 0.05:
                    result[key_blend] += 1   # 已经有混合
                elif wd > 0.85:
                    result[key_binary] += 1  # 二值，需要修复
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 保留一键合并版本（供自动转换流程调用）
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_check_fix_missing_weights(bpy.types.Operator):
    """一键执行孤立骨重定向（Phase1）+ 缺失权重补全（Phase2）。
    供"一键全流程转换"内部调用，手动使用建议分步骤检查。"""
    bl_idname = "object.check_fix_missing_weights"
    bl_label = "一键修复全部权重问题"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}
        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        valid_bones = [b for b in armature.data.bones
                       if b.use_deform and not _weight_is_orphan(b.name)]
        orphan_bones = [b for b in armature.data.bones
                        if b.use_deform and _weight_is_orphan(b.name)
                        and b.name in weighted_vgs]
        targets = _weight_compute_orphan_targets(armature, mesh_objects, orphan_bones, valid_bones)
        redirected = _weight_execute_orphan_transfer(mesh_objects, targets, armature)

        weighted_vgs = _weight_collect_weighted_vgs(mesh_objects)
        missing = [b for b in armature.data.bones
                   if b.use_deform and not _weight_is_orphan(b.name)
                   and b.name not in weighted_vgs]
        fixed, unfixed = _weight_execute_missing_fill(
            armature, mesh_objects, missing, weighted_vgs, protect_torso=True
        )

        # 清理 Zone 3（纯腿部）的冲突权重，跳过 Zone 2 髋部过渡区
        z_max = _get_blend_zone_z_max(armature)
        _weight_cleanup_leg_torso_conflict(armature, mesh_objects, z_max=z_max)

        parts = []
        if redirected:
            parts.append(f"[P1] 孤立骨→MMD {len(redirected)}个")
        if fixed:
            parts.append(f"[P2] 补全权重 {len(fixed)}个")
        if unfixed:
            parts.append(f"[P2] 跳过 {len(unfixed)}个(无祖先)")
        if not parts:
            parts.append("✅ 权重正常")
        self.report({'INFO'}, ' | '.join(parts))
        weight_monitor.auto_check_after_step(context, armature, "step_11", "一键权重修复")
        return {'FINISHED'}

# ─────────────────────────────────────────────────────────────────────────────
# 手动权重转移（通用，适配任意骨骼名称）
# ─────────────────────────────────────────────────────────────────────────────
class OBJECT_OT_manual_weight_transfer(bpy.types.Operator):
    """手动指定源骨骼和目标骨骼，将源骨骼的所有顶点权重叠加转移到目标骨骼。
    转移后源骨骼VG权重清零（保留VG）。
    适用于：修复孤立骨权重分配错误、手动调整肩/腕等骨骼权重分布。"""
    bl_idname = "object.manual_weight_transfer"
    bl_label = "手动转移权重（源 → 目标）"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        src_name = context.scene.weight_manual_src
        dst_name = context.scene.weight_manual_dst
        if not src_name or not dst_name:
            self.report({'ERROR'}, "请填写源骨骼和目标骨骼名称")
            return {'CANCELLED'}
        if src_name == dst_name:
            self.report({'ERROR'}, "源骨骼和目标骨骼不能相同")
            return {'CANCELLED'}

        mesh_objects = _weight_get_mesh_objects(context, armature)
        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定网格")
            return {'CANCELLED'}

        transferred_verts = 0
        affected_meshes = 0

        for obj in mesh_objects:
            src_vg = obj.vertex_groups.get(src_name)
            if not src_vg:
                continue
            dst_vg = obj.vertex_groups.get(dst_name)
            if not dst_vg:
                dst_vg = obj.vertex_groups.new(name=dst_name)

            count = 0
            for v in obj.data.vertices:
                w_src = 0.0
                for g in v.groups:
                    if g.group == src_vg.index:
                        w_src = g.weight
                        break
                if w_src <= 0.001:
                    continue

                cur_dst = 0.0
                for g in v.groups:
                    if g.group == dst_vg.index:
                        cur_dst = g.weight
                        break

                dst_vg.add([v.index], min(1.0, cur_dst + w_src), 'REPLACE')
                src_vg.add([v.index], 0.0, 'REPLACE')
                count += 1

            if count:
                transferred_verts += count
                affected_meshes += 1

        if transferred_verts:
            self.report({'INFO'},
                f"✅ 已转移 {transferred_verts} 个顶点权重：{src_name} → {dst_name}（{affected_meshes}个网格）")
        else:
            self.report({'WARNING'}, f"源骨骼 '{src_name}' 无顶点权重，无需转移")
        return {'FINISHED'}
