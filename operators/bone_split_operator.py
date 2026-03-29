import bpy
from mathutils import Vector
from . import weight_monitor


class OBJECT_OT_split_spine_shoulder(bpy.types.Operator):
    """切分脊柱和肩骨骼：spine upper → 上半身2+上半身3，shoulder → 肩P+肩+肩C
    执行后自动输出权重验证报告"""
    bl_idname = "object.split_spine_shoulder"
    bl_label = "3. 骨骼切分（spine/shoulder）"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        # 收集切分前的权重总和用于验证。
        # 这里必须同时看 上半身2 / 上半身3，避免在重复执行或已存在 上半身3
        # 的情况下，把“原本就在 上半身3 的权重”误算成新增权重。
        pre_weights = self._collect_weights(context, obj, ["上半身2", "上半身3"])

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = obj.data.edit_bones
        split_count = 0

        # === 1. 上半身2 → 上半身2 + 上半身3 ===
        ub2 = edit_bones.get("上半身2")
        ub3_existing = edit_bones.get("上半身3")
        spine_split_applied = False
        if ub2 and not ub3_existing:
            # 上半身2 占下半段，上半身3 占上半段（连接到首）
            mid = ub2.head.lerp(ub2.tail, 0.5)
            ub2_tail = mid.copy()
            ub3_head = mid.copy()
            ub3_tail = ub2.tail.copy()
            ub2_children = [(c.name, c.use_connect) for c in ub2.children]

            # 调整 上半身2
            ub2.tail = ub2_tail
            ub2.use_connect = False

            # 创建 上半身3
            ub3 = edit_bones.get("上半身3")
            if not ub3:
                ub3 = edit_bones.new("上半身3")
            ub3.head = ub3_head
            ub3.tail = ub3_tail
            ub3.parent = ub2
            ub3.use_connect = False
            ub3.use_deform = True

            # 把 上半身2 的子骨骼重新挂到 上半身3
            for child_name, child_connect in ub2_children:
                child = edit_bones.get(child_name)
                if child and child.name != "上半身3":
                    child.parent = ub3
                    child.use_connect = child_connect

            split_count += 1
            spine_split_applied = True

        # === 2. 肩骨骼细化：左肩/右肩 → 肩P.L/.R + 肩.L/.R + 肩C.L/.R ===
        # 结构参考 PMX：肩P（垂直向上，枢轴）→ 肩（水平指向手臂）→ 肩C（垂直向上，补偿）→ 腕
        vg_renames = []  # 记录需要同步的顶点组改名 [(old, new), ...]
        up_len = 0.08    # 枢轴/补偿骨向上的长度

        for side, side_jp in [("L", "左"), ("R", "右")]:
            # 找现有肩骨骼（重命名前叫 左肩/右肩）
            existing = (edit_bones.get(f"{side_jp}肩")
                        or edit_bones.get(f"肩P.{side}")
                        or edit_bones.get(f"肩.{side}"))
            arm = edit_bones.get(f"{side_jp}腕") or edit_bones.get(f"腕.{side}")
            if not existing or not arm:
                continue

            # 已经有完整三骨结构则跳过
            if (edit_bones.get(f"肩P.{side}") and edit_bones.get(f"肩.{side}")
                    and edit_bones.get(f"肩C.{side}")):
                continue

            sh_head = existing.head.copy()   # 肩起始点（胸部侧）
            sh_tail = existing.tail.copy()   # 肩末端（手臂侧）
            sh_parent = existing.parent      # 通常是 上半身3

            up_vec = Vector((0, 0, up_len))

            # 1. 将现有肩骨骼重命名为 肩.L/.R（主变形骨，水平指向手臂，保持原位置）
            old_name = existing.name
            new_name = f"肩.{side}"
            if old_name != new_name:
                existing.name = new_name
                vg_renames.append((old_name, new_name))
            existing.use_deform = True
            existing.use_connect = False

            # 2. 创建 肩P.L/.R（枢轴骨：在肩起始点垂直向上，父级=上半身3）
            shoulder_p = edit_bones.get(f"肩P.{side}")
            if not shoulder_p:
                shoulder_p = edit_bones.new(f"肩P.{side}")
            shoulder_p.head = sh_head
            shoulder_p.tail = sh_head + up_vec
            shoulder_p.parent = sh_parent
            shoulder_p.use_connect = False
            shoulder_p.use_deform = True

            # 3. 肩.L/.R 父级 → 肩P
            existing.parent = shoulder_p
            existing.use_connect = False

            # 4. 创建 肩C.L/.R（补偿骨：在腕起始点垂直向上，父级=肩）
            shoulder_c = edit_bones.get(f"肩C.{side}")
            if not shoulder_c:
                shoulder_c = edit_bones.new(f"肩C.{side}")
            shoulder_c.head = sh_tail
            shoulder_c.tail = sh_tail + up_vec
            shoulder_c.parent = existing
            shoulder_c.use_connect = False
            shoulder_c.use_deform = True

            # 5. 腕骨骼父级 → 肩C
            # 先断开 connect，防止 head 被吸附到 肩C.tail
            arm.use_connect = False
            arm.parent = shoulder_c
            # 显式恢复 arm.head 到肩关节处（= 肩.L tail = sh_tail）
            arm.head = sh_tail.copy()

            split_count += 1

        bpy.ops.object.mode_set(mode='OBJECT')

        # 同步顶点组改名（左肩→肩.L 等）
        for scene_obj in context.scene.objects:
            if scene_obj.type != 'MESH':
                continue
            for old_name, new_name in vg_renames:
                vg = scene_obj.vertex_groups.get(old_name)
                if vg:
                    vg.name = new_name

        # === 权重重分配：上半身2 的权重按比例分给 上半身2 + 上半身3 ===
        if spine_split_applied:
            self._redistribute_spine_weights(context, obj)

        # === 权重重分配：左腕/右腕 前臂部分转移给 左ひじ/右ひじ ===
        self._redistribute_arm_weights(context, obj)

        # === 权重验证报告 ===
        post_weights = self._collect_weights(context, obj, ["上半身2", "上半身3"])
        pre_total = sum(pre_weights.values())
        post_total = sum(post_weights.values())
        delta = abs(pre_total - post_total)

        if delta < 0.01 * max(pre_total, 1):
            status = "✅ 通过"
        else:
            status = f"⚠️ 差异 {delta:.4f}"

        self.report({'INFO'},
            f"骨骼切分完成（{split_count} 处）| 权重验证 {status} "
            f"| 切分前={pre_total:.4f} 切分后={post_total:.4f}")

        weight_monitor.auto_check_after_step(context, obj, "step_3", "骨骼切分")
        return {'FINISHED'}

    def _collect_weights(self, context, armature_obj, bone_names):
        """收集指定骨骼对应顶点组的权重总和"""
        totals = {name: 0.0 for name in bone_names}
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            has_armature_mod = any(
                m.type == 'ARMATURE' and m.object == armature_obj
                for m in obj.modifiers
            )
            if not has_armature_mod:
                continue
            for bone_name in bone_names:
                vg = obj.vertex_groups.get(bone_name)
                if not vg:
                    continue
                for v in obj.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index:
                            totals[bone_name] += g.weight
        return totals

    def _redistribute_arm_weights(self, context, armature_obj):
        """将 左腕/右腕 中位于前臂区域的顶点权重，按投影比例转移到 左ひじ/右ひじ"""
        arm_data = armature_obj.data
        mw = armature_obj.matrix_world

        for side_jp in ['左', '右']:
            arm_bone   = arm_data.bones.get(f'{side_jp}腕')
            elbow_bone = arm_data.bones.get(f'{side_jp}ひじ')
            if not arm_bone or not elbow_bone:
                continue

            # 肘关节起点（= 上臂末端）和前臂末端，世界坐标
            elbow_head_w = mw @ elbow_bone.head_local
            elbow_tail_w = mw @ elbow_bone.tail_local
            forearm_vec  = elbow_tail_w - elbow_head_w
            forearm_len  = forearm_vec.length
            if forearm_len < 1e-6:
                continue
            forearm_dir = forearm_vec.normalized()

            for scene_obj in context.scene.objects:
                if scene_obj.type != 'MESH':
                    continue
                has_arm_mod = any(
                    m.type == 'ARMATURE' and m.object == armature_obj
                    for m in scene_obj.modifiers
                )
                if not has_arm_mod:
                    continue

                vg_arm = scene_obj.vertex_groups.get(f'{side_jp}腕')
                if not vg_arm:
                    continue

                vg_elbow = scene_obj.vertex_groups.get(f'{side_jp}ひじ')
                if not vg_elbow:
                    vg_elbow = scene_obj.vertex_groups.new(name=f'{side_jp}ひじ')

                for v in scene_obj.data.vertices:
                    w_arm = 0.0
                    for g in v.groups:
                        if g.group == vg_arm.index:
                            w_arm = g.weight
                            break
                    if w_arm <= 0:
                        continue

                    # 顶点世界坐标投影到前臂轴
                    world_pos = scene_obj.matrix_world @ v.co
                    proj = (world_pos - elbow_head_w).dot(forearm_dir)

                    if proj <= 0:
                        # 在肘关节之前（上臂区域），保持在 腕
                        continue

                    # 在前臂区域，按距离比例分配
                    ratio_elbow = min(1.0, proj / forearm_len)
                    ratio_arm   = 1.0 - ratio_elbow

                    if ratio_arm > 0:
                        vg_arm.add([v.index], w_arm * ratio_arm, 'REPLACE')
                    else:
                        vg_arm.remove([v.index])

                    vg_elbow.add([v.index], w_arm * ratio_elbow, 'REPLACE')

    def _redistribute_spine_weights(self, context, armature_obj):
        """将上半身2/上半身3的总权重按高度重新分配。

        这里必须把已有的 上半身3 权重一起纳入再分配，否则在重复执行
        或前一步已经创建过 上半身3 权重时，会出现总权重被叠加放大的问题。
        """
        # 需要在 object mode 下操作
        # 获取 上半身2 骨骼的位置信息（用于计算切分点）
        arm_data = armature_obj.data
        ub2_bone = arm_data.bones.get("上半身2")
        ub3_bone = arm_data.bones.get("上半身3")
        if not ub2_bone or not ub3_bone:
            return

        # 切分点（上半身3 头部）在世界坐标中的 Z 值
        # ub2 范围: [ub2.head_local.z, ub2.tail_local.z]
        # ub3 范围: [ub3.head_local.z, ub3.tail_local.z]
        ub2_head_z = (armature_obj.matrix_world @ ub2_bone.head_local).z
        ub3_tail_z = (armature_obj.matrix_world @ ub3_bone.tail_local).z
        split_z = (armature_obj.matrix_world @ ub3_bone.head_local).z

        total_range = ub3_tail_z - ub2_head_z
        if total_range <= 0:
            return

        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
            has_armature_mod = any(
                m.type == 'ARMATURE' and m.object == armature_obj
                for m in obj.modifiers
            )
            if not has_armature_mod:
                continue

            vg2 = obj.vertex_groups.get("上半身2")
            if not vg2:
                continue

            # 确保 上半身3 顶点组存在
            vg3 = obj.vertex_groups.get("上半身3")
            if not vg3:
                vg3 = obj.vertex_groups.new(name="上半身3")

            # 遍历所有顶点，按 (上半身2 + 上半身3) 总量重新分配
            for v in obj.data.vertices:
                w2 = 0.0
                w3 = 0.0
                for g in v.groups:
                    if g.group == vg2.index:
                        w2 = g.weight
                    elif g.group == vg3.index:
                        w3 = g.weight

                source_total = w2 + w3
                if source_total <= 0:
                    continue

                # 顶点世界坐标 Z
                world_z = (obj.matrix_world @ v.co).z
                # 计算属于 上半身3 的比例（越靠上比例越高）
                ratio3 = max(0.0, min(1.0, (world_z - split_z) / (ub3_tail_z - split_z + 1e-6)))
                ratio2 = 1.0 - ratio3

                # 设置新权重
                if ratio2 > 0:
                    vg2.add([v.index], source_total * ratio2, 'REPLACE')
                else:
                    vg2.remove([v.index])

                if ratio3 > 0:
                    vg3.add([v.index], source_total * ratio3, 'REPLACE')
                else:
                    vg3.remove([v.index])
