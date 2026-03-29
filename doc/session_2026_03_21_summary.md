---
name: 2026-03-21 工作总结
description: 当天调试 XPS→MMD 腿部动作不跟随问题的完整记录，供下次继续
type: project
---

# 2026-03-21 工作总结

## 背景

项目：Convert-to-MMD Blender 插件，把 XPS 模型转为 MMD 可用 PMX。
当前角色：Taimanin Asagi（通灵忍者 茜井葵），xna_lara 预设。
问题：导出的 PMX 在 MMD 里播放 VMD 动作时，腿部网格基本不动，但骨骼动画是对的。

---

## 核心原理：MMD D系腿骨机制

MMD 腿部有两套骨骼：

| 骨骼 | 作用 | deform |
|------|------|--------|
| 足.L / ひざ.L / 足首.L | FK/IK 控制骨，驱动动作 | False（不变形网格）|
| 足D.L / ひざD.L / 足首D.L | 变形骨，实际控制网格 | True |

D系骨骼通过 **付与（additional_transform）** 复制 FK 骨骼的旋转，influence=1.0，从而让网格跟随动作。

mmd_tools 内部实现付与的方式：
- `pose_bone.mmd_bone.additional_transform_bone = "足.L"` 设置授权来源
- `FnBone.apply_additional_transformation(armature)` 生成 shadow/dummy 骨骼和约束
- **关键**：D系骨的 tail 必须与 FK 骨方向**不同**（非 well-aligned），才会真正生成 shadow 骨骼

---

## 今天发现的问题（按重要性排序）

### 问题1：D系骨骼 tail 与 FK 骨完全相同 → well-aligned 优化跳过 shadow 骨生成

**现象**：321-9/10 中 `足D.L` 约束直接指向 `足.L`（FK骨），没有 `_shadow_足D.L`。
参考模型中是指向 `_shadow_足D.L`。

**原因**：我们之前把 D系骨的 tail 设为与 FK 骨完全一样，导致 `__is_well_aligned()` 返回 True，mmd_tools 跳过 shadow 骨创建，直接约束到 FK 骨。

**修复**：把 D系骨的 tail 改为向上的短 stub（+0.082Z），与 FK 骨方向不同（y_dot ≈ -1），触发 shadow 骨创建。

**代码位置**：`bone_operator.py` 第 205-212 行，`bone_properties` 字典中的 D系骨定义。

**已修复**：✅ 321-11/12/13 中 shadow 骨正确创建。

---

### 问题2：孤立骨转移后躯干权重未清零 → 顶点被躯干骨和D系骨各拉一份

**现象**：某顶点同时有 `下半身=1.0` 和 `ひざD.L=1.0`，总权重=2.0，网格变形错乱。

**原因**：`_weight_execute_orphan_transfer` 把孤立骨权重转移到 D系骨时，只清除了孤立骨本身的权重，没有清除同一顶点上已有的 `下半身` 权重。

**修复**：区间覆盖发生时（`actual_dst_name != dst_bone.name`），额外把原躯干目标（`下半身`）的权重也清零。

**代码位置**：`_weight_execute_orphan_transfer` 函数，第 546-572 行。

**已修复**：✅ 同时在 `fix_orphan_weights` 末尾加了 `_weight_cleanup_leg_torso_conflict()` 全局清理。

---

### 问题3：缺失权重填充（bell-curve）把D系骨错误地从躯干骨扩散

**现象**：321-12 的 `足首D.L`（踝骨）在大腿区域（Z=0.7~1.0）有 544 顶点，与 `下半身` 完全相同。

**原因**：`_weight_execute_missing_fill` 沿父级链找祖先时，如果 `足D.L`/`ひざD.L` 都没有权重，会一直找到 `下半身`，然后用 `下半身` 做 bell-curve 填充。bell-curve 半径 0.20，`足首D.L` 的 head 在 Z=0.15（踝），t_center 投影到 `下半身` 方向上接近 0，导致 `下半身` 控制的大量腰部顶点（Z=0.8~1.0）都被错误分配给 `足首D.L`。

**修复**：
1. `_weight_execute_missing_fill` 中：D系腿骨如果祖先搜索到达 `下半身`/`腰` 则跳过，不做填充。
2. `fix_missing_weights` 执行后自动再次运行 `_weight_cleanup_leg_torso_conflict()`。

**代码位置**：`_weight_execute_missing_fill` 函数，第 608 行附近。

