# Minimal Editorial SaaS Design System & Theme Specification

**Product**: EffortMatch — Adaptive AI Image Resource Optimizer  
**Style Direction**: Minimal Editorial SaaS  
**Characteristics**: Large high-contrast headlines, generous whitespace, fine 1px borders, soft lavender surfaces, single expressive purple accent, compact evidence-dense cards, calm and precise copy.

---

## 1. Design Tokens & Palette

All styling is managed through CSS custom properties in `frontend/tokens.css`. Every foreground/background pair has been algorithmically verified against **WCAG 2.1 AA** standards (script verified in `backend/tests/test_contrast.py`).

| CSS Variable | Hex Code | Purpose | Verified Contrast Ratio | WCAG AA Status |
| :--- | :--- | :--- | :--- | :--- |
| `--canvas` | `#FFFFFF` | Page canvas, cards, sticky navigation | 18.86:1 vs `--ink` | **PASS** (>= 4.5:1) |
| `--surface` | `#F7F7FA` | Preview shells, secondary containers, inactive cards | 17.64:1 vs `--ink` | **PASS** (>= 4.5:1) |
| `--border` | `#E8E8ED` | Fine dividers, input outlines, card borders | N/A (Structural) | **PASS** |
| `--lavender` | `#F2EDFF` | Chips, active selected card backgrounds | 8.02:1 vs `--purple-700` | **PASS** (>= 4.5:1) |
| `--ink` | `#111113` | Headlines, primary text, prominent metrics | 18.86:1 vs Canvas | **PASS** (>= 4.5:1) |
| `--muted-strong` | `#55555C` | Supporting body text, explanations, labels | 7.39:1 vs Canvas | **PASS** (>= 4.5:1) |
| `--muted` | `#6B6B72` | Secondary captions, sub-metrics | 5.02:1 vs Canvas | **PASS** (>= 4.5:1) |
| `--purple-600` | `#6E34E2` | Primary button fill, text links, active highlights | 6.46:1 vs White text | **PASS** (>= 4.5:1) |
| `--purple-700` | `#5221BA` | Metadata chip text, deciding factor labels | 8.02:1 on Lavender | **PASS** (>= 4.5:1) |
| `--purple-500` | `#9B73F5` | Brand mark fills, progress fills, large word highlight | 3.41:1 (Large text / UI) | **PASS** (>= 3.0:1) |
| `--green` | `#6AAF24` | Status indicator dots (always paired with text) | Graphical dot | **PASS** |
| `--green-text` | `#286208` | Savings percentage and avoided compute text | 7.39:1 vs Canvas | **PASS** (>= 4.5:1) |
| `--amber-text` | `#8A4B00` | Warning labels, demo placeholder notice | 6.80:1 vs Canvas | **PASS** (>= 4.5:1) |
| `--rose-text` | `#B31B38` | Hard budget blocking, error messages | 6.71:1 vs Canvas | **PASS** (>= 4.5:1) |

---

## 2. Typography

- **Primary Font**: **Geist Sans** (`Geist`), 100% self-hosted under `frontend/fonts/` (`.woff2` format).
  - No external runtime CDN requests (Google Fonts CDN calls eliminated).
  - Loaded with `font-display: swap`.
  - Fallback stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`.
- **Monospace Font**: System monospace (`ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace`) for compute units, baseline parameters, and JSON editors.
- **Hierarchy**:
  - `h1`: 56px (desktop) / 36px (mobile), weight 700, tight line height (1.08), negative tracking (`-0.035em`). Exactly one `<h1>` per page.
  - Purple Headline Highlight: "Right effort." in black, "Every image." in `--purple-600`.
  - Section Titles (`h2`): 28px–34px, weight 700, letter-spacing `-0.025em`.
  - Metadata Labels: 11px uppercase with tracked letter spacing (`0.06em–0.08em`).

---

## 3. Brand & Components

1. **Original Brand Mark**:
   - A rounded purple tile (`--purple-600`, 9px radius) containing 3 ascending white vertical bars symbolizing adaptive tiers: Economy (7px), Standard (13px), Maximum (19px).
   - No reference brand marks, folded letters, or copyrighted logos are used.
2. **Buttons**:
   - Pill-shaped (`border-radius: 9999px`), `--purple-600` background with white text, compact vertical padding, upward-right arrow icon (`↗`).
   - Micro-interaction: 1.5px hover lift with soft purple shadow (`box-shadow: 0 4px 12px rgba(110, 52, 226, 0.28)`).
3. **Cards & Proof Shell**:
   - White backgrounds (`--canvas`), 12px–16px border-radius, fine 1px border (`--border`), subtle shadow.
   - Proof Shell in `--surface` with two live evidence cards showcasing engine transparency.
4. **Segmented Tier Selector**:
   - 3 interactive cards (Economy, Standard, Maximum) with explicit text indicator (`★ RECOMMENDED`) on the recommended tier (not relying on color alone).
   - Keyboard accessible (`role="radio"`, `aria-checked`, `tabindex="0"`).
5. **Progress Bar**:
   - Narrow rounded bar (`9px` height) with `--purple-600` fill showing units used relative to Maximum (118.0 units), with an adjacent numerical percentage indicator.
6. **Honesty Origin Badges**:
   - Every metric displays a text badge:
     - `SIMULATED`: Lavender chip with `--purple-700` text.
     - `ESTIMATED`: Outlined gray chip with `--muted-strong` text.
     - `PROVIDER-REPORTED`: Light purple chip.
     - `MEASURED`: Green dot + "Measured" text.
7. **Accessible Modal Dialog**:
   - Used for below-floor override confirmation and hard budget blocking.
   - Accessible: `role="dialog"`, `aria-modal="true"`, `aria-labelledby="modalTitle"`.
   - Closes via Cancel button, backdrop click, and `Escape` key; traps and restores focus.

---

## 4. How to Change the Theme

The entire visual theme can be altered from a single place without modifying component HTML or Python code:

1. **Change CSS Variables** in `frontend/tokens.css`:
   ```css
   :root {
     --canvas: #FFFFFF;
     --surface: #F7F7FA;
     --border: #E8E8ED;
     --ink: #111113;
     --purple-600: #6E34E2; /* Change accent color */
     /* ... */
   }
   ```
2. **Verify Contrast**:
   Run the automated verification suite to guarantee WCAG AA compliance remains intact:
   ```bash
   pytest backend/tests/test_contrast.py
   ```
3. **Hot-Reload Dynamic Config**:
   Update `app_name` or tier parameters via `PUT /config` in the Admin Studio or in `backend/domains/image_resource_optimizer.yaml`.

---

## 5. Responsive Verification & Screenshots

Headless Firefox screenshots were captured at all target resolutions and saved to `docs/screenshots/`:

| Resolution | Device Class | Screenshot Path | Verification Details |
| :--- | :--- | :--- | :--- |
| **1280px** | Desktop | `docs/screenshots/desktop_1280.png` | 2-column problem layout, side-by-side proof cards, 4-step row, complete comparison panel |
| **820px** | Tablet | `docs/screenshots/tablet_820.png` | 2-column cards, adjusted padding, fluid typography |
| **390px** | Mobile | `docs/screenshots/mobile_390.png` | Single-column stacked cards, collapsed mobile nav, touch targets >= 44px, no horizontal scroll |
| **1280px** | Modal Dialog | `docs/screenshots/modal_1280.png` | Below-floor confirmation modal with blurred backdrop and accessible focus trap |
