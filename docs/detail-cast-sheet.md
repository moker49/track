# Detail Cast sheet interaction

The Cast sheet is currently an empty interaction prototype on tracked and untracked show/movie detail pages. Its purpose is to establish the exact sheet behavior before cast data is added.

## Visible layers

- The Cast pill (`[data-cast-sheet-open]`) is fixed at the bottom center above the bottom navigation when a show or movie detail is visible.
- The pill has no animation of its own. It stays rendered while the sheet is open, but the sheet has a higher z-index and covers it.
- The sheet (`[data-cast-sheet]`) is absent while closed. When opened, it is a top layer above both the pill and bottom navigation.
- A scrim sits beneath the sheet and blocks the page. `cast-sheet-open` locks document scrolling while the sheet is open or closing.

## State and history contract

`static/app.js` keeps the sheet state separate from the detail data:

- `castSheetOpen`: sheet is fully open or opening.
- `castSheetEntering`: applies the one-time entrance animation only when opened from the pill.
- `castSheetClosing`: applies the regular non-drag close animation.
- `castSheetSnapClosing`: records that a drag already animated the sheet offscreen, so it can be hidden without a second exit animation.
- `castSheetHistoryActive`: the open sheet has pushed one temporary browser-history entry.

Opening the pill pushes that history entry. Browser/system Back therefore closes the sheet first. Backdrop clicks and Escape call the same close path, which consumes that temporary entry before the detail page can be left.

## Handle gestures

The handle is drag-only; tapping it has no behavior. Pointer interaction is wired to the handle with `touch-action: none` and pointer capture:

1. A pointer-down only records a possible drag. It does not change the sheet state, so an accidental tap cannot interrupt the sheet.
2. Drag mode begins only after more than 6px of downward movement. The persistent open and entrance classes are removed, and an inline `translateY` tracks the pointer.
3. Releasing before 28% of the sheet height (capped at 112px) snaps back to `translateY(0)` with a transform transition.
4. Releasing past that threshold transitions from the current inline offset to the sheet height. Once it is visually offscreen, the temporary history entry is consumed and the sheet is hidden without another exit animation.

The important distinction is that `.is-open` is a stable state, not an animation trigger. Only `.is-entering` runs the full closed-to-open keyframe. This prevents a successful snap-open from replaying the full entrance animation after it has already settled.

## When adding content

Keep the content inside `[data-cast-sheet-content]`. Do not change the layer order, history behavior, drag thresholds, or the separation between stable/open, entering, closing, and drag-snap states without re-testing Back, Escape, backdrop dismissal, short drags, and threshold-crossing drags.
