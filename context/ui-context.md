# UI Context

## Theme

**Current: dark only, glassmorphic.** Near-black slate background, translucent blurred
cards, blue accent, Bootstrap 5 with a custom layer on top. Sidebar navigation on desktop,
collapsing to a top bar with an overlay drawer on mobile.

> **Scheduled for replacement in Stage 3.1.** This theme is documented as it stands, not as
> it should be. Dark glass at 70% opacity with a backdrop blur is the lowest-contrast
> combination available, and this app is used on a phone in warehouse doorways and open
> markets in full daylight. It also costs real GPU time on the budget Android hardware
> this market runs. Stage 3.1 rebuilds the palette light-first with dark by toggle and
> `prefers-color-scheme`, and drops the blur.
>
> Three consecutive commits early in the project were corrections forcing text back to a
> readable colour. That is the interface reporting that the effect fights legibility.

## Colors

Defined as CSS custom properties in `static/css/style.css`. Components use the tokens.

| Role | CSS Variable | Value |
| --- | --- | --- |
| Page background | `--bg-dark` | `#0f172a` |
| Card surface | `--bg-card` | `rgba(30, 41, 59, 0.7)` |
| Primary text | `--text-primary` | `#f1f5f9` |
| Muted text | `--text-secondary` | `#94a3b8` |
| Accent | `--accent-primary` | `#3b82f6` |
| Border | `--border-color` | `rgba(148, 163, 184, 0.2)` |

Semantic state uses Bootstrap's contextual classes (`text-success`, `bg-danger`,
`badge bg-warning`) rather than custom tokens. Stage 3.1 should give these real tokens —
semantic colour is separate from the accent and should not depend on Bootstrap defaults.

Currency is always rendered with the cedi sign and two decimals: `₵{{ '%.2f'|format(x) }}`.

## Typography

System font stack via Bootstrap. No webfont is loaded, which is deliberate on metered
mobile data. Monospace (`font-monospace`) marks SKUs, references and permission codes —
anything the user might read character by character.

## Border Radius

Bootstrap defaults (`rounded`, `rounded-3`). Cards use `0.75rem` via `.glass-card`.

## Component Library

Bootstrap 5.3.0 and Bootstrap Icons 1.11.3, **vendored under `static/vendor/`** with
Chart.js 4.4.1, plus `static/css/style.css`. Nothing loads from another origin — a service
worker cannot reliably cache cross-origin responses, and `tests/test_assets.py` fails if a
CDN link reappears.

Searchable dropdowns use `static/js/combobox.js` (with `static/css/combobox.css`), applied
by putting `data-combobox` on a `<select>`. The native `<select>` stays in the DOM and
still posts its value, so the page works with JavaScript off.

**Known debt, to be resolved in Stage 3.2 / 3.3:**
- 29 `!important` declarations, mostly overriding Bootstrap's white table and card
  defaults. Target zero — either configure Bootstrap through its variables or replace it
  with a small hand-written layer.
- Three mobile breakpoints (991px, 767px, 400px) maintain a second card-shaped copy of
  every table layout.

## Layout Patterns

- **Shell** — fixed left sidebar plus `.main-content`; below 991px the sidebar becomes an
  off-canvas drawer behind `.sidebar-overlay`, toggled from `.mobile-header`.
- **Page header** — `.page-header` with an `<h2>` and `.page-header-actions` on the right.
- **Cards** — `.glass-card` for every panel. `.card-toolbar` gives a heading plus actions.
- **Tables** — `.table-cards` reflows rows into stacked cards on mobile using
  `data-label` attributes on every `<td>`. **Any new table must set `data-label`**, or it
  becomes unreadable on a phone.
- **Stat tiles** — `.stat-icon` with `.stat-primary` / `.stat-warning` / `.stat-success` /
  `.stat-danger`, wrapped in a `.glass-card`.
- **Empty states** — centred icon, heading, one explanatory sentence, and a button to the
  action that resolves it. Every list has one.
- **Navigation** — grouped with `.nav-section-label`; visibility driven by
  `current_user.can()` and `has_feature()`, never by role name.
- **Print** — invoices and statements hide everything outside the printable region via
  `visibility: hidden` on `body *`.

## Icons

Bootstrap Icons 1.11 (`bi bi-*`). Inline in buttons with `me-1`; standalone at `fs-1` in
empty states.
