from .model import StepExecutionReport, StepExecutionStage


def build_step2_execution_report(
    copied_pairs,
    lower_body_seeded,
    lower_body_seed_details,
    d_follow_applied,
    spine_redistributed,
    hip_modified,
    thigh_root_restored,
    mid_thigh_reinforced,
    normalized,
):
    stages = [
        StepExecutionStage(
            stage_id="2.1",
            label="腿部 FK -> D骨 权重复制",
            status="info",
            metrics={
                "copied_pairs": copied_pairs,
            },
            notes=["建立足D/ひざD/足首D/足先EX 的基础权重来源"],
        ),
        StepExecutionStage(
            stage_id="2.2",
            label="下半身基础权重初始化",
            status="info" if lower_body_seeded > 0 else "warning",
            metrics={
                "lower_body_seeded": lower_body_seeded,
            },
            notes=lower_body_seed_details[:6] or ["未从 helper 初始化下半身权重"],
        ),
        StepExecutionStage(
            stage_id="2.3",
            label="D骨跟随与上半身1分配",
            status="info",
            metrics={
                "d_follow_applied": int(bool(d_follow_applied)),
                "spine_redistributed": spine_redistributed,
            },
            notes=["D系骨骼附加变换已尝试应用", "上半身1/2 过渡已重分配"],
        ),
        StepExecutionStage(
            stage_id="2.4",
            label="髋部渐变与腿根带修正",
            status="info" if hip_modified > 0 or thigh_root_restored > 0 else "warning",
            metrics={
                "hip_modified": hip_modified,
                "thigh_root_restored": thigh_root_restored,
                "mid_thigh_reinforced": mid_thigh_reinforced,
            },
            notes=[
                "髋部顶端创建下半身/足D 过渡带",
                "腿根上缘恢复本侧足D参与带",
                "上大腿中段补强本侧足D控制带",
            ],
        ),
        StepExecutionStage(
            stage_id="2.5",
            label="变形骨归一化",
            status="info",
            metrics={
                "normalized_vertices": normalized,
            },
            notes=["将变形骨总权重归一化，避免 >1 或过低残留"],
        ),
    ]

    summary_parts = [
        f"2.1复制={copied_pairs}",
        f"2.2下半身初始化={lower_body_seeded}",
        f"2.3脊柱分配={'yes' if spine_redistributed else 'no'}",
        f"2.4髋部={hip_modified}/腿根={thigh_root_restored}/大腿={mid_thigh_reinforced}",
        f"2.5归一化={normalized}",
    ]
    return StepExecutionReport(
        step_id="step_2",
        label="补全缺失骨骼",
        stages=stages,
        summary=" | ".join(summary_parts),
    )
