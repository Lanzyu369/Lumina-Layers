from __future__ import annotations

import pytest

from tools.machine_adapter.providers import get_provider


def test_vendor_slicers_reuse_bambu_orca_profile_format():
    elegoo = get_provider("ElegooSlicer")
    anycubic = get_provider("AnycubicSlicerNext")
    flashforge = get_provider("FlashStudio")
    qidi = get_provider("QIDIStudio")

    assert elegoo.profile_format == "bambu_orca"
    assert elegoo.sidecar_policy == "orca_like"
    assert elegoo.default_vendor_keys == ("Elegoo",)
    assert anycubic.profile_format == "bambu_orca"
    assert anycubic.sidecar_policy == "anycubic_next"
    assert anycubic.default_vendor_keys == ("Anycubic",)
    assert anycubic.default_application_metadata == "AnycubicSlicerNext-1.4.1.2"
    assert anycubic.default_client_version == "1.4.1.2 20260604104233"
    assert flashforge.profile_format == "bambu_orca"
    assert flashforge.sidecar_policy == "orca_like"
    assert flashforge.default_vendor_keys == ("Flashforge",)
    assert flashforge.default_application_metadata == "BambuStudio-2.3.2"
    assert flashforge.default_client_version == ""
    assert qidi.profile_format == "bambu_orca"
    assert qidi.sidecar_policy == "qidi_studio"
    assert qidi.default_vendor_keys == ("Q Series", "X 4 Series", "X 5 Series")
    assert qidi.default_application_metadata == "QIDIStudio-02.07.02.60"
    assert qidi.default_client_version == "02.07.02.60"


def test_unknown_provider_is_rejected():
    with pytest.raises(KeyError, match="Unsupported machine adapter provider"):
        get_provider("Cura")
