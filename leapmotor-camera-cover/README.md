# Leapmotor B05 driver-camera privacy cover

A flip-up lid for the driver-monitoring camera on the left A-pillar. A rectangular frame is taped to the camera pod. The lid hangs over the lens when closed and folds up 180° onto the frame when open, and it clicks into place in both positions.

![preview](preview.png)

It prints **as one piece with the hinge already assembled** (print-in-place). It needs no supports and no assembly.

## Why a flip lid and not a slider

The camera pod is small. Its window is about 25 × 14.5 mm, with only about 5.5 mm of face above it, 5–6 mm on each side and about 3 mm below. A sliding shutter would stick far out past the pod. A lid hinged on the top edge fits.

## Size (defaults, measured with a tape measure)

| | |
|---|---|
| Frame | 32.9 × 23.7 mm, 5 mm thick at the hinge, 2 mm elsewhere |
| Lid | covers 27.4 × 16.2 mm (window + 1.2 mm overlap) |
| Crossbar | 1.5 mm bar under the lid joining both legs, ending ~3.3 mm below the window. Set `bottom_bar = false` to drop it |
| Needs | 5.9 mm of face above the window, ~4 mm on each side, ~3.3 mm below |

The first test print used sizes estimated from photos and came out about 25% too big. These defaults come from a tape measure held on the pod.

## Fit test first

`fit-test.stl` is a 0.6 mm flat outline of the frame with the window cut out. It prints in a few minutes. Hold it on the pod: the window hole should sit just around the dark window, and the outline should stay on the pod face. If it's off, change `win_w` / `win_h` (or `strip_h` for the top) and print the test again.

## Print (Bambu Lab A1)

- **Black PETG** (or ASA). PLA softens behind a windscreen. Use an opaque dark colour, because the camera uses infrared light.
- 0.2 mm layers, 3 walls, no supports, printed flat as exported.
- After printing, bend the lid gently to break the hinge free.
- If the hinge fuses, raise `g` (0.35 → 0.4). If the click is too stiff or too weak, change `det` (0 = no click).

## Fit

1. Peel off the clear protective film tab on the lens if it's still there.
2. Clean the pod face with isopropyl alcohol.
3. Stick the frame on with **thin foam VHB tape** (~0.8–1 mm) on the strip and both legs (the crossbar may not touch the pod, which is fine). Put the hinge just above the window's top edge.

To change sizes, open `camera-cover.scad` in OpenSCAD (Window → Customizer) or in MakerWorld's Parametric Model Maker. Set `part = preview` and `open_angle` to see it move.

> This is the driver attention/fatigue camera. With the lid closed, the car will probably show a warning or switch off driver-monitoring features.
