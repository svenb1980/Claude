// Leapmotor B05 driver-camera privacy cover — flip-up lid
// Print-in-place: frame and lid print together as one piece, no supports.
// All dimensions in mm. Defaults are estimated from photos of the A-pillar
// camera pod (dark window ≈ 27-28 × 16-17.5 mm, ≈ 9 mm of face above it,
// ≈ 6-9 mm left/right, only ≈ 2 mm below) — check them with a ruler.
//
// Coordinates: X across the face, Y up the face, Z out of the face.
// The frame (U-shape: strip above the window + a leg on each side) is taped
// to the pod face. The lid hangs down over the window and flips up 180°
// to lie on top of the strip; small click bumps hold it closed and open.

/* [Camera window — measure these] */
// Width of the dark window including its black rim
win_w = 28;
// Height of the dark window including its black rim
win_h = 17.5;

/* [Fit] */
// How far the lid reaches past the window on each side
cover_ov = 1.5;
// Hinge axis height above the top of the window
axis_up = 1;
// Height of the tape strip above the hinge
strip_h = 5;
// Print-in-place gap between moving parts (raise if it fuses)
g = 0.35;
// Pin-in-hole clearance
pin_clear = 0.3;
// Click strength: how far the bumps press into the lid (0 = no clicks)
det = 0.15;
// Recess in the lid's back so it clears the window's raised rim
rim_pocket = 0.6;

/* [Shape] */
// Lid and frame thickness
t = 2;
// Hinge barrel radius
R = 2.6;
// Hinge pin radius
pin_r = 1.1;
// Frame leg width
et = 2.6;
// Preview only: lid angle (0 = closed, 180 = open)
open_angle = 0;
// Parts to render
part = "print"; // [print, preview]

/* [Hidden] */
$fn = 48;
lw      = win_w + 2 * cover_ov;           // lid width
lid_len = axis_up + win_h + cover_ov;     // lid length below the axis
fw      = lw + 2 * (g + et);              // frame width
ys      = R + 0.4;                        // strip starts here (barrel clearance)
leg_bot = -(axis_up + win_h);             // legs end level with window bottom
rho     = 2.0;                            // click bump distance from axis
rb      = g + det;                        // click bump radius

assert(rho + rb <= R, "click bump sticks out of the hinge barrel");
assert(rho - rb >= pin_r + pin_clear, "click bump overlaps the pin hole");
assert(rho - rb - g >= pin_r, "click dimple cuts the pin");

module rrect(w, h, r) { offset(r) offset(-r) square([w, h]); }

module teardrop_x(r, len) {               // horizontal hole, point up: no support
    rotate([0, 90, 0]) linear_extrude(len)
        hull() { circle(r); translate([-r * sqrt(2), 0]) square(0.01, center = true); }
}

module lid() {
    difference() {
        union() {
            translate([-lw / 2, -lid_len, 0])
                linear_extrude(t) rrect(lw, lid_len + 0.01, 2);
            translate([-lw / 2, 0, R]) rotate([0, 90, 0]) cylinder(r = R, h = lw);
            for (s = [-1, 1]) translate([s * lw / 2, 0, R]) rotate([0, s * 90, 0])
                cylinder(r = pin_r, h = g + et - 0.2);
            // finger grip on the bottom edge
            translate([-lw / 2 + 4, -lid_len + 0.4, t - 0.01])
                hull() { cube([lw - 8, 1.6, 0.01]); translate([0, 0.4, 0]) cube([lw - 8, 0.8, 1.2]); }
        }
        // clears the window's raised rim
        translate([-(win_w + 1) / 2, -axis_up - win_h - 0.5, -1])
            cube([win_w + 1, win_h + 1, 1 + rim_pocket]);
        // click dimples: closed and open (180°) positions
        if (det > 0) for (s = [-1, 1], y = [-rho, rho])
            translate([s * (lw / 2 + g), y, R]) sphere(rb + g);
    }
}

module frame() {
    difference() {
        union() {
            translate([-fw / 2, ys, 0]) linear_extrude(t) rrect(fw, strip_h, 1.5);
            for (s = [-1, 1]) {
                x0 = s > 0 ? lw / 2 + g : -(lw / 2 + g + et);
                translate([x0, leg_bot, 0]) cube([et, ys + 1.5 - leg_bot, t]);
                hull() {                  // ear around the hinge pin
                    translate([x0, 0, R]) rotate([0, 90, 0]) cylinder(r = R, h = et);
                    translate([x0, -R, 0]) cube([et, 2 * R, 0.01]);
                }
            }
        }
        for (s = [-1, 1])
            translate([s > 0 ? lw / 2 : -fw / 2 - 1, 0, R]) teardrop_x(pin_r + pin_clear, g + et + 1);
    }
    if (det > 0) for (s = [-1, 1])
        translate([s * (lw / 2 + g), -rho, R]) sphere(rb);
}

frame();
if (part == "preview") color("orange")
    translate([0, 0, R]) rotate([-open_angle, 0, 0]) translate([0, 0, -R]) lid();
else lid();

echo(str("Frame ", fw, " mm wide; needs ", axis_up + ys + strip_h,
         " mm of flat face above the window and ", g + et + cover_ov, " mm beside it"));
