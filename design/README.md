# Design system

`tokens.css` is **generated** — run `python design/build_tokens.py` to rebuild it.
It is gitignored because it embeds the Bootstrap Icons woff2 as a data URI
(~185 KB) purely so the mockups render standalone in Claude Design, which cannot
reach the app's `/static/vendor` tree. The app itself keeps using the vendored
font file and never loads this.

- `build_tokens.py` — generator. Edit the design system here, not in tokens.css.
- `icons.json` — codepoints resolved from the app's own bootstrap-icons.min.css,
  so the mockups use the real icons rather than substitutes.
- `directions/` — the three directions explored before choosing. Kept as the
  record of what was rejected and why.
- `pages/` — page mockups for the chosen direction.

**Chosen direction: B on desktop, C on phone.** Frosted glass and density where
there is a big screen and no glare; solid surfaces, no blur, thicker borders and
bottom-tab navigation below 768px, because the app is used one-handed in
sunlight. See the plan for the full reasoning.
