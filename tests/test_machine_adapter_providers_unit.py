from __future__ import annotations

import pytest

from tools.machine_adapter.providers import get_provider


def test_vendor_slicers_reuse_bambu_orca_profile_format():
    elegoo = get_provider("ElegooSlicer")
    anycubic = get_provider("AnycubicSlicerNext")
    flashforge = get_provider("FlashStudio")
    qidi = get_provider("QIDIStudio")

    assert elegoo.profile_format == "bambu_orca"
    assert elegoo.default_vendor_keys == ("Elegoo",)
    assert anycubic.profile_format == "bambu_orca"
    assert anycubic.default_vendor_keys == ("Anycubic",)
    assert flashforge.profile_format == "bambu_orca"
    assert flashforge.default_vendor_keys == ("Flashforge",)
    assert qidi.profile_format == "bambu_orca"
    assert qidi.default_vendor_keys == ("Q Series", "X 4 Series", "X 5 Series")


def test_unknown_provider_is_rejected():
    with pytest.raises(KeyError, match="Unsupported machine adapter provider"):
        get_provider("Cura")
