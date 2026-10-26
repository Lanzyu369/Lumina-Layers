// =========================================================================
// Gradient Color Swatch Card Storage Box — OpenSCAD
// 梯度色卡收纳盒（合盖式 · 深帽盖）
//
// Stepped-rim snap-on deep-cap lid.
// Box walls step inward near the top; lid outer walls extend
// from plate down to near box base; inner lip catches the ledge.
// No overhangs, no supports needed.
//
// 盒壁顶部内缩形成台阶，盖子外壁从顶板延伸到盒底附近，
// 内唇卡住台阶扣合。无悬垂，无需支撑。
// =========================================================================

// --- Card dimensions / 色卡尺寸 (实测) ---
card_w       = 67.0;   // 色卡长边 (mm)
card_h       = 34.0;   // 色卡短边 / 竖放高度 (mm)
card_t       = 2.88;   // 色卡厚度 (mm, 实测值)

// --- Box parameters / 盒体参数 ---
num_cards    = 20;      // 每盒色卡数量
wall         = 2.0;     // 厚壁段壁厚 (mm)
floor_t      = 1.5;     // 底板厚度 (mm)
groove_t     = 1.0;     // 凹槽隔条厚度 (mm)
groove_h     = 10.0;    // 凹槽隔条高度 (mm)
expose       = 12.0;    // 色卡露出盒口的高度 (mm)
step_inset   = 1.2;     // 台阶内缩量：厚壁→薄壁缩进多少 (mm)
step_depth   = 8.0;     // 台阶区高度：薄壁段有多高 (mm)

// --- Tolerances / 公差 (FDM 优化) ---
// slot_clearance:  0.22 mm → 每侧 0.11 mm (槽宽 3.1 mm)
// width_clearance: 0.60 mm → 每侧 0.30 mm
// lid_clearance:   0.30 mm (紧扣但可拆)
slot_clearance  = 0.22;  // 厚度方向总间隙 (mm)
width_clearance = 0.60;  // 宽度方向总间隙 (mm)
lid_clearance   = 0.30;  // 盖子与盒壁间隙 (mm)

// --- Lid parameters / 盖子参数 ---
plate        = 1.5;     // 盖子顶板厚度 (mm)
lid_wall     = 1.5;     // 盖子外壁厚度 (mm)
top_clearance = 2.0;    // 盖内顶面与色卡顶部的间隙 (mm)

// =========================================================================
// Derived dimensions — do not edit
// =========================================================================

slot  = card_t + slot_clearance;
ix    = num_cards * slot + (num_cards + 1) * groove_t;
iy    = card_w + width_clearance;

wall_h = card_h - expose;
thin   = wall - step_inset;

ox = ix + 2 * wall;
oy = iy + 2 * wall;
oz = wall_h + floor_t;
step_z = oz - step_depth;

// Lid derived
card_top_z     = floor_t + card_h;
plate_inner_z  = card_top_z + top_clearance;
gap            = lid_clearance;

lx      = ox + 2 * gap + 2 * lid_wall;
ly      = oy + 2 * gap + 2 * lid_wall;
outer_h = plate_inner_z - 1.0;
lip_h   = plate_inner_z - step_z - 1.0;
lip_t   = step_inset - gap;
lip_off = lid_wall + gap + thin + gap;

// =========================================================================
// Box body module
// =========================================================================

module box_body() {
    // Floor
    cube([ox, oy, floor_t]);

    // --- Left wall: thick then thin ---
    translate([0, 0, floor_t])
        cube([wall, oy, step_z - floor_t]);
    translate([step_inset, 0, step_z])
        cube([thin, oy, oz - step_z]);

    // --- Right wall ---
    translate([ox - wall, 0, floor_t])
        cube([wall, oy, step_z - floor_t]);
    translate([ox - step_inset - thin, 0, step_z])
        cube([thin, oy, oz - step_z]);

    // --- Front wall ---
    translate([wall, 0, floor_t])
        cube([ox - 2 * wall, wall, step_z - floor_t]);
    translate([wall, step_inset, step_z])
        cube([ox - 2 * wall, thin, oz - step_z]);

    // --- Back wall ---
    translate([wall, oy - wall, floor_t])
        cube([ox - 2 * wall, wall, step_z - floor_t]);
    translate([wall, oy - step_inset - thin, step_z])
        cube([ox - 2 * wall, thin, oz - step_z]);

    // --- Groove ridges ---
    for (i = [0 : num_cards]) {
        gx = wall + i * (slot + groove_t);
        translate([gx, wall, floor_t])
            cube([groove_t, oy - 2 * wall, groove_h]);
    }
}

// =========================================================================
// Lid module  (modeled in print orientation: plate on bed)
// =========================================================================

module lid() {
    w = lid_wall;

    // Plate
    cube([lx, ly, plate]);

    // --- Outer walls (4 sides) ---
    // Left
    translate([0, 0, plate])
        cube([w, ly, outer_h]);
    // Right
    translate([lx - w, 0, plate])
        cube([w, ly, outer_h]);
    // Front
    translate([w, 0, plate])
        cube([lx - 2 * w, w, outer_h]);
    // Back
    translate([w, ly - w, plate])
        cube([lx - 2 * w, w, outer_h]);

    // --- Inner lip (4 sides) ---
    // Left lip
    translate([lip_off, w, plate])
        cube([lip_t, ly - 2 * w, lip_h]);
    // Right lip
    translate([lx - lip_off - lip_t, w, plate])
        cube([lip_t, ly - 2 * w, lip_h]);
    // Front lip
    translate([w, lip_off, plate])
        cube([lx - 2 * w, lip_t, lip_h]);
    // Back lip
    translate([w, ly - lip_off - lip_t, plate])
        cube([lx - 2 * w, lip_t, lip_h]);
}

// =========================================================================
// Render — box and lid side by side
// =========================================================================

// Box body (left)
box_body();

// Lid (right, separated by 10 mm gap)
translate([ox + 10, 0, 0])
    lid();

// =========================================================================
// Summary (shown in console with echo)
// =========================================================================
echo(str(
    "\n=== Snap-On Lid Gradient-Card Box ===",
    "\n  Card: ", card_w, " x ", card_h, " x ", card_t, " mm",
    "\n  Slots: ", num_cards,
    "\n  Box:  ", ox, " x ", oy, " x ", oz, " mm",
    "\n    Wall: ", wall_h, " mm tall, card exposed: ", expose, " mm",
    "\n    Step: ", step_inset, " mm inset, ", step_depth, " mm deep",
    "\n  Lid:  ", lx, " x ", ly, " x ", plate + outer_h, " mm",
    "\n    Outer walls: ", outer_h, " mm, inner lip: ", lip_t, " x ", lip_h, " mm",
    "\n  Groove: ", groove_t, " x ", groove_h, " mm",
    "\n  Tolerances:",
    "\n    Slot: ", slot_clearance, " mm total (", slot_clearance/2, " mm/side)",
    "\n    Width: ", width_clearance, " mm total (", width_clearance/2, " mm/side)",
    "\n    Lid gap: ", lid_clearance, " mm",
    "\n  Print: box upright, lid upside-down (plate on bed). No supports."
));
