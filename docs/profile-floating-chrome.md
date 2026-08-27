# Profile scroll chrome

Profile uses one real app bar and tab row. It remains in normal document flow; there is no cloned chrome or animation.

## Implementation contract

On each upward Profile scroll, `static/app.js` reads the real `.profile-top-app-bar` position. There is one rule:

```js
if (chrome.getBoundingClientRect().bottom < 0) {
  chrome.style.transform = "translateY(...)"; // make bottom exactly 0
}
```

The transform is accumulated only while scrolling up. When upward scrolling brings the transformed original chrome to `top >= 0`, a temporary visual clone is placed at `top: 0` and the original is reset behind it. The clone receives no input.

## Resulting behavior

- At the top, the real Profile chrome is visible in its natural position.
- The chrome always retains its normal layout space.
- While scrolling up, if its rendered bottom is above the viewport, it is moved only enough to restore that bottom to the top edge (`0`). It remains fully offscreen.
- Once upward scrolling brings the original top to `0`, a non-interactive clone covers the reset original at the top edge. The original itself remains visible throughout.
- On the next downward scroll, the clone is removed and the original is positioned at `top: 0`; without a clone, downward scrolling has no special behavior.

Do not animate the handoff or change layout with margins. The clone is only a visual cover for the one reset transition; the original remains the interactive, in-flow chrome.

Profile tab changes intentionally reset `window.scrollTo({ top: 0, behavior: "auto" })`, placing the original chrome back in its natural top position.
