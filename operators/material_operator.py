import bpy


class OBJECT_OT_convert_materials_to_mmd(bpy.types.Operator):
    """将所有网格材质转换为 MMD 格式（调用 mmd_tools API）"""
    bl_idname = "object.convert_materials_to_mmd"
    bl_label = "9. 材质转换（→MMD格式）"

    def execute(self, context):
        # 检查 mmd_tools 是否可用
        try:
            from mmd_tools.core.material import FnMaterial
        except ImportError:
            self.report({'ERROR'}, "请先安装 mmd_tools 插件")
            return {'CANCELLED'}

        # mmd_material 属性未注册说明 mmd_tools 未启用，尝试自动启用
        rna_ids = [p.identifier for p in bpy.types.Material.bl_rna.properties]
        if 'mmd_material' not in rna_ids:
            try:
                bpy.ops.preferences.addon_enable(module="mmd_tools")
            except Exception:
                pass
            rna_ids = [p.identifier for p in bpy.types.Material.bl_rna.properties]
            if 'mmd_material' not in rna_ids:
                self.report({'ERROR'}, "mmd_tools 未启用，请在 Preferences → Add-ons 中启用后重试")
                return {'CANCELLED'}

        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            obj for obj in context.scene.objects
            if obj.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == armature
                for m in obj.modifiers
            )
        ]

        if not mesh_objects:
            self.report({'WARNING'}, "未找到绑定到此骨架的网格对象")
            return {'CANCELLED'}

        converted = 0
        for obj in mesh_objects:
            for mat_slot in obj.material_slots:
                mat = mat_slot.material
                if not mat:
                    continue
                try:
                    FnMaterial.convert_to_mmd_material(mat)
                    converted += 1
                except Exception as e:
                    self.report({'WARNING'}, f"材质 '{mat.name}' 转换失败: {e}")

        self.report({'INFO'}, f"已转换 {converted} 个材质为 MMD 格式")
        return {'FINISHED'}
