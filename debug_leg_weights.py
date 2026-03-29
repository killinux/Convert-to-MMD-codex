"""
腿部权重逐步诊断脚本
每执行一个转换步骤后，在 Blender 脚本编辑器里运行一次。
会打印：
  - 大腿区 / 膝盖区 / 小腿区 的代表顶点权重
  - 权重总和 & 异常标记
  - 左右侧串权检测

使用方法：
  1. 在 Blender Outliner 中选中 集合1 里的骨架
  2. 在脚本编辑器里运行本脚本
  3. 每执行一个转换步骤后重新运行，对比输出变化
"""

import bpy

# ─────────────────────────────────────────────────────────────────────────────
# 配置：要监控的骨骼 & Z 采样区间
# ─────────────────────────────────────────────────────────────────────────────
WATCH_BONES = [
    "足D.L", "足D.R",
    "ひざD.L", "ひざD.R",
    "足首D.L", "足首D.R",
    "下半身",
    "左足",  "右足",   # FK骨（XPS阶段有，MMD阶段应转为D系）
    "左ひざ", "右ひざ",
    "leg_L", "leg_R",  # 某些XPS别名
    "thigh_L", "thigh_R",
    "calf_L",  "calf_R",
]

# 右侧腿 Z 区间（以 Blender world space 为准，按实际模型调整）
# 脚本会自动从骨架骨骼推算，这里只是备用默认值
THIGH_Z_RANGE   = None   # 自动推算
KNEE_Z_RANGE    = None   # 自动推算
SHIN_Z_RANGE    = None   # 自动推算


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：从骨架推算各区间
# ─────────────────────────────────────────────────────────────────────────────
def get_bone_z(arm, bone_names):
    """返回骨骼 head/tail 的 world Z，取第一个找到的"""
    for name in bone_names:
        b = arm.data.bones.get(name)
        if b:
            hz = (arm.matrix_world @ b.head_local).z
            tz = (arm.matrix_world @ b.tail_local).z
            return min(hz, tz), max(hz, tz)
    return None, None


def build_z_ranges(arm):
    # 尝试 右足 (XPS) 或 足D.R (MMD) 作为大腿参考
    thigh_min, thigh_max = get_bone_z(arm, ["右足", "足D.R", "thigh_R", "leg_R"])
    knee_min,  knee_max  = get_bone_z(arm, ["右ひざ", "ひざD.R", "calf_R"])
    ankle_min, ankle_max = get_bone_z(arm, ["右足首", "足首D.R", "foot_R"])

    if thigh_min is None:
        return None, None, None

    # 大腿区：thigh 骨骼范围
    z_thigh = (thigh_min, thigh_max)
    # 膝盖区：大腿末端附近 ±15% thigh长度
    if thigh_min is not None and thigh_max is not None:
        half = (thigh_max - thigh_min) * 0.2
        z_knee = (thigh_min - half, thigh_min + half)
    else:
        z_knee = None
    # 小腿区：knee骨骼范围（如果有）
    z_shin = (knee_min, knee_max) if knee_min is not None else None

    return z_thigh, z_knee, z_shin


