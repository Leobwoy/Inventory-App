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

**Two Bootstrap behaviours that have already cost time:**

- `.d-flex` carries `display: flex !important`, which **beats the browser's `[hidden]`
  rule**. An element with `hidden` and `d-flex` stays visible forever. `style.css` now sets
  `[hidden] { display: none !important; }`; without it the offline banner and the discount
  summary showed permanently (F-42).
- Bootstrap 5.3 colours table cells from `--bs-table-color` **set on the cells**, so a
  `color` on `.table` never reaches them. Restyling a table means setting the Bootstrap
  variables, not the property — the console's text was invisible until this was understood.

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
- **Gate pages** — a signed-in page that is a gate rather than a page of the app (today,
  the change-password screen) passes `standalone=True` and keeps `{% block auth_content %}`.
  It gets the centred `.auth-shell` layout with no sidebar, because every link in that
  sidebar would bounce the user straight back. `.auth-shell` also reserves the 60px the
  fixed `.mobile-header` occupies — without it a card taller than the viewport centres
  itself and pushes its own heading behind that bar.
- **Print** — invoices and statements hide everything outside the printable region via
  `visibility: hidden` on `body *`.

## Icons

Bootstrap Icons 1.11 (`bi bi-*`). Inline in buttons with `me-1`; standalone at `fs-1` in
empty states.

## Choosing a product

Products are chosen in a **dialog**, never in a table cell. `templates/_partials/product_picker.html`
plus `static/js/picker.js`, opened by a `.picker-button` carrying
`data-picker-for="<selector>"`. One dialog per page serves every line on it.

The reason is arithmetic. On a 1440px laptop the sale form's product cell was 130px and the
search box inside it 98px, while the longest product name needed 169. Five columns wanted
about a 1500px window; no width tuning fixes that.

Rules for any page that adopts it:

- The `<select>` stays in the DOM, keeps its name, and stays the source of truth. The picker
  writes to it and dispatches a bubbling `change`, so existing listeners keep working.
- The select is hidden by `picker.js` adding `line-enhanced`, **never by the server**. With
  no script the select is the control and the page still works.
- Each line wrapper carries `data-line`; the select carries `data-picker-select`.
- Whatever is worth knowing beside a product - its price on a sale, its last cost on a
  purchase order - goes on the `<option>` as `data-meta`. The picker itself knows nothing
  about products.

Lines that used to be table rows with three inputs in them are **cards** instead: purchase
order lines and goods receipt lines both use this shape, with `.field-grid` inside. A table
row cannot hold a product name, a quantity, a unit dropdown, a cost and a total at any screen
width a shop actually owns.

This is the app's **first and only Bootstrap modal**. Bootstrap's JS bundle was already
loaded and precached on every page, so it cost nothing new. `.modal-content` is solid
(`--bg-card-solid`), not frosted - a dialog is the one surface with a whole page behind it.
