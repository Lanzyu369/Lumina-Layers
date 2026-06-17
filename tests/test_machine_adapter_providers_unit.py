from __future__ import annotations

import pytest

from tools.machine_adapter.providers import get_provider


def test_elegoo_and_anycubic_reuse_bambu_orca_profile_format():
    elegoo = get_provider("ElegooSlicer")
    anycubic = get_provider("AnycubicSlicerNext")

    assert elegoo.profile_format == "bambu_orca"
    assert elegoo.sidecar_policy == "orca_like"
    assert elegoo.default_vendor_keys == ("Elegoo",)
    assert anycubic.profile_format == "bambu_orca"
    assert anycubic.sidecar_policy == "anycubic_next"
    assert anycubic.default_vendor_keys == ("Anycubic",)


def test_unknown_provider_is_rejected():
    with pytest.raises(KeyError, match="Unsupported machine adapter provider"):
        get_provider("Cura")
