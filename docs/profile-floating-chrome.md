# Profile floating chrome

Profile intentionally uses two copies of its top chrome:

- The **original** Profile app bar and tab row remain in normal document flow. They scroll with Diary or Statistics content.
- A separately cloned **floating** copy is fixed at the top of the app shell. It is created once from `.profile-top-app-bar`, so visual or control changes to the source should remain compatible with the clone.

This avoids changing the height, margin, or sticky positioning of the real chrome while a user is scrolling. Those changes can create layout-driven scroll events and produce a hide/show loop.

## State contract

`static/app.js` uses `PROFILE_CHROME_RETURN_BUFFER` (currently `200` pixels) to split Profile scrolling into three zones:

1. **At the top** (`scrollY <= 0`)
   - The floating copy must be hidden.
   - If it is visible, hide it immediately. This is safe because the original is exactly aligned beneath it.

2. **Original visible or in the return buffer**
   - The original is visible, or its bottom is within the buffer above the viewport.
   - Do not alter the floating copy, regardless of scroll direction. This stable handoff zone prevents flicker close to the original chrome.

3. **Original fully beyond the buffer**
   - Scrolling down: a visible floating copy slides upward out of view; an invisible one stays invisible.
   - Scrolling up: an invisible floating copy slides downward into view; a visible one stays visible.

The implementation must use the original bar’s `getBoundingClientRect().bottom` to determine zone two. Do not use only `scrollY`: the chrome height and safe-area inset are part of the geometry.

## Animation contract

- The floating chrome uses transform-only animation: `translateY(-100%)` to `translateY(0)` for entry, with the reverse for exit.
- Do **not** animate opacity. The required interaction is a slide, not a fade.
- Do **not** hide the element until its own `profile-floating-chrome-out` animation ends. Filter `animationend` by both `event.target` and `event.animationName`, since events from descendants can otherwise end the exit early.
- To make the complete entry visible, first remove `hidden`, then add the entry class in `requestAnimationFrame`. The base floating state must be parked above the viewport.
- The only intentionally instantaneous change is the exact-top handoff.

## Synchronization and accessibility

The clone contains working Back and tab controls, handled through the existing delegated events. Its duplicated `id` and `aria-controls` values are removed when cloned. `selectProfileTab(...)` updates every `[data-profile-tab]`, including the floating copy, so both tab rows always share selected state.

When editing Profile chrome, test all of these paths manually:

1. Scroll down from the top past the buffer, then reverse direction.
2. Reverse direction repeatedly inside the return buffer.
3. Reach exact top with the floating copy visible.
4. Change Diary/Statistics while the floating copy is visible; the tab switch must scroll to top and hide the copy.
5. Leave Profile and return through both the in-app Back button and browser history.
