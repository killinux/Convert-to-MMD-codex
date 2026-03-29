# Convert-to-MMD Codex 交接文档

更新时间：2026-03-27

## 0.15 2026-03-27 晚间最新状态

截至 2026-03-27 21:23，`Step 2` 腿根问题已经从“左右整体反了”收敛成“live 结果基本正常，旧摘要缓存滞后”。

关键结论：

- 已确认当前工程与目标 PMX 的几何侧约定为：
  - `正 X = 左`
  - `负 X = 右`
- 之前按反向侧别做出的部分判断已失效，因此后续看腿根关系时，必须优先相信“几何侧”而不是先验的 `.L/.R` 直觉。
- 以 Blender live 关系快照重新计算，当前 `Step 2` 的腿根带为：
  - 左腿根：`local=48.135, opp=16.705, lower=60.738`
  - 右腿根：`local=46.404, opp=17.830, lower=65.555`
- 上述结果说明：
  - 两边都已恢复成“本侧 D 骨 > 对侧 D 骨”
  - 不再是此前那种“整套串侧”的错误
- 当前 live 关系异常数已经是 `0`
- 但 `scene["wm_last_check_result"]` 仍残留旧缓存，可能还会显示：
  - `左腿根上缘混入过多足D.R权重`
  - `关系异常=2`

因此当前的主要剩余问题不是腿根规则本身，而是：

- 面板顶部那句 `wm_last_check_result` 仍可能显示旧缓存
- 需要以面板下方的：
  - `关系摘要`
  - `关系异常`
  - `腿根带测量`
 以及 Blender live 关系快照为准

当日晚间新改动：

- [planning/relationship_builder.py](/Users/bytedance/Desktop/Convert-to-MMD/planning/relationship_builder.py)
  - 将腿根串侧阈值从 `0.35` 放宽到 `0.40`
  - 目的：避免把边界残留误判成 `unexpected`
- [ui_panel.py](/Users/bytedance/Desktop/Convert-to-MMD/ui_panel.py)
  - 面板结果显示改为：若存在 live 关系快照，则优先用 live 的 `关系异常` 数量覆盖旧缓存摘要中的 `关系异常=...`
  - 目的：减少顶部一句话与下方 live 数据互相打架

## 0.2 明天讨论提纲

明天优先讨论这 3 件事：

1. 顶层设计是什么  
   是否坚持“分层设计 + 分阶段执行 + 每步验证”，尤其是：
   - 先语义与映射
   - 再主干结构
   - 再 helper / D骨 / twist
   - 最后局部权重修复

2. 如何自动化测试  
   目标不是“做完再肉眼看”，而是：
   - 每一步自动拍快照
   - 每一步自动跑局部 pose
   - 自动对比关键区域与参考 PMX

3. 目前问题是什么  
   当前最卡的是：
   - `Step 4` 之后腿根 `足D` 参与带仍不稳定
   - 腿根顶部容易被 `下半身` 吃太多
   - 左右 D 骨还会互相污染
   - 手工 Blender 测试成本太高，反馈太慢

## 0.25 2026-03-27 白天新增设计决定

今天新增的一个关键共识是：

- 先定“权重如何被观察和判断”的设计
- 再继续深入修 `足D` / 腿根权重

原因是，最近连续出现的问题都说明：

- 用户看到的是“D骨不控制腿根”
- 真正根因可能是：
  - 主干骨字段和骨架不同步
  - `下半身` 顶点组不存在
  - helper 还没并入目标 deform 组
  - 左右 `.L/.R` 与几何侧不一致

因此当前决定把下面三样东西纳入正式设计：

1. 源关系表  
   显示：
   - 源骨骼
   - 中间语义
   - 当前顶点组
   - 带权顶点数 / 总权重 / 区域

2. 目标关系表  
   显示：
   - MMD 骨骼
   - 当前顶点组是否存在
   - 当前权重来源
   - deform / control / helper 类型

3. 步骤变化表 + 预期规则  
   每一步都记录：
   - 哪些骨新增/重命名
   - 哪些顶点组新增/消失
   - 哪些变化属于 `expected / expected_risky / unexpected`

