import bpy
from mathutils import Vector


class OBJECT_OT_add_twist_bones(bpy.types.Operator):
    """添加 MMD 手臂/手腕扭转骨骼（腕捩/手捩系列）"""
    bl_idname = "object.add_twist_bones"
    bl_label = "6. 添加扭转骨骼（腕捩/手捩）"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = obj.data.edit_bones
        created = 0

        for side, side_jp in [("L", "左"), ("R", "右")]:
            arm_bone   = edit_bones.get(f"{side_jp}腕")  or edit_bones.get(f"腕.{side}")
            elbow_bone = edit_bones.get(f"{side_jp}ひじ") or edit_bones.get(f"ひじ.{side}")
            wrist_bone = edit_bones.get(f"{side_jp}手首") or edit_bones.get(f"手首.{side}")

            if not arm_bone or not elbow_bone:
                continue

            arm_h   = arm_bone.head.copy()
            arm_t   = arm_bone.tail.copy()   # = elbow head
            el_h    = elbow_bone.head.copy()
            el_t    = elbow_bone.tail.copy()  # = wrist head

            # 用骨骼长度的 37% 作为朝上子骨的显示长度（与 PMX 参考比例一致）
            arm_len   = (arm_t - arm_h).length
            elbow_len = (el_t - el_h).length
            up_len    = max(arm_len * 0.37, 0.04)
            up_vec    = Vector((0, 0, up_len))

            # ── 腕捩.L（上臂扭转主骨）：在 腕 60% 处，朝腕方向，deform=True ──
            twist_arm_head = arm_h.lerp(arm_t, 0.60)
            twist_arm_tail = arm_h.lerp(arm_t, 1.0)   # 与 腕.L 同方向，指向 elbow
            b = self._create_bone(edit_bones, f"腕捩.{side}",
                                  twist_arm_head, twist_arm_tail,
                                  parent_name=arm_bone.name, use_deform=True)
            if b: created += 1

            # 腕捩1/2/3.L：分布在 腕 的 32%/52%/72% 处，尾部垂直向上
            for i, ratio in enumerate([0.32, 0.52, 0.72], start=1):
                bh = arm_h.lerp(arm_t, ratio)
                b = self._create_bone(edit_bones, f"腕捩{i}.{side}",
                                      bh, bh + up_vec,
                                      parent_name=arm_bone.name, use_deform=True)
                if b: created += 1

            # _dummy_腕捩1/2/3.L：head = 腕捩.L head，尾部垂直向上，parent=腕捩
            for i in range(1, 4):
                b = self._create_bone(edit_bones, f"_dummy_腕捩{i}.{side}",
                                      twist_arm_head, twist_arm_head + up_vec,
                                      parent_name=f"腕捩.{side}", use_deform=False)
                if b: created += 1

            # _shadow_腕捩1/2/3.L：head = 腕捩.L head，尾部垂直向上，parent=腕
            for i in range(1, 4):
                b = self._create_bone(edit_bones, f"_shadow_腕捩{i}.{side}",
                                      twist_arm_head, twist_arm_head + up_vec,
                                      parent_name=arm_bone.name, use_deform=False)
                if b: created += 1

            # ── 手捩.L（前臂扭转主骨）：在 ひじ 60% 处，朝手腕方向，deform=True ──
            twist_el_head = el_h.lerp(el_t, 0.60)
            twist_el_tail = el_h.lerp(el_t, 1.0)   # 与 ひじ.L 同方向，指向 wrist
            b = self._create_bone(edit_bones, f"手捩.{side}",
                                  twist_el_head, twist_el_tail,
                                  parent_name=elbow_bone.name, use_deform=True)
            if b: created += 1

            # 手捩1/2/3.L：分布在 ひじ 的 33%/53%/74% 处，尾部垂直向上
            elbow_up = max(elbow_len * 0.37, 0.04)
            elbow_up_vec = Vector((0, 0, elbow_up))
            for i, ratio in enumerate([0.33, 0.53, 0.74], start=1):
                bh = el_h.lerp(el_t, ratio)
                b = self._create_bone(edit_bones, f"手捩{i}.{side}",
                                      bh, bh + elbow_up_vec,
                                      parent_name=elbow_bone.name, use_deform=True)
                if b: created += 1

            # _dummy_手捩1/2/3.L：head = 手捩.L head，尾部垂直向上，parent=手捩
            for i in range(1, 4):
                b = self._create_bone(edit_bones, f"_dummy_手捩{i}.{side}",
                                      twist_el_head, twist_el_head + elbow_up_vec,
                                      parent_name=f"手捩.{side}", use_deform=False)
                if b: created += 1

            # _shadow_手捩1/2/3.L：head = 手捩.L head，尾部垂直向上，parent=ひじ
            for i in range(1, 4):
                b = self._create_bone(edit_bones, f"_shadow_手捩{i}.{side}",
                                      twist_el_head, twist_el_head + elbow_up_vec,
                                      parent_name=elbow_bone.name, use_deform=False)
                if b: created += 1

            # ── ダミー.L（手腕 dummy 骨）──
            if wrist_bone:
                b = self._create_bone(edit_bones, f"ダミー.{side}",
                                      wrist_bone.head.copy(),
                                      wrist_bone.head + Vector((0, 0, -0.03)),
                                      parent_name=wrist_bone.name, use_deform=False)
                if b: created += 1

        bpy.ops.object.mode_set(mode='OBJECT')

        # 添加扭转约束（在 pose mode）
        bpy.ops.object.mode_set(mode='POSE')
        self._add_twist_constraints(obj)
        bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, f"扭转骨骼创建完成，共 {created} 个骨骼")
        return {'FINISHED'}

    def _create_bone(self, edit_bones, name, head, tail, parent_name=None, use_deform=True):
        """创建骨骼，已存在则跳过"""
        if edit_bones.get(name):
            return None
        bone = edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        bone.use_connect = False
        bone.use_deform = use_deform
        if parent_name:
            parent = edit_bones.get(parent_name)
            if parent:
                bone.parent = parent
        return bone

    def _add_twist_constraints(self, obj):
        """为扭转主骨添加 COPY_ROTATION 约束"""
        pose_bones = obj.pose.bones

        for side, side_jp in [("L", "左"), ("R", "右")]:
            arm_name   = f"{side_jp}腕"
            elbow_name = f"{side_jp}ひじ"

            # 腕捩 跟随 腕 的 Y 轴旋转（0.5 比例）
            nenja_arm_name = f"腕捩.{side}"
            if nenja_arm_name in pose_bones and arm_name in pose_bones:
                pb = pose_bones[nenja_arm_name]
                if not any(c.type == 'COPY_ROTATION' for c in pb.constraints):
                    c = pb.constraints.new('COPY_ROTATION')
                    c.target = obj
                    c.subtarget = arm_name
                    c.use_x = False
                    c.use_y = True
                    c.use_z = False
                    c.mix_mode = 'REPLACE'
                    c.target_space = 'LOCAL'
                    c.owner_space = 'LOCAL'
                    c.influence = 0.5

            # 手捩 跟随 ひじ 的 Y 轴旋转（0.5 比例）
            nenja_wrist_name = f"手捩.{side}"
            if nenja_wrist_name in pose_bones and elbow_name in pose_bones:
                pb = pose_bones[nenja_wrist_name]
                if not any(c.type == 'COPY_ROTATION' for c in pb.constraints):
                    c = pb.constraints.new('COPY_ROTATION')
                    c.target = obj
                    c.subtarget = elbow_name
                    c.use_x = False
                    c.use_y = True
                    c.use_z = False
                    c.mix_mode = 'REPLACE'
                    c.target_space = 'LOCAL'
                    c.owner_space = 'LOCAL'
                    c.influence = 0.5
