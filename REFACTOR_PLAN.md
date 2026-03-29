# XPS→MMD 权重转换插件 Zone-based 架构重构计划

**日期**：2026-03-25
**分支**：main
**状态**：规划中

---

## 1. 背景：当前问题

### 核心症结

当前的权重处理流程是一个线性管道，各步骤共享同一套骨骼权重数据，导致后续步骤（尤其是 cleanup）会无差别地修改所有区域的权重，破坏前面步骤精心构造的渐变区。

### 具体现象

- **Hip blend zone 被破坏**：`_transfer_hip_weights` 建立了左右侧防交叉的渐变过渡，但随后的 D-bone cleanup 或 normalize 步骤会重新分配权重，导致渐变消失，左右侧权重再次交叉污染。
- **膝盖过渡被破坏**：deform bone normalize 在 cleanup 阶段统一处理全身，无法区分"渐变区应保留"与"残留值应清除"的差异。
- **调试困难**：出现问题时，难以判断是哪个步骤引入的，因为所有步骤都写同一个权重数组。

### 根本原因

缺乏区域隔离机制。不同身体区域的权重转换逻辑和 cleanup 规则本质上不同，但被混在同一个函数中顺序执行，相互干扰。

---

## 2. 三个 Zone 的定义

### Zone 1 — 上半身（Upper Body）

| 属性 | 内容 |
|------|------|
| 顶点范围 | 髋部混合区上边界以上的所有顶点 |
| 涉及骨骼 | 脊椎、胸、肩、手臂、颈、头及其 D-bone 对应骨骼 |
| 核心特点 | 左右对称，无跨侧问题；cleanup 可以激进清理小权重 |
| Cleanup 规则 | 可以 normalize、可以清除 < threshold 的残留权重 |

### Zone 2 — 髋部过渡区（Hip Blend Zone）

| 属性 | 内容 |
|------|------|
| 顶点范围 | 由 `hip_blend_upper_y` 到 `hip_blend_lower_y` 之间的顶点 |
| 涉及骨骼 | 左右髋骨（`LeftHip` / `RightHip`）、骨盆（`Pelvis`/`Lower`） |
| 核心特点 | 左右两侧权重必须严格按 X 坐标分离，渐变过渡需要保留 |
| Cleanup 规则 | **禁止** 全局 normalize；**禁止** 清除非零小权重；只允许按侧清理对侧污染 |

### Zone 3 — 下半身（Lower Body）

| 属性 | 内容 |
|------|------|
| 顶点范围 | 髋部混合区下边界以下的所有顶点 |
| 涉及骨骼 | 大腿、膝盖、小腿、脚踝、脚趾及其 D-bone 对应骨骼 |
| 核心特点 | 左右分支完全独立；膝盖区域需要保留渐变过渡权重 |
| Cleanup 规则 | 可以在单侧范围内 normalize；膝盖渐变区需专项保护 |

---

## 3. 方案B：独立函数拆分重构

### 总体思路

将现有的线性流程拆解为三个相互隔离的处理函数，每个函数只负责自己 Zone 内的顶点，不得跨 Zone 读写权重。最终由一个协调函数按顺序调用，并在 Zone 边界处做一次合并校验。

### 函数签名（伪代码）

```python
def _process_upper_body(mesh, bone_map, vertex_mask_zone1) -> WeightPatch:
    """处理 Zone1 上半身权重转换与 cleanup"""
    ...

def _process_hip_blend(mesh, bone_map, vertex_mask_zone2, x_coords) -> WeightPatch:
    """处理 Zone2 髋部过渡区，维护左右侧渐变隔离"""
    ...

def _process_lower_body(mesh, bone_map, vertex_mask_zone3) -> WeightPatch:
    """处理 Zone3 下半身权重转换与 cleanup"""
    ...

def _apply_zone_patches(mesh, patch1, patch2, patch3):
    """将三个 Zone 的结果合并写入 mesh，边界处做 normalize 校验"""
    ...
```

---

## 4. 各函数职责、边界与操作规则

### 4.1 `_process_upper_body`

**职责**
- XPS 上半身骨骼 → MMD 骨骼名称映射
- D-bone 权重分配（上半身部分）
- 残留小权重清除

**边界**
- 输入：`vertex_mask_zone1`（布尔数组，仅 Zone1 顶点为 True）
- 输出：`WeightPatch`（只包含 Zone1 顶点的权重修改）
- 严禁读取或写入 Zone2、Zone3 的顶点

**允许的操作**
- 全局 normalize（仅在 Zone1 顶点范围内）
- 清除权重 < 0.001 的残留值
- 左右对称骨骼的镜像校验

**禁止的操作**
- 修改任何 Zone2 / Zone3 顶点的权重
- 依赖 Zone2 顶点的权重值做决策

---

### 4.2 `_process_hip_blend`

**职责**
- 根据顶点 X 坐标计算左右侧混合权重
- 建立从 `LeftHip` 到 `RightHip` 的渐变过渡
- 清除对侧污染（X > 0 的顶点不应有左侧骨骼权重，反之亦然）

