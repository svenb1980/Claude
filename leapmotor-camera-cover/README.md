# Leapmotor B05 interior camera privacy cover

A sliding shutter cover. The **base** sticks around the camera with double-sided tape, and the **shutter** slides in dovetail rails. It clicks into place when open and when closed.

![preview](preview.png)

The B05 camera dimensions aren't published, so the model is parametric. The STLs in this folder use the default 22 × 12 mm window. Measure your own camera before you print.

## 1. Measure (calipers or a ruler)

| Value | What to measure |
|---|---|
| `win_w` | Width of the dark camera window along the direction you want it to slide, **including the IR LEDs** next to the lens. Add about 1 mm. |
| `win_h` | Height of that dark window. Add about 1 mm. |

Also check that the trim around the camera has a fairly flat area of about **(2 × win_w + 16) × (win_h + 15) mm**. The cover slides sideways, so it needs room beside the camera.

## 2. Make your STL

- **Option A (no software):** upload `camera-cover.scad` to MakerWorld's *Parametric Model Maker* (OpenSCAD customizer). Enter your values and export.
- **Option B:** open `camera-cover.scad` in [OpenSCAD](https://openscad.org). Use *Window → Customizer*, set the values, then *Render (F6)* and *Export STL*.

Set `part` to `assembly_closed` / `assembly_open` to preview the cover put together.

## 3. Print (Bambu Lab A1)

- **Material:** PETG or ASA. PLA warps in a car parked in the sun. Use **black / opaque**, because the camera works with infrared light and some light colours let IR through.
- Use 0.2 mm layers, 3 walls and 100% infill (the parts are tiny). No supports. Print both parts flat, as exported.
- **Print a test first.** If the shutter is too tight, raise `gap` (0.25 → 0.3). If it's loose, lower it. For a stronger click, raise `detent_h`. To remove the click, set it to 0.

## 4. Fit

1. Slide the shutter in from the open end of the rails.
2. Clean the trim with isopropyl alcohol.
3. Stick the base on with thin 3M VHB / automotive double-sided tape around the window. Thin foam tape can handle a slightly curved surface.

> Note: this camera is the driver attention/fatigue monitor. When it's covered, the car may show a warning or turn off driver-monitoring features. Open the shutter if you need them.