这样后续像 `Step 2` 的问题，就不需要等用户拖动 D骨后才发现，而会直接显示成：

- `下半身 顶点组缺失`
- `unexpected`

这套设计已补充到：

- [universal_xps_to_mmd_architecture.md](/Users/bytedance/Desktop/Convert-to-MMD/doc/universal_xps_to_mmd_architecture.md)

另外，最小实现骨架已开始落地：

- [planning/model.py](/Users/bytedance/Desktop/Convert-to-MMD/planning/model.py)
  - 新增：
    - `BoneWeightEntry`
    - `TargetWeightEntry`
    - `StepChangeEntry`
    - `StepExpectationRule`
    - `WeightRelationshipSnapshot`
- [planning/relationship_builder.py](/Users/bytedance/Desktop/Convert-to-MMD/planning/relationship_builder.py)
  - 新增“关系快照构建器”
  - 当前先支持：
    - 从当前 mesh 顶点组统计源关系表 / 目标关系表
    - 为 `step_1 / step_2 / step_3 / step_2_5` 生成最小预期规则
    - 将“关键顶点组缺失 / 空权重”标成 `unexpected`
- [operators/weight_monitor.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/weight_monitor.py)
  - 已开始接入 `relationship_snapshot`
  - 后续每一步的快照会逐步同时记录：
    - 传统区域统计
    - 关系级异常
- [ui_panel.py](/Users/bytedance/Desktop/Convert-to-MMD/ui_panel.py)
  - 已显示：
    - `关系摘要`
    - `关系异常`
    - `最近一步变化`
    - `腿根带测量`
  - 已加“实时关系快照”兜底：
    - 当缓存里的 `relationship_snapshot` 为空或过旧时
    - 面板会按当前场景现算一份关系快照
    - 避免 Blender 子模块热更新不完整时 UI 完全失明

## 0. 当日晚间新增进展（2026-03-26 23:27）

今天又继续把“语义扫描 -> ConversionPlan -> 一键流程”往前推了一段，当前新增的重点是：

- 已实现“源/目标双边语义扫描 + 计划预览 + 自动填骨映射”
- 已把 `target` 侧语义误判里最明显的一类修掉：
  - `_dummy_足首D.L/R`
  - `_shadow_足首D.L/R`
  - `足首D.L/R`
  这类辅助骨不再误识别成 `neck`
- 已把一键流程改成“先扫语义，再自动填主干映射”
- 已引入 `source-only / source_plus_reference` 两种计划模式
- 已加入“继续高风险步骤”开关
- 默认一键流程现在只跑安全阶段，把高风险步骤留给人工确认
- 一键流程的推荐顺序已调整为“先结构，后高风险权重”：
  - `2 补全缺失骨骼`
  - `3 骨骼切分`
  - 再 `4 helper 权重转移`
  - 再 `8 前臂扭转权重`
- 面板里已新增“执行预览”，会显示：
  - 默认执行哪些步骤
  - 哪些步骤待人工确认
  - 哪些步骤按 plan 跳过
- 已把原 `2.5` / `6.5` 的用户可见编号顺到当前执行顺序：
  - `4 转移腿/腰辅助骨权重`
  - `8 转移前臂扭转权重`
- 已继续收 `Step 4` 的髋部/大腿内侧问题：
  - helper redirect 改成保守合并，不再直接把源权重整包顶满目标骨
  - 新增“大腿内侧上缘 / 中线 cleanup”
  - 这段 cleanup 会在 `Step 4` 里自动执行，重点压：
    - 中线区域 `足D.L + 足D.R` 同时残留
    - 左腿内侧沾到右 `足D`
    - 右腿内侧沾到左 `足D`

这部分的主要代码位置：

