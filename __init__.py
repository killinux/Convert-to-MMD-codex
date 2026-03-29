bl_info = {
    "name": "Convert to MMD",
    "author": "UITCIS(空想幻灵)",
    "version": (2, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar",
    "description": "Plugin to automatically rename and complete missing bones for MMD format",
    "warning": "",
    "wiki_url": "",
    "category": "Animation"
}

import bpy
import os  # 新增：导入os模块

from .operators import preset_operator
from .operators import bone_operator
from .operators import collection_operator
from .operators import ik_operator
from .operators import pose_operator
from .operators import clear_unweighted_bones_operator
from .operators import bone_split_operator
from .operators import twist_bone_operator
from .operators import weight_verify_operator
from .operators import mesh_operator
from .operators import material_operator
from .operators import auto_convert_operator
from .operators import weight_monitor
from .operators import semantic_debug_operator
from . import ui_panel
from . import bone_map_and_group
from . import bone_utils
def register_properties(properties_dict):
    """Registers properties dynamically using a dictionary."""
    for prop_name, prop_value in properties_dict.items():
        setattr(bpy.types.Scene, prop_name, bpy.props.StringProperty(default=prop_value))


def unregister_properties(properties_list):
    """Unregisters properties dynamically using a list of property names."""
    for prop_name in properties_list:
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)

