import bpy
import math
from mathutils import Matrix
from ..bone_utils import apply_armature_transforms

ARM_BEND_THRESHOLD = 3.0  # 超过此角度（度）认为有弯曲问题


def _bend_angle(bone_a, bone_b):
    """计算两根骨骼方向的弯曲角度（0=笔直，正值=有弯曲）"""
    if not bone_a or not bone_b:
        return 0.0
    d_a = (bone_a.tail - bone_a.head).normalized()
    d_b = (bone_b.tail - bone_b.head).normalized()
    dot = max(-1.0, min(1.0, d_a.dot(d_b)))
    return math.degrees(math.acos(dot))  # 0=方向相同=笔直


def _rot_to_align(from_vec, to_vec):
    """返回将 from_vec 旋转到 to_vec 的 4x4 旋转矩阵，若已对齐返回 None"""
    axis = from_vec.cross(to_vec)
    if axis.length < 1e-6:
        return None
    axis = axis.normalized()
    dot = max(-1.0, min(1.0, from_vec.dot(to_vec)))
    return Matrix.Rotation(math.acos(dot), 4, axis)


class OBJECT_OT_check_arm_straightness(bpy.types.Operator):
    """检测手臂关节是否笔直（上臂-前臂、前臂-手腕）"""
    bl_idname = "object.check_arm_straightness"
    bl_label = "检测手臂关节"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        scene = context.scene
        left_upper  = getattr(scene, "left_upper_arm_bone",  "")
        left_lower  = getattr(scene, "left_lower_arm_bone",  "")
        right_upper = getattr(scene, "right_upper_arm_bone", "")
        right_lower = getattr(scene, "right_lower_arm_bone", "")
        left_hand   = getattr(scene, "left_hand_bone",  "")
        right_hand  = getattr(scene, "right_hand_bone", "")

        if not any([left_upper, left_lower, right_upper, right_lower]):
            self.report({'ERROR'}, "请先在骨骼映射中设置腕/ひじ骨骼")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        eb = obj.data.edit_bones

        elbow_bends = {}
        wrist_bends = {}
        for side, upper_name, lower_name, hand_name in [
            ("左", left_upper, left_lower, left_hand),
            ("右", right_upper, right_lower, right_hand),
        ]:
            upper = eb.get(upper_name)
            lower = eb.get(lower_name)
            hand  = eb.get(hand_name) if hand_name else None
            elbow_bends[side] = _bend_angle(upper, lower)
            wrist_bends[side] = _bend_angle(lower, hand)

        bpy.ops.object.mode_set(mode='OBJECT')

        left_elbow  = elbow_bends.get("左", 0.0)
        right_elbow = elbow_bends.get("右", 0.0)
        left_wrist  = wrist_bends.get("左", 0.0)
        right_wrist = wrist_bends.get("右", 0.0)
        has_problem = any(v > ARM_BEND_THRESHOLD for v in [left_elbow, right_elbow, left_wrist, right_wrist])

        scene.arm_check_done        = True
        scene.arm_check_has_problem = has_problem
        scene.arm_check_left_bend   = left_elbow
        scene.arm_check_right_bend  = right_elbow
        scene.arm_check_left_wrist  = left_wrist
        scene.arm_check_right_wrist = right_wrist

        if has_problem:
            self.report({'WARNING'},
                f"弯曲：肘 左{left_elbow:.1f}° 右{right_elbow:.1f}°  "
                f"腕 左{left_wrist:.1f}° 右{right_wrist:.1f}°")
        else:
            self.report({'INFO'}, "手臂关节笔直，可直接转A-Pose")
        return {'FINISHED'}