# ─────────────────────────────────────────────────────────────────────────────
# 核心：采集顶点权重，输出报告
# ─────────────────────────────────────────────────────────────────────────────
def analyze_zone(label, obj, arm, z_range, side="R", max_samples=8):
    """采集指定 Z 区间内、指定侧的代表顶点，输出权重明细"""
    if z_range is None:
        return

    z_min, z_max = z_range
    mw = obj.matrix_world

    # 构建 vg_index → name 映射
    idx_map = {}
    for name in WATCH_BONES:
        vg = obj.vertex_groups.get(name)
        if vg:
            idx_map[vg.index] = name

    if not idx_map:
        print(f"  [{label}] 网格 {obj.name} 无监控骨骼的顶点组")
        return

    # 筛选目标侧的顶点（右侧 X < 0，左侧 X > 0，MMD 坐标系）
    results = []
    for v in obj.data.vertices:
        co = mw @ v.co
        if co.z < z_min or co.z > z_max:
            continue
        if side == "R" and co.x > 0.05:
            continue
        if side == "L" and co.x < -0.05:
            continue

        weights = {}
        total = 0.0
        for g in v.groups:
            if g.group in idx_map and g.weight > 0.001:
                weights[idx_map[g.group]] = round(g.weight, 4)
                total += g.weight

        if not weights:
            continue
        results.append((co.z, co.x, total, weights))

    if not results:
        print(f"  [{label}] 无顶点（Z={z_min:.3f}~{z_max:.3f} {side}侧）")
        return

    results.sort(key=lambda x: x[0])  # 按Z升序

    # 均匀采样 max_samples 个
    step = max(1, len(results) // max_samples)
    sampled = results[::step][:max_samples]

    print(f"\n  ── {label} ({side}侧, {len(results)}顶点, 采样{len(sampled)}个) ──")
    any_bad = False
    for z, x, total, weights in sampled:
        flag = ""
        if total > 1.05:
            flag = "  ⚠️ 超重!"
        elif total < 0.80:
            flag = "  ⚠️ 欠重!"
        elif "足D.R" in weights and "足D.L" in weights:
            flag = "  ⚠️ 左右串权!"
        elif side == "R" and "足D.L" in weights and weights.get("足D.L", 0) > 0.05:
            flag = "  ⚠️ 右侧有足D.L!"
        elif side == "L" and "足D.R" in weights and weights.get("足D.R", 0) > 0.05:
            flag = "  ⚠️ 左侧有足D.R!"
        if flag:
            any_bad = True
        # 只显示有值的骨骼
        w_str = "  ".join(f"{k}={v:.3f}" for k, v in sorted(weights.items(), key=lambda x: -x[1]))
        print(f"    Z={z:.3f} X={x:.3f} 总={total:.3f}  {w_str}{flag}")

    if not any_bad:
        print(f"    ✅ 采样顶点权重正常")


def analyze_cross_contamination(obj, mw):
    """检测：左侧顶点（X > 0.02）有 足D.R，或右侧（X < -0.02）有 足D.L"""
    vg_dl = obj.vertex_groups.get("足D.L")
    vg_dr = obj.vertex_groups.get("足D.R")
    if not vg_dl and not vg_dr:
        return

    idx_l = vg_dl.index if vg_dl else -1
    idx_r = vg_dr.index if vg_dr else -1

    bad_l_on_r = []  # 右侧有 足D.L
    bad_r_on_l = []  # 左侧有 足D.R

    for v in obj.data.vertices:
        co = mw @ v.co
        wl = wr = 0.0
        for g in v.groups:
            if g.group == idx_l: wl = g.weight
            if g.group == idx_r: wr = g.weight

        if co.x < -0.02 and wl > 0.05:
            bad_l_on_r.append((co.z, co.x, wl, wr))
        if co.x > 0.02 and wr > 0.05:
            bad_r_on_l.append((co.z, co.x, wl, wr))

    if bad_l_on_r:
        bad_l_on_r.sort(key=lambda x: -x[2])
        print(f"\n  ⚠️ 右侧(X<-0.02)含有 足D.L 的顶点: {len(bad_l_on_r)} 个")
        for z, x, wl, wr in bad_l_on_r[:5]:
            print(f"    Z={z:.3f} X={x:.3f}  足D.L={wl:.3f}  足D.R={wr:.3f}")
    else:
        print(f"  ✅ 无右侧串权（足D.L）")

    if bad_r_on_l:
        bad_r_on_l.sort(key=lambda x: -x[3])
        print(f"\n  ⚠️ 左侧(X>0.02)含有 足D.R 的顶点: {len(bad_r_on_l)} 个")
        for z, x, wl, wr in bad_r_on_l[:5]:
            print(f"    Z={z:.3f} X={x:.3f}  足D.L={wl:.3f}  足D.R={wr:.3f}")
    else:
        print(f"  ✅ 无左侧串权（足D.R）")


def check_overunder_weight(obj, arm):
    """统计全身权重超过1.0 / 低于0.8的变形骨顶点数"""
    deform_set = {b.name for b in arm.data.bones if b.use_deform}
    vg_idx = {vg.index for vg in obj.vertex_groups if vg.name in deform_set}
    if not vg_idx:
        return

    over = under = ok = 0
    for v in obj.data.vertices:
        total = sum(g.weight for g in v.groups if g.group in vg_idx and g.weight > 0)
        if total < 0.01:
            continue  # 未绑定顶点
        if total > 1.05:
            over += 1
        elif total < 0.80:
            under += 1
        else:
            ok += 1

    flag_o = " ⚠️" if over > 0 else " ✅"
    flag_u = " ⚠️" if under > 0 else " ✅"
    print(f"\n  全身变形权重统计: 正常={ok}{flag_o} 超重={over}{flag_u} 欠重={under}")


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────
def main():
    arm = bpy.context.active_object
    if not arm or arm.type != 'ARMATURE':
        # 尝试找场景中第一个骨架
        for obj in bpy.context.scene.objects:
            if obj.type == 'ARMATURE':
                arm = obj
                break
    if not arm:
        print("❌ 未找到骨架，请在 Outliner 选中骨架后重新运行")
        return

    # 找绑定到该骨架的网格
    meshes = [o for o in bpy.context.scene.objects
              if o.type == 'MESH' and any(
                  m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]

    if not meshes:
        print(f"❌ 骨架 {arm.name} 没有绑定的网格")
        return

    print(f"\n{'='*60}")
    print(f"骨架: {arm.name}  绑定网格: {[o.name for o in meshes]}")

    # 推算 Z 区间
    z_thigh, z_knee, z_shin = build_z_ranges(arm)

    if z_thigh:
        print(f"推算区间  大腿: Z={z_thigh[0]:.3f}~{z_thigh[1]:.3f}  "
              f"膝盖: Z={z_knee[0]:.3f}~{z_knee[1]:.3f}" if z_knee else
              f"推算区间  大腿: Z={z_thigh[0]:.3f}~{z_thigh[1]:.3f}")
    else:
        print("⚠️ 无法从骨架推算Z区间（骨骼可能尚未重命名）")
        # 使用粗略默认值
        z_thigh = (0.55, 1.0)
        z_knee  = (0.42, 0.62)
        z_shin  = (0.15, 0.55)

    for obj in meshes:
        mw = obj.matrix_world
        print(f"\n{'─'*50}")
        print(f"网格: {obj.name}")

        # 检查各区间
        for side in ("R", "L"):
            analyze_zone(f"大腿区", obj, arm, z_thigh, side=side)
            if z_knee:
                analyze_zone(f"膝盖区", obj, arm, z_knee, side=side)
            if z_shin:
                analyze_zone(f"小腿区", obj, arm, z_shin, side=side)

        # 串权检测
        print()
        analyze_cross_contamination(obj, mw)

        # 全身权重总量统计
        check_overunder_weight(obj, arm)

    print(f"\n{'='*60}\n")


main()