**边界**
- 输入：`vertex_mask_zone2`、每个顶点的 X 坐标数组
- 输出：`WeightPatch`（只包含 Zone2 顶点的权重修改）
- 严禁读取或写入 Zone1、Zone3 的顶点

**允许的操作**
- 按 X 坐标的分段线性函数计算混合比例
- 清除明确对侧骨骼的权重（如 X > blend_threshold 时清除 `LeftHip` 权重）
- 对中线附近顶点保留双侧小权重以维持平滑

**禁止的操作**
- 全局 normalize（会破坏渐变比例）
- 清除权重绝对值 < threshold 的值（渐变区边缘本来就有小权重）
- 依赖 Zone1 / Zone3 权重值做计算

---

### 4.3 `_process_lower_body`

**职责**
- XPS 下半身骨骼 → MMD 骨骼名称映射
- D-bone 权重分配（下半身部分）
- 膝盖渐变区保护性 cleanup
- 大腿、小腿的残留权重清除

**边界**
- 输入：`vertex_mask_zone3`
- 输出：`WeightPatch`（只包含 Zone3 顶点的权重修改）
- 严禁读取或写入 Zone1、Zone2 的顶点

**允许的操作**
- 在单侧（左腿/右腿）范围内 normalize
- 对膝盖渐变区使用宽松 threshold（不清除小于 0.01 以下的权重）
- 对非渐变区（脚踝、脚趾）使用激进 cleanup

**禁止的操作**
- 跨左右腿 normalize
- 对膝盖渐变区使用与其他区域相同的 cleanup 规则
- 修改 Zone2 顶点的权重

---

### 4.4 `_apply_zone_patches`（协调函数）

**职责**
- 将三个 `WeightPatch` 合并写入 mesh
- 检查 Zone 边界顶点的权重总和是否接近 1.0
- 输出警告（不自动修复）若发现边界处权重总和异常

**规则**
- 三个 Patch 的顶点掩码必须互斥（不重叠）且合并后覆盖所有顶点
- 边界顶点（Zone1/Zone2 交界、Zone2/Zone3 交界）各归属一个 Zone，不共享

---

## 5. 预期收益

### 5.1 快速定位问题到具体 Zone

出现权重异常时，可以通过以下方式快速缩小范围：

1. 检查异常顶点的 Y 坐标 → 确定属于哪个 Zone
2. 只审查对应 Zone 的处理函数
3. 在函数入口/出口插入断言，验证"该函数未修改其他 Zone 的权重"

### 5.2 独立测试每个 Zone

每个函数可以单独用 mock mesh 测试，不需要运行完整的转换流程。

### 5.3 避免 cleanup 相互干扰

Zone2 的渐变权重不会被 Zone1/Zone3 的 cleanup 逻辑误清除，因为这些 cleanup 逻辑物理上无法访问 Zone2 的顶点。

### 5.4 规则可见性

每个 Zone 的允许/禁止操作在函数注释中明确列出，未来修改时有明确约束可参考。

---

## 6. 注意事项与风险

### 6.1 Zone 边界的确定

- `hip_blend_upper_y` 和 `hip_blend_lower_y` 的具体数值需要从当前代码中提取并固化为常量。
- 边界值若依赖 mesh 动态计算，需确保三个函数使用同一次计算结果，避免因浮点误差导致顶点归属不一致。

### 6.2 WeightPatch 数据结构

- 需要新增 `WeightPatch` 类（或使用字典 `{vertex_index: {bone_name: weight}}`）。
- 合并时需处理同一顶点被多个 Patch 包含的边缘情况（理论上不应发生，需加断言）。

### 6.3 重构顺序建议

1. 先提取 Zone 边界常量，不改逻辑
2. 新增 `vertex_mask` 生成辅助函数
3. 将现有逻辑逐段搬入三个新函数，保持行为不变
4. 加入边界断言
5. 逐步将跨 Zone 的 cleanup 调用替换为 Zone 内的等价实现
6. 最后删除旧的线性流程代码

### 6.4 回归测试

- 重构完成后，在同一套测试模型上对比重构前后的权重输出，确保数值一致。
- 重点检查：Zone2 边界顶点的权重总和、膝盖渐变区的权重分布。

### 6.5 已知遗留问题（重构前需记录）

- 当前 `_transfer_hip_weights` 和 `_normalize_deform_weights` 的调用顺序在 `auto_convert_operator.py` 中，重构后这两个函数将被拆入 Zone2 和 Zone3，需同步更新调用方。
- `bone_split_operator.py` 中的 D-bone 逻辑目前与主流程耦合，需确认是否也需要按 Zone 拆分。

---

## 7. 相关文件索引

| 文件 | 说明 |
|------|------|
| `operators/auto_convert_operator.py` | 主转换流程，当前线性管道所在位置 |
| `operators/bone_operator.py` | 骨骼名称映射逻辑 |
| `operators/bone_split_operator.py` | D-bone 拆分逻辑 |
| `ui_panel.py` | UI 入口，调用链起点 |
| `__init__.py` | 插件注册 |

---

*本文档用于在讨论中断后恢复上下文。下次讨论时从"6.3 重构顺序建议"的第3步开始。*