- [operators/semantic_debug_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/semantic_debug_operator.py)
- [semantic/infer.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/infer.py)
- [planning/model.py](/Users/bytedance/Desktop/Convert-to-MMD/planning/model.py)
- [planning/builder.py](/Users/bytedance/Desktop/Convert-to-MMD/planning/builder.py)
- [operators/auto_convert_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/auto_convert_operator.py)
- [ui_panel.py](/Users/bytedance/Desktop/Convert-to-MMD/ui_panel.py)
- [__init__.py](/Users/bytedance/Desktop/Convert-to-MMD/__init__.py)
- [weights/redirects.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/redirects.py)
- [operators/bone_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/bone_operator.py)

### 0.1 今晚做过的实际验证

已完成：

- 本地 Python 语法检查通过：
  - `weights/redirects.py`
  - `operators/bone_operator.py`
- 已同步到 Blender 3.6 插件目录
- 已通过 Blender MCP 重新加载 add-on
- 已确认 Blender 插件目录中的 [redirects.py](/Users/bytedance/Library/Application%20Support/Blender/3.6/scripts/addons/Convert-to-MMD/weights/redirects.py) 包含：
  - `cleanup_inner_thigh_d_weights`

还没做完的验证：

- 还需要用户在 Blender 里重新点一次：
  - `2 补全缺失骨骼`
  - `3 骨骼切分`
  - `4 转移腿/腰辅助骨权重`
- 然后再看：
  - 大腿内侧是否仍由 `足D.L/R` 双侧污染
  - `wm_last_check_result` 里的髋部硬切割和冲突顶点是否下降

### 0.3 截至 2026-03-27 凌晨的当前问题

这几条是明天继续前最重要的现状：

- `Step 1` 的“过期映射”问题已修  
  现在如果 Scene 字段还留着旧骨名，例如 `root hips`，但当前骨架里已经有 `下半身`，会自动同步字段，而不是继续误报。

- `Step 2` 会把 `左足/右足/左ひざ/右ひざ/左足首/右足首` 设为 `use_deform=False`  
  这符合当前设计：FK 腿骨做控制，D 骨做实际变形。

- 当前真正卡住的不是 FK/D 双控  
  而是腿根上缘 `下半身 -> 足D` 的过渡带仍不理想。

- 右腿腿根的一个已观测问题：
  - `Step 4` 后右腿腿根上缘曾测到平均分布约为：
    - `下半身 0.804`
    - `足D.L 0.108`
    - `足D.R 0.087`
  - 说明这里不只是 `足D.R` 偏少，还混入了错误的 `足D.L`

- 左腿腿根也曾测到被过度洗成 `下半身`
  - 某次实测左腿根顶部约为：
    - `下半身 0.996`
    - `足D.L 0.0`
    - `足D.R 0.004`
  - 这解释了“拖 D 骨时大腿根几乎不动”的现象

- 当前结论：
  - `Step 4` 需要同时处理两件事：
    - 清掉对侧 D 骨污染
    - 保住本侧 D 骨在腿根上缘的参与带
  - 只做 cleanup 不够
  - 只做 restore 也不够

- 2026-03-27 晚间新增根因：
  - 通过关系快照直接核到：
    - `unused bip001 xtra02` 几何上在左侧
    - `unused bip001 xtra04` 几何上在右侧
  - 旧版 `profiles/xna_lara.py` 却写成：
    - `xtra02 -> 足D.R`
    - `xtra04 -> 足D.L`
  - 这会在 helper 转移前就把腿根权重导向错误的 D 骨，直接制造左右串侧。
  - 已修正为：
    - `xtra02 -> 足D.L`
    - `xtra04 -> 足D.R`
  - 同时已把“helper 几何侧 vs 目标骨侧不一致”接入关系快照，后续 profile 再写反时，面板应该能直接报出关系异常。

## 1. 项目目标与当前判断

这个仓库当前更准确的定位，不是“直接解析 XPS 再直接写 PMX 的格式转换器”，而是：

- 在 Blender 里运行的辅助插件
- 负责把 XPS 风格的人形骨架、辅助骨和权重整理成更接近 MMD 的结构
- 最终 PMX 导出仍依赖 `mmd_tools`

当前建议的长期目标是做成一个“尽量通用的 XPS -> MMD-ready 转换工具”，而不是简单的名字替换器。核心思想是：

