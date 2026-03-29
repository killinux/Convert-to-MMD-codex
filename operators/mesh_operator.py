import bpy


class OBJECT_OT_merge_meshes(bpy.types.Operator):
    """将所有绑定到同一骨架的网格对象合并为一个（保留顶点组/材质槽/Shape Keys）"""
    bl_idname = "object.merge_meshes"
    bl_label = "8. 网格合并"

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        # 找到所有绑定到此骨架的网格
        mesh_objects = [
            obj for obj in context.scene.objects
            if obj.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == armature
                for m in obj.modifiers
            )
        ]

        if len(mesh_objects) < 2:
            self.report({'INFO'}, f"只有 {len(mesh_objects)} 个网格，无需合并")
            return {'CANCELLED'}

        # 取消所有选择（直接操作属性，不依赖 3D View 上下文）
        for obj in context.scene.objects:
            obj.select_set(False)

        # 选择所有要合并的网格
        for obj in mesh_objects:
            obj.select_set(True)

        # 将第一个网格作为活动对象（join 会保留活动对象）
        context.view_layer.objects.active = mesh_objects[0]

        # 执行合并
        bpy.ops.object.join()

        # 合并后重新选择骨架作为活动对象
        for obj in context.scene.objects:
            obj.select_set(False)
        armature.select_set(True)
        context.view_layer.objects.active = armature

        self.report({'INFO'}, f"已将 {len(mesh_objects)} 个网格合并为 1 个")
        return {'FINISHED'}
