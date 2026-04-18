#!/usr/bin/env python3
"""
Generate a 3D-printable storage box for gradient color swatch cards.
生成可 3D 打印的梯度色卡收纳盒（合盖式）。

Stepped-rim snap-on lid — box walls step inward near the top,
lid drops over with an inner lip catching the ledge.
No overhangs, no supports needed.

盒壁顶部内缩形成台阶，盖子内唇卡住台阶扣合。无悬垂，无需支撑。

Usage:
    python scripts/generate_swatch_box.py
    python scripts/generate_swatch_box.py --num-cards 10
"""
from __future__ import annotations

import argparse
import os

import numpy as np


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _box(x0, y0, z0, x1, y1, z1):
    v = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=np.float64)
    f = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [2, 3, 7], [2, 7, 6],
        [0, 4, 7], [0, 7, 3],
        [1, 2, 6], [1, 6, 5],
    ], dtype=np.int64)
    return v, f


def _merge(parts):
    all_v, all_f, off = [], [], 0
    for v, f in parts:
        all_v.append(v)
        all_f.append(f + off)
        off += len(v)
    return np.vstack(all_v), np.vstack(all_f)


# ---------------------------------------------------------------------------
# Box body
# ---------------------------------------------------------------------------
#
#  Cross-section (front/back wall, Y-Z):
#
#   Full wall (0 → step_z)       Thin wall (step_z → oz)
#   ┌─wall─┐                     ┌thin┐
#   │      │                     │    │
#   │      │   ← step_z ─────── │    │  ← ledge for lid lip
#   │      │                     │    │
#   │      └─────────────────────┘    │
#   │           floor                 │
#   └─────────────────────────────────┘
#
#   The step (wall→thin) creates a ledge. The lid's inner lip
#   sits on this ledge. No overhangs — both box and lid print
#   upright without supports.
#

def build_box_body(
    card_w=67.0, card_h=34.0, card_t=2.88,
    num_cards=20,
    slot_clearance=0.22,
    width_clearance=0.6,
    wall=2.0,
    floor=1.5,
    groove_t=1.0,
    groove_h=3.0,
    expose=12.0,
    step_inset=1.2,
    step_depth=8.0,
    lid_clearance=0.3,
):
    """
    Tolerance notes (FDM-optimized):
      slot_clearance:  total gap around card thickness.
                       0.22 mm → 0.11 mm/side (slot = 3.1 mm for 2.88 mm card).
      width_clearance: total gap around card long edge.
                       0.6 mm → 0.30 mm/side — comfortable lateral play.
      lid_clearance:   gap between lid and box walls.
                       0.3 mm — snug snap fit, removable by hand.

    公差说明（FDM 优化）：
      slot_clearance  = 0.22 mm（厚度方向，每侧 0.11 mm，槽宽 3.1 mm）
      width_clearance = 0.6 mm（宽度方向，每侧 0.30 mm）
      lid_clearance   = 0.3 mm（盖子与盒壁间隙）

    Args:
        expose: How far cards stick above box rim (mm). (色卡露出高度)
        step_inset: Wall inset at top step (mm). (台阶内缩量)
        step_depth: Height of thinned step section (mm). (台阶高度)
    """
    slot = card_t + slot_clearance
    ix = num_cards * slot + (num_cards + 1) * groove_t
    iy = card_w + width_clearance

    wall_h = card_h - expose
    ox = ix + 2 * wall
    oy = iy + 2 * wall
    oz = wall_h + floor
    step_z = oz - step_depth
    thin = wall - step_inset

    parts = []
    # Floor
    parts.append(_box(0, 0, 0, ox, oy, floor))

    # --- Left wall: full then thin ---
    parts.append(_box(0, 0, floor, wall, oy, step_z))
    parts.append(_box(step_inset, 0, step_z, step_inset + thin, oy, oz))
    # --- Right wall ---
    parts.append(_box(ox - wall, 0, floor, ox, oy, step_z))
    parts.append(_box(ox - step_inset - thin, 0, step_z, ox - step_inset, oy, oz))
    # --- Front wall ---
    parts.append(_box(wall, 0, floor, ox - wall, wall, step_z))
    parts.append(_box(wall, step_inset, step_z, ox - wall, step_inset + thin, oz))
    # --- Back wall ---
    parts.append(_box(wall, oy - wall, floor, ox - wall, oy, step_z))
    parts.append(_box(wall, oy - step_inset - thin, step_z, ox - wall, oy - step_inset, oz))

    # Groove ridges
    for i in range(num_cards + 1):
        gx = wall + i * (slot + groove_t)
        parts.append(_box(gx, wall, floor, gx + groove_t, oy - wall, floor + groove_h))

    v, f = _merge(parts)
    info = dict(
        ox=ox, oy=oy, oz=oz, step_z=step_z,
        wall=wall, thin=thin, floor=floor,
        expose=expose, wall_h=wall_h,
        step_inset=step_inset, step_depth=step_depth,
        lid_clearance=lid_clearance,
        groove_t=groove_t, groove_h=groove_h,
        slot=slot, num_cards=num_cards,
        slot_clearance=slot_clearance,
        width_clearance=width_clearance,
    )
    return v, f, info