def register():
    # 注册所有类
    bpy.utils.register_class(ui_panel.OBJECT_PT_skeleton_hierarchy)
    bpy.utils.register_class(ui_panel.OBJECT_OT_load_preset)
    bpy.utils.register_class(bone_operator.OBJECT_OT_rename_to_mmd)
    bpy.utils.register_class(bone_operator.OBJECT_OT_complete_missing_bones)
    bpy.utils.register_class(bone_operator.OBJECT_OT_disable_xps_helper_bones)
    bpy.utils.register_class(bone_operator.OBJECT_OT_transfer_foretwist_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_check_orphan_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_fix_orphan_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_check_missing_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_fix_missing_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_check_fix_missing_weights)
    bpy.utils.register_class(bone_operator.OBJECT_OT_cleanup_leg_conflict)
    bpy.utils.register_class(bone_operator.OBJECT_OT_check_hip_blend_zone)
    bpy.utils.register_class(bone_operator.OBJECT_OT_fix_hip_blend_zone)
    bpy.utils.register_class(bone_operator.OBJECT_OT_manual_weight_transfer)
    bpy.utils.register_class(preset_operator.OBJECT_OT_fill_from_selection_specific)
    bpy.utils.register_class(preset_operator.OBJECT_OT_export_preset)
    bpy.utils.register_class(preset_operator.OBJECT_OT_import_preset)
    bpy.utils.register_class(preset_operator.OBJECT_OT_use_mmd_tools_convert)
    bpy.utils.register_class(pose_operator.OBJECT_OT_convert_to_apose)
    bpy.utils.register_class(pose_operator.OBJECT_OT_check_arm_straightness)
    bpy.utils.register_class(pose_operator.OBJECT_OT_fix_elbow_straightness)
    bpy.utils.register_class(pose_operator.OBJECT_OT_fix_wrist_straightness)
    bpy.utils.register_class(pose_operator.OBJECT_OT_fix_arm_straightness)
    bpy.utils.register_class(ik_operator.OBJECT_OT_add_ik)
    bpy.utils.register_class(collection_operator.OBJECT_OT_create_bone_group)
    bpy.utils.register_class(clear_unweighted_bones_operator.OBJECT_OT_clear_unweighted_bones)
    bpy.utils.register_class(clear_unweighted_bones_operator.OBJECT_OT_merge_single_child_bones)
    bpy.utils.register_class(bone_split_operator.OBJECT_OT_split_spine_shoulder)
    bpy.utils.register_class(twist_bone_operator.OBJECT_OT_add_twist_bones)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_verify_weights)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_clean_orphan_vertex_groups)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_fix_nondeform_weights)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_compare_bone_weights)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_highlight_conflict_vertices)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_clear_conflict_highlight)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_pose_test)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_pose_test_reset)
    bpy.utils.register_class(weight_verify_operator.OBJECT_OT_probe_d_bone_pose_response)
    bpy.utils.register_class(mesh_operator.OBJECT_OT_merge_meshes)
    bpy.utils.register_class(material_operator.OBJECT_OT_convert_materials_to_mmd)
    bpy.utils.register_class(auto_convert_operator.OBJECT_OT_auto_convert)
    bpy.utils.register_class(weight_monitor.OBJECT_OT_weight_health_check)
    bpy.utils.register_class(weight_monitor.OBJECT_OT_weight_clear_monitor)
    bpy.utils.register_class(semantic_debug_operator.OBJECT_OT_debug_infer_semantic)
    bpy.utils.register_class(semantic_debug_operator.OBJECT_OT_fill_mapping_from_semantic)
    # 注册动态属性
    bones = preset_operator.get_bones_list()
    register_properties(bones)

    # 注册 EnumProperty
    bpy.types.Scene.preset_enum = bpy.props.EnumProperty(
        name="预设",
        description="选择一个预设",
        items=get_preset_enum,
        update=preset_enum_update  # 使用显式函数替代 lambda
    )
    bpy.types.Scene.my_enum = bpy.props.EnumProperty(
        name="模式",
        description="选择操作模式",
        items=[
            ('option1', "骨骼映射", "进行骨骼映射"),
            ('option2', "骨骼清理", "进行骨骼清理")
        ],
        default='option1'
    )
    # 手臂关节检测结果属性
    bpy.types.Scene.arm_check_done        = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.arm_check_has_problem = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.arm_check_left_bend   = bpy.props.FloatProperty(default=0.0)
    bpy.types.Scene.arm_check_right_bend  = bpy.props.FloatProperty(default=0.0)
    bpy.types.Scene.arm_check_left_wrist  = bpy.props.FloatProperty(default=0.0)
    bpy.types.Scene.arm_check_right_wrist = bpy.props.FloatProperty(default=0.0)
    # 权重验证结果属性
    bpy.types.Scene.weight_verify_done = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.weight_verify_bones_without_vg = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_verify_orphan_vgs = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_verify_orphan_names = bpy.props.StringProperty(default="")
    bpy.types.Scene.weight_verify_total_verts = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_verify_unweighted_verts = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_verify_nondeform_verts = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_verify_nondeform_names = bpy.props.StringProperty(default="")
    # 逐骨对比属性
    bpy.types.Scene.weight_ref_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="参考骨架",
        description="用于对比权重分布的参考 MMD 模型骨架",
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    bpy.types.Scene.semantic_source_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="源骨架",
        description="待转换的源骨架",
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    bpy.types.Scene.semantic_target_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="目标骨架",
        description="参考 PMX / MMD 目标骨架",
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    bpy.types.Scene.weight_compare_done = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.weight_compare_result = bpy.props.StringProperty(default="")
    # 冲突顶点高亮属性
    bpy.types.Scene.weight_conflict_done = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.weight_conflict_count = bpy.props.IntProperty(default=0)
    # 手动权重转移
    bpy.types.Scene.weight_manual_src = bpy.props.StringProperty(name="源骨骼", default="")
    bpy.types.Scene.weight_manual_dst = bpy.props.StringProperty(name="目标骨骼", default="")
    # 孤立骨检查结果
    bpy.types.Scene.weight_orphan_check_done = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.weight_orphan_count = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_orphan_preview = bpy.props.StringProperty(default="")
    # 缺失权重检查结果
    bpy.types.Scene.weight_missing_check_done = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.weight_missing_count = bpy.props.IntProperty(default=0)
    bpy.types.Scene.weight_missing_names = bpy.props.StringProperty(default="")
    # 髋部渐变区检查结果
    bpy.types.Scene.hip_blend_check_done   = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.hip_blend_left_count   = bpy.props.IntProperty(default=0)
    bpy.types.Scene.hip_blend_right_count  = bpy.props.IntProperty(default=0)
    bpy.types.Scene.hip_blend_left_binary  = bpy.props.IntProperty(default=0)
    bpy.types.Scene.hip_blend_right_binary = bpy.props.IntProperty(default=0)
    # 权重健康监控
    bpy.types.Scene.wm_step_status = bpy.props.StringProperty(default="{}")
    bpy.types.Scene.wm_last_check_result = bpy.props.StringProperty(default="")
    bpy.types.Scene.semantic_debug_preview = bpy.props.StringProperty(default="")
    bpy.types.Scene.semantic_debug_count = bpy.props.IntProperty(default=0)
    bpy.types.Scene.semantic_debug_canonical = bpy.props.StringProperty(default="")
    bpy.types.Scene.semantic_target_preview = bpy.props.StringProperty(default="")
    bpy.types.Scene.semantic_target_count = bpy.props.IntProperty(default=0)
    bpy.types.Scene.semantic_plan_preview = bpy.props.StringProperty(default="")
    bpy.types.Scene.semantic_plan_json = bpy.props.StringProperty(default="")
    bpy.types.Scene.auto_convert_allow_risky = bpy.props.BoolProperty(
        name="继续高风险步骤",
        description="勾选后，一键流程会继续执行 2.5 / 6.5 / 权重修复 等高风险步骤",
        default=False,
    )
    bpy.types.Scene.d_bone_pose_probe_result = bpy.props.StringProperty(default="")