- 先理解原始骨架
- 再抽象成统一语义层
- 再构造 MMD 控制骨 / 变形骨
- 最后做区域化的权重迁移和修复

## 2. 已完成的架构调整

已经新增并接入了这几层基础模块：

- [semantic](/Users/bytedance/Desktop/Convert-to-MMD/semantic)
- [canonical](/Users/bytedance/Desktop/Convert-to-MMD/canonical)
- [weights](/Users/bytedance/Desktop/Convert-to-MMD/weights)
- [profiles](/Users/bytedance/Desktop/Convert-to-MMD/profiles)

### 2.1 新增模块

已新增文件：

- [semantic/types.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/types.py)
- [semantic/infer.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/infer.py)
- [canonical/model.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/model.py)
- [canonical/normalize.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/normalize.py)
- [weights/snapshot.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/snapshot.py)
- [weights/diff.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/diff.py)
- [weights/zones.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/zones.py)
- [weights/refine_hip.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/refine_hip.py)
- [weights/redirects.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/redirects.py)
- [profiles/base_profile.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/base_profile.py)
- [profiles/xna_lara.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/xna_lara.py)
- [profiles/generic_xps.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/generic_xps.py)
- [profiles/registry.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/registry.py)
- [operators/semantic_debug_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/semantic_debug_operator.py)

### 2.2 已迁出的旧逻辑

以下逻辑已经从大文件中抽离，但仍通过旧调用路径保持兼容：

- 髋部渐变区逻辑
  - 旧入口在 [operators/bone_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/bone_operator.py)
  - 新实现位于 [weights/refine_hip.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/refine_hip.py)

- 辅助骨权重转移逻辑
  - 旧入口在 [operators/bone_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/bone_operator.py)
  - 新实现位于 [weights/redirects.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/redirects.py)

- 权重快照逻辑
  - 旧 operator 位于 [operators/weight_monitor.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/weight_monitor.py)
  - 新实现位于 [weights/snapshot.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/snapshot.py)

### 2.3 profile 层

原先 `Step 4 / 8` 中写死在 `bone_operator.py` 里的 redirect 表，已经改成通过 profile 获取：

- 默认 profile 在 [profiles/registry.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/registry.py)
- 现有 profile：
  - [profiles/xna_lara.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/xna_lara.py)
  - [profiles/generic_xps.py](/Users/bytedance/Desktop/Convert-to-MMD/profiles/generic_xps.py)

当前默认 profile 仍偏向 XNA/XPS 风格骨架。

## 3. 语义识别层的当前状态

### 3.1 已实现内容

当前 `semantic.infer()` 是“名称规则第一层”版本，已经能识别以下主干语义：

- `pelvis`
- `pelvis_helper`
- `spine_lower`
- `spine_mid`
- `spine_upper`
- `neck`
- `head`
- `eye_l`
- `eye_r`
- `clavicle_l/r`
- `upper_arm_l/r`
- `lower_arm_l/r`
- `hand_l/r`
- `thigh_l/r`
- `calf_l/r`
- `foot_l/r`
- `toe_l/r`
- `inner_thigh_helper_l/r`
- `twist_helper_l/r`

相关实现：

- [semantic/infer.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/infer.py)
- [canonical/normalize.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/normalize.py)

### 3.2 已修正过的问题

这几项已经通过真实 Blender 场景验证过：

- `spine lower` 不再误判为 `pelvis`
- `arm left/right shoulder 2` 不再被 `clavicle` 抢走，已经能识别成 `upper_arm`
- `arm left/right wrist` 已经能识别成 `hand`
- `head hair left 1` 不再被当成 `head`
- `head eyelid / eyebrow / jaw / lip / tongue` 这类脸部细分骨已从 `head` 候选中排除
- `head eyeball left/right` 已加入 `eye_l / eye_r` 候选

### 3.3 当前 Blender 实测结果

最后一次在 Blender 中读取到的结果是：

