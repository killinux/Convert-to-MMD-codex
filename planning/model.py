from dataclasses import dataclass, field
from typing import Literal


PlanMode = Literal["source_only", "source_plus_reference"]
BoneEntryType = Literal["source", "helper", "control_candidate", "deform_candidate"]
BoneEntryStatus = Literal["normal", "pending_transfer", "transferred", "missing", "empty", "abnormal"]
BoneKind = Literal["deform", "control", "helper"]
ExpectationKind = Literal["expected", "expected_risky", "unexpected"]
ChangeItemType = Literal["bone", "vertex_group", "weight_relation", "warning"]
Severity = Literal["info", "warning", "error"]


@dataclass
class PlanRisk:
    level: Severity
    message: str


@dataclass
class BoneWeightEntry:
    bone_name: str
    semantic_role: str = ""
    current_group_name: str = ""
    vertex_count: int = 0
    weight_sum: float = 0.0
    regions: list[str] = field(default_factory=list)
    geometry_side: Literal["left", "right", "center", "unknown"] = "unknown"
    entry_type: BoneEntryType = "source"
    status: BoneEntryStatus = "normal"
    source_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "bone_name": self.bone_name,
            "semantic_role": self.semantic_role,
            "current_group_name": self.current_group_name,
            "vertex_count": self.vertex_count,
            "weight_sum": self.weight_sum,
            "regions": self.regions,
            "geometry_side": self.geometry_side,
            "entry_type": self.entry_type,
            "status": self.status,
            "source_refs": self.source_refs,
            "confidence": self.confidence,
        }


@dataclass
class TargetWeightEntry:
    bone_name: str
    bone_kind: BoneKind = "deform"
    group_exists: bool = False
    vertex_count: int = 0
    weight_sum: float = 0.0
    regions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    status: BoneEntryStatus = "normal"

    def to_dict(self) -> dict:
        return {
            "bone_name": self.bone_name,
            "bone_kind": self.bone_kind,
            "group_exists": self.group_exists,
            "vertex_count": self.vertex_count,
            "weight_sum": self.weight_sum,
            "regions": self.regions,
            "source_refs": self.source_refs,
            "status": self.status,
        }


@dataclass
class StepChangeEntry:
    step_id: str
    item_type: ChangeItemType
    name: str
    before: str = ""
    after: str = ""
    expected: ExpectationKind = "expected"
    severity: Severity = "info"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "item_type": self.item_type,
            "name": self.name,
            "before": self.before,
            "after": self.after,
            "expected": self.expected,
            "severity": self.severity,
            "note": self.note,
        }


@dataclass
class StepExpectationRule:
    step_id: str
    allowed_bones: list[str] = field(default_factory=list)
    required_groups: list[str] = field(default_factory=list)
    forbidden_missing_groups: list[str] = field(default_factory=list)
    risky_regions: list[str] = field(default_factory=list)
    required_band_checks: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "allowed_bones": self.allowed_bones,
            "required_groups": self.required_groups,
            "forbidden_missing_groups": self.forbidden_missing_groups,
            "risky_regions": self.risky_regions,
            "required_band_checks": self.required_band_checks,
            "note": self.note,
        }


@dataclass
class WeightRelationshipSnapshot:
    source_entries: list[BoneWeightEntry] = field(default_factory=list)
    target_entries: list[TargetWeightEntry] = field(default_factory=list)
    step_changes: list[StepChangeEntry] = field(default_factory=list)
    expectation_rules: list[StepExpectationRule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_entries": [entry.to_dict() for entry in self.source_entries],
            "target_entries": [entry.to_dict() for entry in self.target_entries],
            "step_changes": [entry.to_dict() for entry in self.step_changes],
            "expectation_rules": [rule.to_dict() for rule in self.expectation_rules],
        }


@dataclass
class StepExecutionStage:
    stage_id: str
    label: str
    status: Severity = "info"
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage_id": self.stage_id,
            "label": self.label,
            "status": self.status,
            "metrics": self.metrics,
            "notes": self.notes,
        }


@dataclass
class StepExecutionReport:
    step_id: str
    label: str
    stages: list[StepExecutionStage] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "label": self.label,
            "stages": [stage.to_dict() for stage in self.stages],
            "summary": self.summary,
        }


@dataclass
class ConversionPlan:
    mode: PlanMode
    source_armature_name: str
    target_armature_name: str | None = None
    source_profile_guess: str = "generic_xps"
    source_recognized_count: int = 0
    target_recognized_count: int = 0
    direct_mapping: list[str] = field(default_factory=list)
    missing_in_source: list[str] = field(default_factory=list)
    missing_in_target: list[str] = field(default_factory=list)
    helper_roles: list[str] = field(default_factory=list)
    recommended_stages: list[str] = field(default_factory=list)
    manual_review_items: list[str] = field(default_factory=list)
    risks: list[PlanRisk] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source_armature_name": self.source_armature_name,
            "target_armature_name": self.target_armature_name,
            "source_profile_guess": self.source_profile_guess,
            "source_recognized_count": self.source_recognized_count,
            "target_recognized_count": self.target_recognized_count,
            "direct_mapping": self.direct_mapping,
            "missing_in_source": self.missing_in_source,
            "missing_in_target": self.missing_in_target,
            "helper_roles": self.helper_roles,
            "recommended_stages": self.recommended_stages,
            "manual_review_items": self.manual_review_items,
            "risks": [{"level": risk.level, "message": risk.message} for risk in self.risks],
        }
