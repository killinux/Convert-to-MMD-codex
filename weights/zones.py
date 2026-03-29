from dataclasses import dataclass, field


@dataclass
class ZoneMasks:
    upper: set[int] = field(default_factory=set)
    hip: set[int] = field(default_factory=set)
    lower: set[int] = field(default_factory=set)
    knee_l: set[int] = field(default_factory=set)
    knee_r: set[int] = field(default_factory=set)


def build_zone_masks(mesh_obj, armature_obj, model) -> ZoneMasks:
    """Build region masks for later zone-based weight processing.

    Placeholder implementation: returns empty masks until the first
    zone-based refactor lands.
    """
    return ZoneMasks()