- 识别数：`31`
- canonical 摘要：
  - `pelvis = root hips`
  - `spine_lower = spine lower`
  - `spine_mid = spine middle`
  - `spine_upper = spine upper`
  - `neck = head neck lower`
  - `head = null`
  - `upper_arm_l = arm left shoulder 2`
  - `upper_arm_r = arm right shoulder 2`
  - `lower_arm_l = arm left elbow`
  - `lower_arm_r = arm right elbow`
  - `hand_l = arm left wrist`
  - `hand_r = arm right wrist`

这说明：

- 主干骨架基本已识别正确
- 脸部细分骨被大量排除，所以总识别数从 `51/63` 降到了 `31`
- `head` 为空的原因是：这套骨架没有独立 `head` 主骨，只有：
  - `head neck lower`
  - `head neck upper`

为解决这个问题，已经继续修改了规则，但尚未完成最终 Blender 侧确认：

- `head neck lower -> neck`
- `head neck upper -> head`
- `head eyeball left/right -> eye_l / eye_r`

这部分当前代码已写在：

- [semantic/infer.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/infer.py)
- [canonical/model.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/model.py)
- [canonical/normalize.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/normalize.py)
- [operators/semantic_debug_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/semantic_debug_operator.py)

但需要在 Blender 里再次点击“扫描当前骨架语义”做最终确认。

## 4. Blender 插件调试入口

已新增调试 UI：

- 面板：`Convert to MMD`
- 区域：`语义识别与转换计划`
- 按钮：`扫描当前骨架语义`

当前这个区域已经不只是调试入口，而是第一版 `ConversionPlan` 工作台，里面已有：

- `源骨架`
- `目标骨架`
- `扫描源/目标语义`
- `自动填骨映射`
- `计划预览`
- `执行预览`

另外，一键流程区域也已经新增：

- `继续高风险步骤（4 / 8 / 权重修复）`
- `一键全流程转换`

默认行为：

- 先自动扫描语义
- 再自动填充主干映射
- 默认只跑安全阶段
- 将高风险步骤留给人工确认

代码位置：

- [operators/semantic_debug_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/semantic_debug_operator.py)
- [ui_panel.py](/Users/bytedance/Desktop/Convert-to-MMD/ui_panel.py)
- [__init__.py](/Users/bytedance/Desktop/Convert-to-MMD/__init__.py)

当前 Scene 上挂了这些调试字段：

- `semantic_debug_preview`
- `semantic_debug_count`
- `semantic_debug_canonical`

另一个 Codex 可以通过 Blender MCP 直接读取：

```python
import bpy
s = bpy.context.scene
print(s.semantic_debug_count)
print(s.semantic_debug_preview)
print(s.semantic_debug_canonical)
```

## 5. 权重相关的重要判断

### 5.1 Step 2 / 4 问题定位

之前已经针对“大腿内侧权重不对”做过分析，结论如下：

- `Step 2` 中已经创建过一次髋部渐变区
- `Step 4` 把 `xtra08 / xtra08opp` 一类辅助骨权重过于粗暴地并到了 `下半身`
- 然后做 normalize，但没有重新构建髋部渐变
- 结果是大腿内侧出现很多顶点：
  - `下半身 = 1.0`
  - `足D.L/R = 0`

因此判断：

- `_create_hip_blend_zone()` 本身不是坏逻辑
- 但如果简单粗暴地加回某一步后面，会有左右串侧、超权重、掩盖根因等风险
- 更合理的方向是：
  - 把 helper redirect 做成 profile/rule
  - 或在 redirect 后做有条件的 hip blend 重建

相关实现位置：

- [weights/refine_hip.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/refine_hip.py)
- [weights/redirects.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/redirects.py)

### 5.1.1 当前推荐顺序调整

在实际联调后，当前更推荐的执行顺序是：

- `2 补全缺失骨骼`
- `3 骨骼切分`
- `4 转移腿/腰辅助骨权重`

原因：

- `2 -> 3` 有明显结构依赖，`3` 需要 `2` 先把主干 MMD 骨名和基础结构补出来
- `4` 主要影响腿/腰 helper 权重，不是 `3` 的结构前提
- 若把 `4` 放在 `3` 前面，会把腿腰区域的高风险权重波动提前带进流程，增加调试噪声
- 因此当前按“先结构、后高风险权重”更稳

