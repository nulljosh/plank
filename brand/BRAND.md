# Plank brand kit and design system

One plank of wood, seen from the corner, rings on the cut end.

## The mark
A cream plank on an ink tile. No text, no outline, no gradient.

- `../site/icon.svg` is the source of truth: the README, the landing nav and the favicon all use it.
- `icon-1024.png` is the full square at 1024, no alpha. Round it with the page, not in the file.
- `mark.svg` is the plank alone in `currentColor` for your own background.
- Clear space equal to the plank's end grain. Smallest size 16 px.

## Colour
| Role | Light | Dark |
|---|---|---|
| Accent, links, focus | `#a33d18` rust | `#ff8a5c` |
| Band, frame | `#8f3517`, `#b3461f` | `#6e2810`, `#b3461f` |
| Icon | `#f3efe4` plank on `#1c1a17` ink | same |
| Text | `#1a1a1a` | `#f2f2f0` |
| Background | `#fafafa` | `#111110` |
| Surface | `#f0f0f0` | `#1c1b19` |

Plank wears paper and ink. Rust is the one colour it owns, for links, the band and focus. Never purple or teal.

## Type
System sans only, nothing to download. Code is SF Mono, then Menlo.

## Space and shape
- Space on the 8 point grid. Controls are 48 point capsules. Focus is a ring at 30 percent accent.
- Motion is 0.2 s ease and honours reduced motion.
