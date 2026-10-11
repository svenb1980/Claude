// Leapmotor B05 driver-camera privacy cover — flip-up lid
// Print-in-place: frame and lid print together as one piece, no supports.
// All dimensions in mm. Defaults fit the A-pillar camera pod: face ≈ 18 mm
// tall, dark window incl. black rim ≈ 20 × 11.5 mm, ≈ 4 mm of face above it,
// ≈ 4.5 mm left/right, ≈ 2.5 mm below.
//
// Coordinates: X across the face, Y up the face, Z out of the face.
// The frame (strip above the window, a leg on each side and an optional
// crossbar below the lid) is taped to the pod face. The lid hangs down over
// the window and flips up 180° to lie on top of the strip; small click bumps hold it closed and open.

/* [Camera window — measure these] */
// Width of the dark window including its black rim
win_w = 20;
// Height of the dark window including its black rim
win_h = 11.5;

/* [Fit] */
// How far the lid reaches past the window on each side
cover_ov = 0.8;
// Hinge axis height above the top of the window
axis_up = 0.3;
// Height of the tape strip above the hinge
strip_h = 1.2;
// Print-in-place gap between moving parts (raise if it fuses)
g = 0.3;
// Pin-in-hole clearance
pin_clear = 0.3;
// Click strength: how far the bumps press into the lid (0 = no clicks)
det = 0.12;
// Crossbar below the lid joining the two legs (stiffens the frame)
bottom_bar = true;
// Crossbar height
bar_h = 1.2;
// Recess in the lid's back so it clears the window's raised rim
rim_pocket = 0.6;

/* [Shape] */
// Lid and frame thickness
t = 2;
// Hinge barrel radius
R = 2.2;
// Hinge pin radius
pin_r = 0.9;
// Frame leg width
et = 2.2;
// Length of each hinge knuckle on the lid (kept short so they stay clear of the window)
kl = 2;
// Preview only: lid angle (0 = closed, 180 = open)
open_angle = 0;
// Parts to render
part = "print"; // [print, preview, fit_test]

/* [Hidden] */
$fn = 48;
lw      = win_w + 2 * cover_ov;           // lid width
lid_len = axis_up + win_h + cover_ov;     // lid length below the axis
fw      = lw + 2 * (g + et);              // frame width
ys      = R + 0.4;                        // strip starts here (barrel clearance)
bar_y   = -lid_len - g - bar_h;            // crossbar bottom edge
leg_bot = bottom_bar ? bar_y : -(axis_up + win_h);  // legs run down to the bar, else to window bottom
rho     = (R + pin_r + pin_clear) / 2;    // click bump distance from axis
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
            // knuckles only at the ends, so nothing sits in front of the window when open
            for (x = [-lw / 2, lw / 2 - kl]) translate([x, 0, R]) rotate([0, 90, 0]) cylinder(r = R, h = kl);
            for (s = [-1, 1]) translate([s * lw / 2, 0, R]) rotate([0, s * 90, 0])
                cylinder(r = pin_r, h = g + et - 0.2);
            // finger grip on the bottom edge
            translate([-lw / 2 + 4, -lid_len + 0.4, t - 0.01])
                hull() { cube([lw - 8, 1.6, 0.01]); translate([0, 0.4, 0]) cube([lw - 8, 0.8, 1.2]); }
        }
        // clears the window's raised rim
        translate([-(win_w + 0.6) / 2, -axis_up - win_h - 0.3, -1])
            cube([win_w + 0.6, win_h + 0.6, 1 + rim_pocket]);
        // click dimples: closed and open (180°) positions
        if (det > 0) for (s = [-1, 1], y = [-rho, rho])
            translate([s * (lw / 2 + g), y, R]) sphere(rb + g);
    }
}

module frame() {
    difference() {
        union() {
            translate([-fw / 2, ys, 0]) linear_extrude(t) rrect(fw, strip_h, 1.5);
            if (bottom_bar)
                translate([-fw / 2, bar_y, 0]) linear_extrude(t) rrect(fw, bar_h, min(1.5, bar_h / 2 - 0.01));
            for (s = [-1, 1]) {
                x0 = s > 0 ? lw / 2 + g : -(lw / 2 + g + et);
                translate([x0, leg_bot + (bottom_bar ? 1 : 0), 0]) cube([et, ys + 1.5 - leg_bot, t]);
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

// Quick 0.6 mm template: hold it on the pod to check size before the real print
module fit_test() {
    difference() {
        linear_extrude(0.6) projection() frame();
        translate([-win_w / 2, -axis_up - win_h, -1])
            linear_extrude(3) rrect(win_w, win_h, 2);
    }
}

if (part == "fit_test") fit_test();
else frame();
if (part == "fit_test") {}
else if (part == "preview") color("orange")
    translate([0, 0, R]) rotate([-open_angle, 0, 0]) translate([0, 0, -R]) lid();
else lid();

echo(str("Frame ", fw, " x ", ys + strip_h - leg_bot, " mm; needs ", axis_up + ys + strip_h,
         " mm of flat face above the window and ", g + et + cover_ov, " mm beside it",
         bottom_bar ? str("; crossbar reaches ", -(leg_bot + axis_up + win_h), " mm below the window") : ""));