def _apply_pose_rotations(context, obj, pose_bone_rots):
    """
    在 POSE 模式对指定骨骼施加旋转，然后通过「复制修改器→应用→armature_apply」
    将姿态烘焙进网格静置姿态。
    pose_bone_rots: [(bone_name, rot_matrix), ...]  rot_matrix=None 跳过
    返回 True/False
    """
    # 收集可用网格（无 shape keys）
    meshes = []
    for mesh_obj in bpy.data.objects:
        if mesh_obj.type == 'MESH':
            for mod in mesh_obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object == obj:
                    if not mesh_obj.data.shape_keys:
                        meshes.append(mesh_obj)
                    break

    temp_mesh = None
    if not meshes:
        bpy.ops.mesh.primitive_cube_add(size=0.5)
        temp_mesh = context.active_object
        temp_mesh.name = "CTMMD_TEMP_FIX"
        mod = temp_mesh.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = obj
        meshes.append(temp_mesh)

    # 为每个网格添加复制修改器
    TAG = "_ctmmd_fix_copy"
    for mesh_obj in meshes:
        for mod in mesh_obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object == obj:
                cp = mesh_obj.modifiers.new(name=mod.name + TAG, type='ARMATURE')
                cp.object = obj
                cp.use_vertex_groups  = mod.use_vertex_groups
                cp.use_bone_envelopes = mod.use_bone_envelopes
                break

    # POSE 模式施加旋转
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')

    pb = obj.pose.bones
    applied = []
    for bone_name, rot_mat in pose_bone_rots:
        if rot_mat is None or not bone_name:
            continue
        b = pb.get(bone_name)
        if b:
            b.matrix = rot_mat @ b.matrix
            applied.append(bone_name)

    context.view_layer.update()

    if not applied:
        # 清理复制修改器再退出
        bpy.ops.object.mode_set(mode='OBJECT')
        for mesh_obj in meshes:
            for mod in list(mesh_obj.modifiers):
                if TAG in mod.name:
                    mesh_obj.modifiers.remove(mod)
        if temp_mesh:
            bpy.data.objects.remove(temp_mesh, do_unlink=True)
        return False

    # 对每个网格应用复制修改器（烘焙当前姿态变形）
    try:
        for mesh_obj in meshes:
            context.view_layer.objects.active = mesh_obj
            for mod in list(mesh_obj.modifiers):
                if mod.type == 'ARMATURE' and mod.object == obj and TAG in mod.name:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    break
    except RuntimeError as e:
        raise e

    # 切回骨架，应用当前姿态为新静置姿态
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.armature_apply()
    bpy.ops.object.mode_set(mode='OBJECT')

    if temp_mesh:
        bpy.data.objects.remove(temp_mesh, do_unlink=True)

    return True


class OBJECT_OT_fix_elbow_straightness(bpy.types.Operator):
    """将前臂对齐到上臂方向，消除肘关节弯曲，烘焙到静置姿态"""
    bl_idname = "object.fix_elbow_straightness"
    bl_label = "0b. 修复肘关节弯曲"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        scene = context.scene
        left_upper  = getattr(scene, "left_upper_arm_bone", "")
        left_lower  = getattr(scene, "left_lower_arm_bone", "")
        right_upper = getattr(scene, "right_upper_arm_bone", "")
        right_lower = getattr(scene, "right_lower_arm_bone", "")

        bpy.ops.object.mode_set(mode='EDIT')
        eb = obj.data.edit_bones
        rots = []
        fixed_sides = []
        for side, upper_name, lower_name in [
            ("左", left_upper, left_lower),
            ("右", right_upper, right_lower),
        ]:
            upper = eb.get(upper_name)
            lower = eb.get(lower_name)
            if not upper or not lower:
                continue
            d_upper = (upper.tail - upper.head).normalized()
            d_lower = (lower.tail - lower.head).normalized()
            rots.append((lower_name, _rot_to_align(d_lower, d_upper)))
            fixed_sides.append(side)
        bpy.ops.object.mode_set(mode='OBJECT')

        if not rots:
            self.report({'WARNING'}, "未找到上臂/前臂骨骼，请检查骨骼映射")
            return {'CANCELLED'}

        try:
            ok = _apply_pose_rotations(context, obj, rots)
        except RuntimeError as e:
            self.report({'ERROR'}, f"应用修改器失败：{e}")
            return {'CANCELLED'}

        if not ok:
            self.report({'INFO'}, "肘关节已笔直，无需修复")
            return {'FINISHED'}

        scene.arm_check_done = False
        self.report({'INFO'}, f"已修复 {'/'.join(fixed_sides)} 肘关节弯曲，网格已同步更新")
        return {'FINISHED'}