# ---------------------------------------------------------------------------
# Snap-on lid  (prints upside-down, plate on bed)
# ---------------------------------------------------------------------------
#
#  Cross-section (Y-Z):
#
#   ┌───────────────────────────────────────┐  ← plate (top when placed)
#   │  ┌─outer─┐                ┌─outer─┐  │
#   │  │       │  ┌─inner lip─┐ │       │  │
#   │  │       │  │           │ │       │  │
#   │  │       │  └───────────┘ │       │  │
#   │  └───────┘                └───────┘  │
#   └───────────────────────────────────────┘
#
#   outer walls wrap outside the box; inner lip sits on the step ledge.
#   Printed plate-down — no overhangs.
#

def build_lid(info, plate=1.5, lid_wall=1.5):
    ox = info["ox"]
    oy = info["oy"]
    sd = info["step_depth"]
    si = info["step_inset"]
    thin = info["thin"]
    gap = info["lid_clearance"]
    expose = info["expose"]

    # Outer footprint
    lx = ox + 2 * gap + 2 * lid_wall
    ly = oy + 2 * gap + 2 * lid_wall
    # Outer walls: cover exposed cards + overlap with step zone
    outer_h = expose + sd
    lip_h = sd - 1.0    # inner lip height (shorter to clear step)
    lip_t = si - gap     # lip thickness fits between step inset and thin wall

    parts = []
    # Plate
    parts.append(_box(0, 0, 0, lx, ly, plate))

    w = lid_wall
    # Outer walls (4 sides)
    parts.append(_box(0, 0, plate, w, ly, plate + outer_h))
    parts.append(_box(lx - w, 0, plate, lx, ly, plate + outer_h))
    parts.append(_box(w, 0, plate, lx - w, w, plate + outer_h))
    parts.append(_box(w, ly - w, plate, lx - w, ly, plate + outer_h))

    # Inner lip (4 sides) — offset inward from outer wall
    # Lip position: outer_wall + gap + box_wall_at_step = w + gap + thin
    lip_off = w + gap + thin + gap  # from lid edge to lip inner face
    lip_z0 = plate
    lip_z1 = plate + lip_h

    # left lip
    parts.append(_box(lip_off, w, lip_z0, lip_off + lip_t, ly - w, lip_z1))
    # right lip
    parts.append(_box(lx - lip_off - lip_t, w, lip_z0, lx - lip_off, ly - w, lip_z1))
    # front lip
    parts.append(_box(w, lip_off, lip_z0, lx - w, lip_off + lip_t, lip_z1))
    # back lip
    parts.append(_box(w, ly - lip_off - lip_t, lip_z0, lx - w, ly - lip_off, lip_z1))

    v, f = _merge(parts)
    lid_info = dict(lx=lx, ly=ly, total_z=plate + outer_h,
                    outer_h=outer_h, lip_h=lip_h, lip_t=lip_t)
    return v, f, lid_info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Generate snap-on lid gradient-card storage box STL files."
    )
    ap.add_argument("--card-width", type=float, default=67.0)
    ap.add_argument("--card-height", type=float, default=34.0)
    ap.add_argument("--card-thickness", type=float, default=2.88)
    ap.add_argument("--num-cards", type=int, default=20)
    ap.add_argument("--output-dir", type=str, default="output/models")
    args = ap.parse_args()

    import trimesh

    bv, bf, info = build_box_body(
        card_w=args.card_width, card_h=args.card_height,
        card_t=args.card_thickness, num_cards=args.num_cards,
    )
    box_mesh = trimesh.Trimesh(vertices=bv, faces=bf, process=True)

    lv, lf, li = build_lid(info)
    lid_mesh = trimesh.Trimesh(vertices=lv, faces=lf, process=True)

    os.makedirs(args.output_dir, exist_ok=True)
    bp = os.path.join(args.output_dir, "swatch_box_body.stl")
    lp = os.path.join(args.output_dir, "swatch_box_lid.stl")
    box_mesh.export(bp)
    lid_mesh.export(lp)

    print(f"\n=== Snap-On Lid Gradient-Card Box ===")
    print(f"  Card: {args.card_width} x {args.card_height} x {args.card_thickness} mm")
    print(f"  Slots: {args.num_cards}")
    print(f"  Box:   {bp}  ({info['ox']:.1f} x {info['oy']:.1f} x {info['oz']:.1f} mm)")
    print(f"    Wall: {info['wall_h']:.1f} mm tall, card exposed: {info['expose']:.1f} mm")
    print(f"    Step: {info['step_inset']:.1f} mm inset, {info['step_depth']:.1f} mm deep")
    print(f"  Lid:   {lp}  ({li['lx']:.1f} x {li['ly']:.1f} x {li['total_z']:.1f} mm)")
    print(f"    Outer walls: {li['outer_h']:.1f} mm, inner lip: {li['lip_t']:.1f} mm x {li['lip_h']:.1f} mm")
    print(f"  Groove: {info['groove_t']:.1f} mm x {info['groove_h']:.1f} mm")
    print(f"  Tolerances:")
    print(f"    Slot (thickness): {info['slot_clearance']:.1f} mm total ({info['slot_clearance']/2:.2f} mm/side)")
    print(f"    Width:            {info['width_clearance']:.1f} mm total ({info['width_clearance']/2:.2f} mm/side)")
    print(f"    Lid gap:          {info['lid_clearance']:.1f} mm")
    print(f"\n  Print: box upright (open up), lid upside-down (plate on bed).")
    print(f"  No supports needed.\n")


if __name__ == "__main__":
    main()