def unregister():
    # 注销所有类
    bpy.utils.unregister_class(ui_panel.OBJECT_PT_skeleton_hierarchy)
    bpy.utils.unregister_class(ui_panel.OBJECT_OT_load_preset)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_rename_to_mmd)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_complete_missing_bones)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_disable_xps_helper_bones)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_transfer_foretwist_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_check_orphan_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_fix_orphan_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_check_missing_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_fix_missing_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_check_fix_missing_weights)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_cleanup_leg_conflict)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_check_hip_blend_zone)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_fix_hip_blend_zone)
    bpy.utils.unregister_class(bone_operator.OBJECT_OT_manual_weight_transfer)
    bpy.utils.unregister_class(preset_operator.OBJECT_OT_fill_from_selection_specific)
    bpy.utils.unregister_class(preset_operator.OBJECT_OT_export_preset)
    bpy.utils.unregister_class(preset_operator.OBJECT_OT_import_preset)
    bpy.utils.unregister_class(preset_operator.OBJECT_OT_use_mmd_tools_convert)
    bpy.utils.unregister_class(pose_operator.OBJECT_OT_convert_to_apose)
    bpy.utils.unregister_class(pose_operator.OBJECT_OT_check_arm_straightness)
    bpy.utils.unregister_class(pose_operator.OBJECT_OT_fix_elbow_straightness)
    bpy.utils.unregister_class(pose_operator.OBJECT_OT_fix_wrist_straightness)
    bpy.utils.unregister_class(pose_operator.OBJECT_OT_fix_arm_straightness)
    bpy.utils.unregister_class(ik_operator.OBJECT_OT_add_ik)
    bpy.utils.unregister_class(collection_operator.OBJECT_OT_create_bone_group)
    bpy.utils.unregister_class(clear_unweighted_bones_operator.OBJECT_OT_clear_unweighted_bones)
    bpy.utils.unregister_class(clear_unweighted_bones_operator.OBJECT_OT_merge_single_child_bones)
    bpy.utils.unregister_class(bone_split_operator.OBJECT_OT_split_spine_shoulder)
    bpy.utils.unregister_class(twist_bone_operator.OBJECT_OT_add_twist_bones)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_verify_weights)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_clean_orphan_vertex_groups)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_fix_nondeform_weights)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_compare_bone_weights)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_highlight_conflict_vertices)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_clear_conflict_highlight)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_pose_test)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_pose_test_reset)
    bpy.utils.unregister_class(weight_verify_operator.OBJECT_OT_probe_d_bone_pose_response)
    bpy.utils.unregister_class(mesh_operator.OBJECT_OT_merge_meshes)
    bpy.utils.unregister_class(material_operator.OBJECT_OT_convert_materials_to_mmd)
    bpy.utils.unregister_class(auto_convert_operator.OBJECT_OT_auto_convert)
    bpy.utils.unregister_class(weight_monitor.OBJECT_OT_weight_health_check)
    bpy.utils.unregister_class(weight_monitor.OBJECT_OT_weight_clear_monitor)
    bpy.utils.unregister_class(semantic_debug_operator.OBJECT_OT_debug_infer_semantic)
    bpy.utils.unregister_class(semantic_debug_operator.OBJECT_OT_fill_mapping_from_semantic)
    del bpy.types.Scene.my_enum
    for prop in ["weight_verify_done", "weight_verify_bones_without_vg", "weight_verify_orphan_vgs",
                 "weight_verify_orphan_names", "weight_verify_total_verts",
                 "weight_verify_unweighted_verts",
                 "weight_verify_nondeform_verts", "weight_verify_nondeform_names",
                 "weight_ref_armature", "weight_compare_done", "weight_compare_result",
                 "semantic_source_armature", "semantic_target_armature",
                 "weight_conflict_done", "weight_conflict_count",
                 "weight_manual_src", "weight_manual_dst",
                 "weight_orphan_check_done", "weight_orphan_count", "weight_orphan_preview",
                 "weight_missing_check_done", "weight_missing_count", "weight_missing_names",
                 "hip_blend_check_done", "hip_blend_left_count", "hip_blend_right_count",
                 "hip_blend_left_binary", "hip_blend_right_binary",
                 "wm_step_status", "wm_last_check_result",
                 "semantic_debug_preview", "semantic_debug_count", "semantic_debug_canonical",
                 "semantic_target_preview", "semantic_target_count", "semantic_plan_preview",
                 "semantic_plan_json", "auto_convert_allow_risky", "d_bone_pose_probe_result",
                 "arm_check_done", "arm_check_has_problem",
                 "arm_check_left_bend", "arm_check_right_bend",
                 "arm_check_left_wrist", "arm_check_right_wrist"]:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    # 注销动态属性
    bones = preset_operator.get_bones_list()
    unregister_properties(bones)

    # 注销 EnumProperty
    if hasattr(bpy.types.Scene, "preset_enum"):
        delattr(bpy.types.Scene, "preset_enum")

# 新增 EnumProperty 定义
def get_preset_enum(self, context):
    # 修改: 确保路径解析正确，使用bpy.utils.script_path_user()获取用户脚本目录
    script_dir = os.path.dirname(os.path.realpath(__file__))
    presets_dir = os.path.join(script_dir, "presets")
    preset_items = []
    if os.path.exists(presets_dir):
        for preset_file in os.listdir(presets_dir):
            if preset_file.endswith('.json'):
                # 修改: 使用文件名作为选项的标识符
                preset_name = os.path.splitext(preset_file)[0]
                preset_items.append((preset_name, preset_name, ""))
    return preset_items

# 修改: 将 update 回调函数改为显式函数定义
def preset_enum_update(self, context):
    # 调用加载预设的操作符
    bpy.ops.object.load_preset(preset_name=self.preset_enum)
    return None  # 确保返回值为 None

if __name__ == "__main__":
    register()
