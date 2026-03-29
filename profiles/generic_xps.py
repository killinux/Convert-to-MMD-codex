from .base_profile import ConversionProfile


GENERIC_XPS_PROFILE = ConversionProfile(
    name="generic_xps",
    helper_redirects={},
    foretwist_redirects={},
    metadata={
        "description": "Conservative profile for generic XPS sources.",
    },
)

