"""Color selection recommendation behavior. 颜色选择推荐行为。"""


def test_recommend_lut_colors_by_rgb_basic_ordering() -> None:
    """RGB 距离排序契约：红色基准下 ``#ff0000`` 必须排第一。
    Pin the RGB-distance ordering contract: under a red base the closest LUT
    entry must come first, smallest distance wins, ties broken by index.
    """
    from api.color_workstation_helpers import _recommend_lut_colors_by_rgb

    lut = [
        {"color": (255, 0, 0), "hex": "#ff0000"},
        {"color": (255, 255, 0), "hex": "#ffff00"},
        {"color": (0, 0, 255), "hex": "#0000ff"},
        {"color": (0, 255, 0), "hex": "#00ff00"},
    ]
    rec = _recommend_lut_colors_by_rgb((254, 2, 2), lut, top_k=2)
    assert len(rec) == 2
    assert rec[0]["hex"] == "#ff0000"
