from .generic_xps import GENERIC_XPS_PROFILE
from .xna_lara import XNA_LARA_PROFILE


DEFAULT_PROFILE_NAME = XNA_LARA_PROFILE.name


PROFILES = {
    XNA_LARA_PROFILE.name: XNA_LARA_PROFILE,
    GENERIC_XPS_PROFILE.name: GENERIC_XPS_PROFILE,
}


def get_profile(name: str = DEFAULT_PROFILE_NAME):
    return PROFILES.get(name, XNA_LARA_PROFILE)


def get_default_profile():
    return get_profile(DEFAULT_PROFILE_NAME)