class OBJECT_OT_fix_wrist_straightness(bpy.types.Operator):
    """将手腕对齐到前臂方向，消除腕关节弯曲，烘焙到静置姿态"""
    bl_idname = "object.fix_wrist_straightness"
    bl_label = "0c. 修复腕关节弯曲"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        scene = context.scene
        left_lower  = getattr(scene, "left_lower_arm_bone", "")
        right_lower = getattr(scene, "right_lower_arm_bone", "")
        left_hand   = getattr(scene, "left_hand_bone", "")
        right_hand  = getattr(scene, "right_hand_bone", "")

        bpy.ops.object.mode_set(mode='EDIT')
        eb = obj.data.edit_bones
        rots = []
        fixed_sides = []
        for side, lower_name, hand_name in [
            ("左", left_lower, left_hand),
            ("右", right_lower, right_hand),
        ]:
            lower = eb.get(lower_name)
            hand  = eb.get(hand_name) if hand_name else None
            if not lower or not hand:
                continue
            # 手腕对齐前臂方向（不是上臂，因为肘可能已经先修复）
            d_lower = (lower.tail - lower.head).normalized()
            d_hand  = (hand.tail  - hand.head).normalized()
            rots.append((hand_name, _rot_to_align(d_hand, d_lower)))
            fixed_sides.append(side)
        bpy.ops.object.mode_set(mode='OBJECT')

        if not rots:
            self.report({'WARNING'}, "未找到前臂/手腕骨骼，请检查骨骼映射")
            return {'CANCELLED'}

        try:
            ok = _apply_pose_rotations(context, obj, rots)
        except RuntimeError as e:
            self.report({'ERROR'}, f"应用修改器失败：{e}")
            return {'CANCELLED'}

        if not ok:
            self.report({'INFO'}, "腕关节已笔直，无需修复")
            return {'FINISHED'}

        scene.arm_check_done = False
        self.report({'INFO'}, f"已修复 {'/'.join(fixed_sides)} 腕关节弯曲，网格已同步更新")
        return {'FINISHED'}


class OBJECT_OT_fix_arm_straightness(bpy.types.Operator):
    """一键修复肘+腕关节弯曲（等同于依次执行0b和0c）"""
    bl_idname = "object.fix_arm_straightness"
    bl_label = "0b+c 一键修复肘+腕"

    def execute(self, context):
        bpy.ops.object.fix_elbow_straightness()
        bpy.ops.object.fix_wrist_straightness()
        return {'FINISHED'}
