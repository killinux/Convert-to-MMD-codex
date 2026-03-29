from dataclasses import dataclass, field


WATCHED_BONES = [
    "腰",
    "足D.L",
    "足D.R",
    "ひざD.L",
    "ひざD.R",
    "足首D.L",
    "足首D.R",
    "足先EX.L",
    "足先EX.R",
    "下半身",
    "上半身",
    "上半身1",
    "上半身2",
    "上半身3",
    "左肩",
    "右肩",
    "左腕",
    "右腕",
    "左ひじ",
    "右ひじ",
    "腕捩.L",
    "腕捩.R",
    "手捩.L",
    "手捩.R",
    "肩.L",
    "肩.R",
    "肩P.L",
    "肩P.R",
    "肩C.L",
    "肩C.R",
]

D_CONFLICT_THRESHOLD = 0.6

REGION_BONES = {
    "torso": {
        "腰",
        "下半身",
        "上半身",
        "上半身1",
        "上半身2",
        "上半身3",
    },
    "left_leg": {
        "左足",
        "左ひざ",
        "左足首",
        "左足先EX",
        "足D.L",
        "ひざD.L",
        "足首D.L",
        "足先EX.L",
    },
    "right_leg": {
        "右足",
        "右ひざ",
        "右足首",
        "右足先EX",
        "足D.R",
        "ひざD.R",
        "足首D.R",
        "足先EX.R",
    },
    "arms": {
        "左肩",
        "右肩",
        "左腕",
        "右腕",
        "左ひじ",
        "右ひじ",
        "腕捩.L",
        "腕捩.R",
        "手捩.L",
        "手捩.R",
        "肩.L",
        "肩.R",
        "肩P.L",
        "肩P.R",
        "肩C.L",
        "肩C.R",
    },
}


@dataclass
class BoneWeightStats:
    vertex_count: int = 0
    weight_sum: float = 0.0


@dataclass
class WeightSnapshot:
    bone_stats: dict[str, BoneWeightStats] = field(default_factory=dict)
    region_stats: dict[str, BoneWeightStats] = field(default_factory=dict)
    hip_left_binary: int = 0
    hip_right_binary: int = 0
    hip_left_blend: int = 0
    hip_right_blend: int = 0
    conflict_count: int = 0
    total_verts: int = 0

    def to_legacy_dict(self) -> dict:
        return {
            "bone_counts": {name: stats.vertex_count for name, stats in self.bone_stats.items()},
            "bone_sums": {name: stats.weight_sum for name, stats in self.bone_stats.items()},
            "region_counts": {name: stats.vertex_count for name, stats in self.region_stats.items()},
            "region_sums": {name: stats.weight_sum for name, stats in self.region_stats.items()},
            "hip_left_binary": self.hip_left_binary,
            "hip_right_binary": self.hip_right_binary,
            "hip_left_blend": self.hip_left_blend,
            "hip_right_blend": self.hip_right_blend,
            "conflict_count": self.conflict_count,
            "total_verts": self.total_verts,
        }


def get_mesh_objects(context, armature):
    return [
        obj for obj in context.scene.objects
        if obj.type == 'MESH' and any(
            mod.type == 'ARMATURE' and mod.object == armature for mod in obj.modifiers
        )
    ]


def take_weight_snapshot(armature, mesh_objects):
    bone_stats = {name: BoneWeightStats() for name in WATCHED_BONES}
    region_stats = {name: BoneWeightStats() for name in REGION_BONES}

    hip_left_binary = 0
    hip_left_blend = 0
    hip_right_binary = 0
    hip_right_blend = 0
    conflict_count = 0

    for obj in mesh_objects:
        idx_to_name = {}
        for name in WATCHED_BONES:
            vg = obj.vertex_groups.get(name)
            if vg:
                idx_to_name[vg.index] = name

        vg_dl = obj.vertex_groups.get("足D.L")
        vg_dr = obj.vertex_groups.get("足D.R")
        vg_s = obj.vertex_groups.get("下半身")
        idx_dl = vg_dl.index if vg_dl else -1
        idx_dr = vg_dr.index if vg_dr else -1
        idx_s = vg_s.index if vg_s else -1

        mw = obj.matrix_world
        z_max_l = z_max_r = -999999.0
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == idx_dl and g.weight > 0.001:
                    vz = (mw @ v.co).z
                    if vz > z_max_l:
                        z_max_l = vz
                elif g.group == idx_dr and g.weight > 0.001:
                    vz = (mw @ v.co).z
                    if vz > z_max_r:
                        z_max_r = vz

        z_top_l = z_max_l - 1.5
        z_top_r = z_max_r - 1.5

        for v in obj.data.vertices:
            vz = None
            wd_l = wd_r = ws = 0.0
            region_weights = {name: 0.0 for name in REGION_BONES}

            for g in v.groups:
                gidx = g.group
                weight = g.weight

                if gidx in idx_to_name and weight > 0.001:
                    name = idx_to_name[gidx]
                    stats = bone_stats.setdefault(name, BoneWeightStats())
                    stats.vertex_count += 1
                    stats.weight_sum += weight
                    for region_name, region_bones in REGION_BONES.items():
                        if name in region_bones:
                            region_weights[region_name] += weight

                if gidx == idx_dl:
                    wd_l = weight
                elif gidx == idx_dr:
                    wd_r = weight
                elif gidx == idx_s:
                    ws = weight

            for region_name, total_weight in region_weights.items():
                if total_weight > 0.001:
                    stats = region_stats.setdefault(region_name, BoneWeightStats())
                    stats.vertex_count += 1
                    stats.weight_sum += total_weight

            if wd_l > 0.001 and z_max_l > -999990:
                if vz is None:
                    vz = (mw @ v.co).z
                if vz >= z_top_l:
                    if ws > 0.05:
                        hip_left_blend += 1
                    elif wd_l > 0.85:
                        hip_left_binary += 1

            if wd_r > 0.001 and z_max_r > -999990:
                if vz is None:
                    vz = (mw @ v.co).z
                if vz >= z_top_r:
                    if ws > 0.05:
                        hip_right_blend += 1
                    elif wd_r > 0.85:
                        hip_right_binary += 1

            if wd_l + wd_r >= D_CONFLICT_THRESHOLD and ws > 0.001:
                conflict_count += 1

    total_verts = sum(len(obj.data.vertices) for obj in mesh_objects)
    bone_stats = {name: stats for name, stats in bone_stats.items() if stats.vertex_count or stats.weight_sum}
    region_stats = {name: stats for name, stats in region_stats.items() if stats.vertex_count or stats.weight_sum}
    return WeightSnapshot(
        bone_stats=bone_stats,
        region_stats=region_stats,
        hip_left_binary=hip_left_binary,
        hip_right_binary=hip_right_binary,
        hip_left_blend=hip_left_blend,
        hip_right_blend=hip_right_blend,
        conflict_count=conflict_count,
        total_verts=total_verts,
    )
