---
name: ux-ui-developer
description: UX and UI developer for the Aandelen-analyzer in stock-analyzer/. Use this whenever you add or change a page, table, form, chart, menu or style in that app, and whenever someone asks about its layout, look and feel, spacing, navigation, or how it works on a phone, even if they don't say "UX" or "UI".
---

# UX/UI developer for the Aandelen-analyzer

The app is read on a desktop and on a phone, often to check one number quickly. A page has done its job when someone finds that number without zooming, sideways scrolling or reading an explanation first. Clean here means fewer competing things on screen, not less information: details stay one tap away.

## How the front end is built

- **No build step.** Jinja templates in `app/web/templates/`, one stylesheet in `app/web/static/style.css`, plain JavaScript in `app/web/static/`. Don't add a framework, a CDN or web fonts, because the app must run offline on a Raspberry Pi.
- **All text comes from `app/i18n/nl.py`.** Write it in plain Dutch and don't put text in templates or JavaScript.
- **`app.js` handles shared behaviour:** the menu and the phone view of tables. Pages must still be usable without JavaScript, even if less tidy.
- **Use the design tokens.** Colours, spacing and radii are CSS variables at the top of `style.css`, in light and dark. Don't write a raw colour or a one-off size in a rule, because dark mode and consistency both depend on it.

## Layout rules

- **Design for 360 px first,** then let the layout grow. Prefer layouts that adapt by themselves (`auto-fit`, `minmax(min(…, 100%), 1fr)`, `clamp()`) over extra breakpoints. The breakpoints are the phone one at 720 px and the menu one at 1240 px, plus one at 600 px for the chart legend.
- **The page never scrolls sideways.** Long text wraps, and only a table with many number columns may scroll inside its own box.
- **One main action per section.** Secondary actions look quieter. On a phone, buttons and form fields take the full width.
- **Touch targets are at least 44 px high on a phone,** and inputs use 16 px text there, otherwise iOS zooms in when a field gets focus.
- **Keep hierarchy simple:** one `h1` per page, an `h2` per card, and muted text for anything secondary. Don't add a card inside a card or a border where spacing already separates things.

## Tables

Tables with four or more columns become compact blocks on a phone without extra work: `app.js` copies each header to its cells as a label. Three things to do when adding one:

- Put the name or date in the first column, because it becomes the heading of the block.
- Mark long text cells with `small`, so they take the full width.
- Add `phone-hide` to columns that the detail page already shows.

Use the `matrix` class when comparing the same numbers across many columns, such as returns per period. It keeps the table as a table, scrolls inside its box and pins the first column.

## Charts

Charts in `charts.js` are drawn at the real width of their box and redrawn when it changes, so text stays a readable size. Never scale a fixed-size SVG down to fit a phone. Below 560 px there is no room for labels beside the plot, so values move above the chart or onto the lines. Follow the `dataviz` skill for colours and marks.

## Checking your work

Tests can't see layout, so look at it. Use a test copy with made-up data, never a real portfolio, and check every page you touched at 360 px and at desktop width, in light and dark mode:

1. `document.documentElement.scrollWidth` is not larger than the window width.
2. No text is cut off or overlapping, also with long product names and large amounts.
3. Empty states, error messages and the login page look right too.
4. The menu opens, closes and works with a keyboard.

Screenshots of the browser pane can fail when it's hidden. If so, check the measurements with JavaScript and say that you didn't see the result yourself.