**已修复**：✅ 代码已更新，但 321-13 是手动导出的（见下方"未解决"）。

---

### 问题4：足先EX.L 重复骨骼（足先EX.L.001）

**现象**：321-12 中存在 `足先EX.L` 和 `足先EX.L.001` 两个骨骼，`.001` 带 DAMPED_TRACK。

**原因**：插件 step 2（`complete_missing_bones`）创建了 `足先EX.L` 作为 D系脚趾骨，IK 步骤（或某步骤）又创建了一个同名骨，Blender 自动加 `.001` 后缀。

**状态**：⚠️ **未修复**，需要排查 IK operator 或 bone_split_operator 里哪里重复创建了这个骨骼。

---

## 当前已知权重情况（对原始 Armature 手动修复后）

```
足D.L:    1766 顶点
足D.R:    2127 顶点
ひざD.L:  1814 顶点
ひざD.R:  1813 顶点
足首D.L:  3225 顶点
足首D.R:  2990 顶点
下半身:   4383 顶点（已从 15045 降到 4383）
```

腿部 Z 分段左腿分布（手动清理后）：
- 髋(Z 0.9~1.1): 足D.L=272, 下半身=10（少量臀部）✅
- 大腿上(Z 0.7~0.9): 足D.L=86 ✅
- 大腿下(Z 0.6~0.7): 足D.L=89, ひざD.L=39 ✅
- 小腿(Z 0.1~0.5): ひざD.L, 足首D.L ✅

---

## 尚未解决的问题

### 主要问题：用户用插件重新跑一遍流程，321-12 的权重仍然错误

用户自己运行完所有步骤导出的 321-12 与我们手动修复的 Armature 不一致。原因可能是：
1. 插件某步骤的执行顺序有问题（用户跑步骤时的具体顺序未知）
2. 即使加了修复代码，bell-curve 填充前 D系骨可能仍从错误来源继承了权重
3. 原始 XPS 模型的腿部骨骼权重本身就是问题（`左足` 本身可能有 0 权重，因为 XPS "leg left thigh" 被映射到了不同名称）

### 需要下次确认的事项

1. **原始 XPS 模型的腿部骨骼映射**：确认 xna_lara 预设中 "leg left thigh" → 哪个骨骼。如果映射不对，`左足` 在 step1 后本就没有腿部顶点，D系权重复制就是 0。
2. **足先EX.L 重复骨骼问题**：找到是哪步创建了重复骨骼，加防护。
3. **端到端测试**：从干净的 XPS 模型（xps 集合中的 Armature 重置）重新跑全部步骤1-10，验证 321-13.pmx 是否在 MMD 中腿部正确跟随。
4. **IK不对齐问题**：用户提到 IK 没和脚对齐，这可能是 step 3（添加 IK）的设置有误。需要对比参考模型的 IK 骨骼位置。

---

## 关键文件位置

| 文件 | 状态 |
|------|------|
| `/Users/bytedance/Desktop/Convert-to-MMD/operators/bone_operator.py` | 主修改文件，含所有权重逻辑 |
| `/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert-to-MMD/` | Blender 加载的实际插件目录（与 Desktop 版本不同！每次修改后需要 cp 同步） |

**重要**：两个目录不一样，修改桌面版本后必须手动同步：
```bash
cp "/Users/bytedance/Desktop/Convert-to-MMD/operators/bone_operator.py" \
   "/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert-to-MMD/operators/bone_operator.py"
```

---

## Blender 场景说明

| 集合 | 内容 |
|------|------|
| xps | 原始 XPS 骨架（Armature），已手动修复权重，是导出基准 |
| 集合 2 | 参考 PMX（Purifier Inase 18 None），比对标准 |
| 集合 3 | 历次导出后再导入的测试模型（321-9 ~ 321-13）|

桌面有：`321-13.pmx`（最新导出，权重已手动修复，D系 shadow 骨骼正确）。

---

## 下次工作建议

1. 先用 `321-13.pmx` 在 MMD 里测试，看腿部是否跟随动作
2. 如果还有问题，用 MCP Blender 工具对比 321-13 和参考模型（集合2）的完整骨骼列表和权重
3. 修复 `足先EX.L.001` 重复骨骼问题
4. 检查并修复 IK 骨骼对齐问题
5. 从干净模型重新跑插件全流程，验证代码修复是否生效