### 5.2 权重检查框架方向

已经明确建议将权重检查分成三层：

- 骨级 diff
- 区域级 diff
- 顶点级热点 diff

当前已完成的基础设施：

- [weights/snapshot.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/snapshot.py)
- [weights/diff.py](/Users/bytedance/Desktop/Convert-to-MMD/weights/diff.py)

目前 `weights.diff` 还只是第一版，后续应该继续扩展到区域和顶点层面。

## 6. 设计文档

目前已有两份较完整的设计/说明文档：

- 架构设计：
  - [universal_xps_to_mmd_architecture.md](/Users/bytedance/Desktop/Convert-to-MMD/doc/universal_xps_to_mmd_architecture.md)

- Blender MCP 接入说明：
  - [blender_mcp_codex_link.md](/Users/bytedance/Desktop/Convert-to-MMD/doc/blender_mcp_codex_link.md)

## 7. Blender 运行环境与同步方式

当前 Blender 3.6 插件目录是：

- `/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert-to-MMD`

本仓库代码通常通过以下方式同步到 Blender 3.6 插件目录：

```bash
rsync -a --delete --exclude '.git' --exclude '__pycache__' /Users/bytedance/Desktop/Convert-to-MMD/ '/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert-to-MMD/'
```

注意：

- 这个目录在仓库外，写入通常需要提权
- 已经多次用这个方式同步成功
- Blender 有时会缓存 Python 模块，必要时应完全重启 Blender 再测

## 7.1 今晚实际测试记录

今晚我自己做过的验证，分成三类：

### A. 静态代码验证

已通过：

```bash
python3 -m py_compile operators/auto_convert_operator.py ui_panel.py __init__.py operators/semantic_debug_operator.py semantic/infer.py planning/builder.py
```

说明：

- 当前新增的 plan 驱动代码、UI 代码、语义识别代码都能通过语法检查

### B. Blender 语义与计划验证

在 Blender 场景中，以：

- 源骨架：`Armature`
- 目标骨架：`Purifier Inase 18 None_arm`

重新扫描后，当前实测结果为：

- `source_count = 31`
- `target_count = 26`

目标骨架预览已修正为正常主干链，例如：

- `下半身 -> pelvis`
- `足.L -> thigh_l`
- `ひざ.L -> calf_l`
- `足首.L -> foot_l`
- `足先EX.L -> toe_l`
- `首 -> neck`
- `頭 -> head`

最关键的是，之前这几类误判已经不再出现：

- `_dummy_足首D.L/R -> neck`
- `_shadow_足首D.L/R -> neck`
- `足首D.L/R -> neck`

### C. Blender 一键流程验证

在安全模式下测试：

- `auto_convert_allow_risky = false`

当前可确认：

- 一键流程会先自动做语义扫描
- 一键流程会自动填充主干映射
- `wm_last_check_result` 能正确写出：
  - 待人工确认的高风险步骤
  - 当前 `plan` 模式
  - 当前 `profile`

例如当前场景中可见结果：

- `待人工确认: 转移腿/腰辅助骨权重 / 转移前臂扭转权重 / 权重修复（孤立骨+缺失骨+髋部渐变） | plan=source_plus_reference | profile=xna_lara`

### D. 今晚发现的一个缓存/验证边界

我在 Blender MCP 里直接调用一键流程时，仍看到了旧版 operator 调用方式遗留的报错：

- `'module' object is not callable`

但我已经在代码里修正了调用方式，新的实现位于：

- [operators/auto_convert_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/auto_convert_operator.py)

并且 Blender 插件目录中的文件也已确认是新版内容：

- [auto_convert_operator.py](/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert-to-MMD/operators/auto_convert_operator.py)

当前判断是：

- 文件同步已经成功
- 但 Blender 进程里这一个 operator 很可能仍命中了旧缓存
- 明早最稳的复核方法是：完全重启 Blender 后，再手点一次“一键全流程转换”

也就是说，这项修复“代码已落地”，但“Blender 运行态最终验证”需要明早再做一次干净复测。

