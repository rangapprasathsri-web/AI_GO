# Theme & Design Gap Report: Editorial SaaS Transformation

Audit completed on: 2026-10-10
Baseline test suite: **124 passed, 0 failed** in 5.39s.

This document audits the existing frontend against the editorial SaaS design specification (sections 1 through 10) before making any modifications.

---

## 1. Audit Summary Table

| Section | Requirement | Current Status | Relevant Files | Structural / Design Changes Needed |
| :--- | :--- | :--- | :--- | :--- |
| **1. Direction & Brand** | Minimal editorial SaaS style (white canvas, fine gray borders, lavender surfaces, purple accent) | **Missing** | `frontend/index.html` | Overhaul dark neon gradient theme (`#090d16`) to clean, calm, high-contrast light editorial theme. |
| | Original brand mark (rounded purple tile with 3 ascending bars) | **Missing** | `frontend/index.html` | Replace glowing `⚡` badge with SVG/CSS rounded tile and 3 tier bars. |
| | Product name from config (`app_name`) | **Partly done** | `backend/domains/image_resource_optimizer.yaml`, `backend/engine/config.py`, `frontend/index.html` | Add `app_name: "EffortMatch"` to domain config, expose via `/config`, and bind to UI dynamically. |
| **2. Design Tokens** | CSS variables: `--ink`, `--canvas`, `--surface`, `--border`, `--muted`, `--purple-500`, `--purple-600`, `--lavender`, `--green` | **Missing** | `frontend/index.html`, `frontend/tokens.css` | Define CSS root variables and Tailwind theme integration. |
| | Contrast enhancements: `--purple-700`, `--muted-strong`, `--green-text` | **Missing** | `frontend/tokens.css`, `backend/tests/test_contrast.py` | Add accessible variants meeting WCAG AA (>= 4.5:1 normal text, >= 3.0:1 UI/large text). |
| | Automated contrast test script | **Missing** | `backend/tests/test_contrast.py` | Create automated test calculating relative luminance and contrast ratios for all pairs in use. |
| **3. Typography** | Geist font self-hosted (400, 500, 600, 700) with fallback and `font-display: swap` | **Missing** | `frontend/fonts/`, `frontend/index.html` | Download Geist woff2 files locally to avoid CDN calls; remove Google Fonts runtime link. |
| | Editorial hierarchy: large H1, tight leading, negative tracking, purple highlight, uppercase tracking labels | **Missing** | `frontend/index.html` | Reorganize headings with single H1, semantic H2/H3, uppercase tracking labels for card metadata. |
| **4. Layout & Flow** | Sticky semi-transparent nav with brand left, links centre, CTA right, mobile toggle | **Missing** | `frontend/index.html` | Replace current dark top bar with clean sticky nav bar with blur and mobile drawer. |
| | Centred hero with eyebrow, two-line headline ("Right effort." / "Every image."), supporting sentence, dual CTA | **Missing** | `frontend/index.html` | Add editorial hero section above the tool. |
| | Product proof preview shell with live/simulated request and resource cards | **Missing** | `frontend/index.html` | Add preview shell showcasing live engine output with honesty badges. |
| | Asymmetric two-column problem statement section | **Missing** | `frontend/index.html` | Add problem statement section highlighting invisible AI compute costs. |
| | Tool section (prompt, purpose, tier selector, recommendation, comparison centerpiece) | **Partly done** | `frontend/index.html` | Retain all 100% functional controls, restyle into compact white cards with fine borders. |
| | Four-step "How it works" row | **Missing** | `frontend/index.html` | Add 4-step row: Describe image, Match effort, Generate, See savings. |
| | History & cumulative savings running total | **Partly done** | `frontend/index.html` | Convert raw table to clean ruled list with right-aligned metrics and prominent running total banner. |
| | Closing CTA and minimal footer | **Missing** | `frontend/index.html` | Add "Your next image starts here" closing section and copyright/links footer. |
| **5. Components** | Pill-shaped buttons (`--purple-600`, upward-right arrow `↗`, subtle hover lift) | **Missing** | `frontend/index.html` | Restyle buttons with pill radii, arrow icons, and accessible focus states. |
| | White cards (10-18px radius, fine border, light shadow, compact metadata labels) | **Missing** | `frontend/index.html` | Replace translucent dark glass cards with clean white editorial cards. |
| | Pale lavender metadata chips (`--lavender` bg, `--purple-700` text) | **Missing** | `frontend/index.html` | Style purpose and tier badges with lavender chips and high contrast text. |
| | Segmented quality tier selector (Economy, Standard, Maximum) with text "Recommended" mark | **Partly done** | `frontend/index.html` | Replace bulky cards with accessible segmented control showing params and text badges. |
| | Resource progress bar (units used vs Maximum) | **Missing** | `frontend/index.html` | Add narrow rounded purple progress bar with adjacent numerical labels. |
| | Explicit text origin badges (Simulated, Estimated, Provider-reported, Measured) | **Partly done** | `frontend/index.html` | Ensure all metrics display text badges with correct color pairings. |
| | Image preview frame with DEMO PLACEHOLDER label and descriptive alt text | **Done** | `frontend/index.html` | Retain existing watermark label and alt attributes; refine container styling. |
| | Accessible Modal dialog for below-floor override and budget blocking | **Missing** | `frontend/index.html` | Replace inline warning box with accessible modal dialog (backdrop click, Esc key, focus trap). |
| | Forms with visible purple focus rings and inline validation | **Partly done** | `frontend/index.html` | Add `--purple-600` focus outline rings (`2px solid`) and clear field labels. |
| **6. Voice & Copy** | Plain language, no hype, concise, warm, practical | **Partly done** | `frontend/index.html` | Update all microcopy and section headlines to editorial voice. |
| **7. Motion** | Subtle entrance animations (<16px rise, 180-700ms), button lift, `prefers-reduced-motion` | **Partly done** | `frontend/index.html` | Standardize transitions and keep full support for reduced motion. |
| **8. Responsive** | Fluid layout across 1280px (desktop), 820px (tablet), 390px (mobile, no horizontal scroll, >=44px touch targets) | **Partly done** | `frontend/index.html` | Implement responsive breakpoints and verify with headless browser screenshots. |
| **9. Accessibility** | WCAG AA contrast, visible focus, logical tab order, keyboard operable, screen reader labels | **Partly done** | `frontend/index.html`, `backend/tests/test_contrast.py` | Add automated contrast test, verify interactive elements with visible focus rings. |
| **10. Honesty** | Prominent labels ("simulated estimate, not measured energy", "estimated savings vs maximum tier (not run)", demo placeholder marks) | **Done** | `frontend/index.html` | Preserve all required honesty labels without softening or shrinking. |

---

## 2. Components Requiring Structural Changes
1. **Top Header & Navigation**:
   - Current: Simple header with tabs bar (`generatorTab`, `historyTab`, `configTab`).
   - Change: Sticky editorial navigation with brand mark, smooth-scroll section anchors (`#generate`, `#how-it-works`, `#history`, `#admin-config`), running total pill, and mobile menu toggle.
2. **Quality Tier Selector**:
   - Current: 3 separate large cards in a grid.
   - Change: Segmented control with high contrast, accessible buttons/radios, explicit "Recommended" text badge, and compact parameter specs.
3. **Override & Budget Flow**:
   - Current: Inline warning box requiring checkbox click.
   - Change: Dedicated modal dialog with backdrop, Escape key handling, and focus trapping that appears when selecting below-floor tiers or triggering budget errors.
4. **Editorial Content Sections**:
   - Addition of Hero section with proof cards, Problem section, 4-step workflow, and Closing CTA.
5. **Centerpiece Comparison Panel**:
   - Integrated progress bar showing units used relative to Maximum (118.0 units), accompanied by precise numerical labels and origin chips.
