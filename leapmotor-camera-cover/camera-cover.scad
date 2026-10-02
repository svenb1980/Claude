// Leapmotor B05 interior camera privacy cover — sliding shutter
// Parametric: measure your camera and adjust the values below.
// All dimensions in mm.
//
// Two parts:
//   base    – stuck around the camera with thin double-sided tape (has the window)
//   shutter – slides in dovetail rails over the window (closed) or beside it (open)
//
// Print both flat, bottom-side down, no supports. PETG or ASA recommended
// (PLA softens in a hot car). Use an opaque dark colour so it also blocks the
// camera's infrared light.

/* [Camera — measure these] */
// Width of the dark camera window (lens + IR LEDs), along the slide direction
win_w = 22;
// Height of the dark camera window, across the slide direction
win_h = 12;
// Corner radius of the window opening
win_r = 2;

/* [Fit] */
// How far the shutter covers past the window on each side
overlap = 3;
// Sideways sliding clearance per side (raise if too tight, lower if loose)
gap = 0.25;
// Height of the click bumps holding the shutter open/closed (0 = no clicks)
detent_h = 0.4;

/* [Shape] */
// Thickness of the plate under the shutter
base_t = 1.6;
// Shutter thickness
shutter_t = 1.6;
// Width of each rail footprint
rail_w = 4;
// Solid end stop past the closed position
end_wall = 2.5;
// Outer corner radius
corner_r = 2;
// Parts to render
part = "both"; // [both, base, shutter, assembly_closed, assembly_open]

/* [Hidden] */
$fn = 48;
zgap   = 0.2;                       // vertical play above the shutter
rail_h = shutter_t + zgap;
sl     = win_w + 2 * overlap;       // shutter length (slide direction)
sw     = win_h + 2 * overlap;       // shutter width at its base
cw     = sw + 2 * gap;              // channel width at the deck
W      = cw + 2 * rail_w;           // base width
L      = end_wall + sl + win_w + 2 * overlap + 1;   // base length, room to park the shutter
H      = base_t + rail_h;           // base total height
closed_x0 = L - end_wall - sl;      // shutter left edge when closed
win_cx = closed_x0 + sl / 2;        // window centre
det_r  = 0.6;                       // click bump radius
det_dx = 1.3;                       // bump position from the shutter's left edge

assert(det_dx + det_r < overlap, "overlap too small for the click bumps");
assert(rail_w > rail_h + 1, "rails too narrow for this shutter thickness");

module rrect(w, h, r) {
    offset(r) offset(-r) square([w, h]);
}

// Dovetail cross-section (y/z), extruded along x
module trapezoid(bottom, height) {
    polygon([[-bottom / 2, 0], [bottom / 2, 0],
             [bottom / 2 - height, height], [-bottom / 2 + height, height]]);
}

module along_x(len) {
    rotate([90, 0, 90]) linear_extrude(len) children();
}

module detent_ridge(x) {
    translate([x, W / 2 - (sw - 2) / 2, base_t + detent_h - det_r])
        rotate([-90, 0, 0]) cylinder(r = det_r, h = sw - 2);
}

module base() {
    difference() {
        linear_extrude(H) rrect(L, W, corner_r);
        // dovetail channel, open at the left end so the shutter slides in
        translate([-1, W / 2, base_t]) along_x(L - end_wall + 1)
            trapezoid(cw, rail_h + 0.01);
        // camera window
        translate([win_cx - win_w / 2, W / 2 - win_h / 2, -1])
            linear_extrude(base_t + 2) rrect(win_w, win_h, win_r);
    }
    if (detent_h > 0) {
        intersection() {
            union() {
                detent_ridge(closed_x0 + det_dx);   // holds it closed
                detent_ridge(det_dx);               // holds it open
            }
            translate([0, 0, base_t]) cube([L, W, rail_h]);
        }
    }
}

module shutter() {
    top_w = sw - 2 * shutter_t;
    difference() {
        // rounded ends so it slides past the click bumps smoothly
        intersection() {
            translate([0, sw / 2, 0]) along_x(sl) trapezoid(sw, shutter_t);
            linear_extrude(shutter_t) rrect(sl, sw, 1);
        }
        if (detent_h > 0)
            translate([det_dx, 0.5, 0]) rotate([-90, 0, 0])
                cylinder(r = det_r + 0.15, h = sw - 1);
    }
    // finger grip ridges
    for (i = [-1 : 1])
        translate([sl / 2 + i * 2.5 - 0.5, sw / 2 - (top_w - 2) / 2, shutter_t - 0.01])
            cube([1, top_w - 2, 0.8]);
}

if (part == "base" || part == "both") base();
if (part == "shutter" || part == "both") translate([0, W + 5, 0]) shutter();
// preview only: shutter mounted in the base
if (part == "assembly_closed" || part == "assembly_open") {
    base();
    color("orange")
        translate([part == "assembly_closed" ? closed_x0 : 0, W / 2 - sw / 2, base_t])
            shutter();
}

echo(str("Base footprint: ", L, " x ", W, " x ", H, " mm"));