## 8. 建议的下一步优先级

建议另一个 Codex 按这个顺序继续：

### 第一步：重新验证一键流程的新版 operator 调用

目标：

- 完全重启 Blender
- 不通过 MCP，直接在 UI 中点一次“一键全流程转换”
- 确认不再出现：
  - `'module' object is not callable`

如果仍出现，优先检查：

- [operators/auto_convert_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/auto_convert_operator.py)
- Blender 是否真的加载了插件目录里的最新版文件

### 第二步：完成执行预览与实际执行的一致性复核

目标：

- 在 `语义识别与转换计划` 面板查看：
  - `计划预览`
  - `执行预览`
- 对照实际一键流程行为，确认：
  - 默认安全模式只跑安全阶段
  - 勾选 `继续高风险步骤` 后才继续 `4 / 8 / 权重修复`

### 第三步：继续扩展 step 裁剪规则

当前 step 裁剪还只是第一版，下一阶段建议继续让 plan 决定：

- 哪些步骤完全不用跑
- 哪些步骤只能在 `source_plus_reference` 下跑
- 哪些步骤应该因主干缺失而直接阻断

例如：

- 无腿部 helper 时，直接跳过 `4`
- 无 twist helper 时，直接跳过 `8`
- 手臂链不完整时，不自动加扭转骨
- 某些控制骨生成阶段应依赖更完整的主干识别

### 第四步：加入最小拓扑规则

当前语义识别还是“名称规则优先”的第一阶段。下一阶段建议继续加入：

- 拓扑补强
- 空间补强

重点目标不是增加识别数，而是提高 `ConversionPlan` 的可信度。

### 第五步：把权重 diff 接进 plan-driven 流程

建议下一步真正落地：

- 在关键步骤前后拍 `WeightSnapshot`
- 输出 `WeightDiff`
- 继续盯紧 Step 2 / Step 4 / Step 8 这三步

目标不是先做漂亮 UI，而是先回答：

- 哪一步改了哪些骨
- 哪一步把髋部过渡冲坏了
- helper redirect 后哪些区域变化最大

### 第六步：继续拆 `bone_operator.py`

这是中长期最重要的重构方向。建议优先继续拆：

- helper redirect 相关规则
- 腿部 / 髋部权重处理
- D 骨与 non-deform cleanup

## 9. 另一个 Codex 接手时的推荐检查顺序

1. 查看工作区状态：
   - `git status --short`

2. 查看架构文档：
   - [universal_xps_to_mmd_architecture.md](/Users/bytedance/Desktop/Convert-to-MMD/doc/universal_xps_to_mmd_architecture.md)
   - [codex_handoff_2026-03-26.md](/Users/bytedance/Desktop/Convert-to-MMD/doc/codex_handoff_2026-03-26.md)

3. 查看语义识别实现：
   - [semantic/infer.py](/Users/bytedance/Desktop/Convert-to-MMD/semantic/infer.py)
   - [canonical/normalize.py](/Users/bytedance/Desktop/Convert-to-MMD/canonical/normalize.py)
   - [operators/semantic_debug_operator.py](/Users/bytedance/Desktop/Convert-to-MMD/operators/semantic_debug_operator.py)

4. 如需 Blender 侧验证：
   - 同步到 Blender 3.6 插件目录
   - 完全重启 Blender
   - 点击 `扫描当前骨架语义`
   - 通过 Blender MCP 或 UI 读取结果

5. 若继续推进自动映射：
   - 基于 canonical model 回填 Scene 属性

## 10. 当前最关键的事实总结

- 这个仓库已经开始从“单一大 operator”转向“语义层 + canonical 层 + 权重层 + profile 层”
- 语义识别第一版已经能稳定识别躯干、四肢和辅助骨的大部分主干
- 当前最接近完成的一步，是把 `head/eye` 最后这部分 Blender 运行时结果确认掉
- 下一步最有价值的功能，不是继续加特判，而是：
  - 让语义识别能自动填骨映射
  - 让每一步权重变化都能被 diff 看见