# 新增的T-Pose到A-Pose转换操作符
class OBJECT_OT_convert_to_apose(bpy.types.Operator):
    """将骨架转换为 A-Pose 并应用为新的静置姿态"""
    bl_idname = "object.convert_to_apose" 
    bl_label = "Convert to A-Pose"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "未选择骨架对象")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "应用骨架变换失败")
            return {'CANCELLED'}
        scene = context.scene
        
        # 获取骨骼名称
        arm_bones = {
            "left_upper_arm": getattr(scene, "left_upper_arm_bone", ""),
            "right_upper_arm": getattr(scene, "right_upper_arm_bone", ""),
        }

        # 检查是否有设置骨骼
        if not any(arm_bones.values()):
            self.report({'ERROR'}, "请先在UI中设置要转换的骨骼")
            return {'CANCELLED'}

        # 1. 确保在对象模式
        bpy.ops.object.mode_set(mode='OBJECT')

        # 2. 找到所有使用这个骨骼的网格对象，并检查形态键
        meshes_with_armature = []
        for mesh_obj in bpy.data.objects:
            if mesh_obj.type == 'MESH':
                for modifier in mesh_obj.modifiers:
                    if modifier.type == 'ARMATURE' and modifier.object == obj:
                        # 检查是否有形态键
                        if not mesh_obj.data.shape_keys:
                            meshes_with_armature.append(mesh_obj)
                        break

        # 检查是否找到可用的网格
        if not meshes_with_armature:
            # 创建临时测试网格
            try:
                bpy.ops.mesh.primitive_cube_add(size=0.5)
                temp_mesh = context.active_object
                temp_mesh.name = "CTMMD_TEMP_MESH"
                
                # 添加骨架修改器
                modifier = temp_mesh.modifiers.new(name="Armature", type='ARMATURE')
                modifier.object = obj
                
                # 添加到可用网格列表
                meshes_with_armature.append(temp_mesh)
                
                # 标记为临时网格
                temp_mesh["is_temp_mesh"] = True
                
            except Exception as e:
                self.report({'ERROR'}, f"创建临时网格失败：{str(e)}")
                return {'CANCELLED'}

        # 3. 为每个网格复制骨骼修改器，但保留原始修改器
        for mesh_obj in meshes_with_armature:
            for modifier in mesh_obj.modifiers:
                if modifier.type == 'ARMATURE' and modifier.object == obj:
                    # 复制修改器
                    new_modifier = mesh_obj.modifiers.new(name=modifier.name + "_copy", type='ARMATURE')
                    new_modifier.object = modifier.object
                    new_modifier.use_vertex_groups = modifier.use_vertex_groups
                    new_modifier.use_bone_envelopes = modifier.use_bone_envelopes
                    break

        # 4. 切换到姿态模式设置A-Pose
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')

        # 5. 清除所有现有姿态
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.rot_clear()
        bpy.ops.pose.scale_clear()
        bpy.ops.pose.loc_clear()
        bpy.ops.pose.select_all(action='DESELECT')

        # 6. 为骨骼设置A-Pose旋转
        pose_bones = obj.pose.bones
        converted_bones = []

        for bone_type, bone_name in arm_bones.items():
            if bone_name and bone_name in pose_bones:
                bone = pose_bones[bone_name]
                bone.rotation_mode = 'XYZ'
                
                # 根据骨骼类型设置不同的旋转角度
                if bone_type == "left_upper_arm":
                    rotation_matrix = Matrix.Rotation(math.radians(37), 4, 'Y')
                elif bone_type == "right_upper_arm":
                    rotation_matrix = Matrix.Rotation(math.radians(-37), 4, 'Y')
                
                # 应用旋转矩阵
                bone.matrix = rotation_matrix @ bone.matrix
                
                converted_bones.append(bone_name)

        if not converted_bones:
            self.report({'WARNING'}, "没有找到匹配的骨骼可以转换")
            return {'CANCELLED'}

        # 7. 更新视图以确保姿态已应用
        context.view_layer.update()

        # 8. 应用第二个修改器（复制的修改器）来调整网格姿态
        try:
            for mesh_obj in meshes_with_armature:
                context.view_layer.objects.active = mesh_obj
                for modifier in mesh_obj.modifiers:
                    if modifier.type == 'ARMATURE' and modifier.object == obj and "_copy" in modifier.name:
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
                        break
        except RuntimeError as e:
            self.report({'ERROR'}, f"应用修改器时出错：{str(e)}")
            return {'CANCELLED'}

        # 9. 切换回骨骼对象
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')

        # 10. 应用当前姿态为新的静置姿态
        bpy.ops.pose.armature_apply()

        # 11. 清理临时创建的网格
        for mesh_obj in meshes_with_armature:
            if mesh_obj.get("is_temp_mesh"):
                bpy.data.objects.remove(mesh_obj, do_unlink=True)

        self.report({'INFO'}, f"已完成A-Pose转换并应用为新的静置姿态")
        return {'FINISHED'}