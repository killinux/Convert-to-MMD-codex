from .base_profile import ConversionProfile


XNA_LARA_PROFILE = ConversionProfile(
    name="xna_lara",
    helper_redirects={
        "unused bip001 xtra02": "足D.R",
        "unused bip001 xtra04": "足D.L",
        "unused bip001 pelvis": {"target": "下半身", "scale": 0.65},
        "unused bip001 xtra08": {"target": "下半身", "scale": 0.35},
        "unused bip001 xtra08opp": {"target": "下半身", "scale": 0.35},
        "unused muscle_elbow_l": "左腕",
        "unused muscle_elbow_r": "右腕",
    },
    foretwist_redirects={
        "unused bip001 l foretwist": "手捩.L",
        "unused bip001 l foretwist1": "手捩.L",
        "unused bip001 r foretwist": "手捩.R",
        "unused bip001 r foretwist1": "手捩.R",
        "unused bip001 xtra07pp": "左肩",
        "unused bip001 xtra07": "右肩",
    },
    metadata={
        "description": "Profile for XNA Lara / common XPS helper-bone naming.",
    },
)
