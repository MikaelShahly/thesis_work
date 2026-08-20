# Design System

## Overview

This design system produces sober, editorial technical-report layouts with strong typographic restraint. A report opens on a large typographic title over a white canvas, then uses figures, dark technical panels, and generous empty space to make complex material feel controlled and authoritative rather than busy. Detail sections can invert the tone into deep green-black or dark navy bands, while results tables, run logs, and reference matter move toward dense, rule-separated clarity: thin rules, tight lists, and pale technical backgrounds.

What makes the system distinctive is the mix of austere black-and-white layout with bursts of tactile imagery — the figures, contour plots, and visualizations that carry the actual evidence. The page avoids decorative chrome; color arrives through figures, abstract renders, restrained coral section markers, links, and dark technical environments. Cards are rounded but not cute. Type is large, tight, and almost monospaced in spirit, creating a research-lab cadence across every surface.

**Key Characteristics:**

- Monumental display headlines with very tight line height and negative tracking.
- White editorial canvases interrupted by deep green, dark navy, and image-led section bands.
- Rounded media cards and content cards, usually 8px to 22px.
- Pill primary buttons in near-black or white, with most secondary actions rendered as underlined text links.
- Restrained, monochrome supporting marks with very wide vertical spacing.
- Dark technical panels using small status chips, integration badges, and console-style content.
- Reference matter — results tables, run logs, nomenclature, references — as long rule-separated lists with restrained category markers.

## Colors

### Brand & Accent

- **Black** (`#000000`): Highest-contrast text and the global anchor color.
- **Near-Black Primary** (`#17171c`): Primary buttons, dark footer, and deep UI cards.
- **Deep Green** (`#003c33`): Hero bands and highlighted dark capability sections.
- **Dark Navy** (`#071829`): Alternative dark section band for contrast or emphasis.
- **Action Blue** (`#1863dc`): Hyperlinks and cross-references, used sparingly.
- **Coral** (`#ff7759`): Section and category markers, taxonomy outlines, and warm accent details.
- **Soft Coral** (`#ffad9b`): Pale chip borders and segmented label details.

### Surface & Background

- **Canvas White** (`#ffffff`): Dominant page background and form/card surface.
- **Soft Stone** (`#eeece7`): Content cards, placeholders, and warm neutral surface blocks.
- **Pale Green Wash** (`#edfce9`): Section backdrop behind stacked dark capability panels.
- **Pale Blue Wash** (`#f1f5ff`): Callout surface behind abstract imagery.
- **Card Border** (`#f2f2f2`): Softest card containment line.

### Text & Rules

- **Ink** (`#212121`): Default body text and most link text on light backgrounds.
- **Muted Slate** (`#93939f`): Footer links, dates, metadata, and de-emphasized labels.
- **Slate** (`#75758a`): Separators and tertiary text.
- **Hairline** (`#d9d9dd`): Standard list rules and section dividers.
- **Border Light** (`#e5e7eb`): Secondary divider and utility rule.

### Semantic

- **Focus Blue** (`#4c6ee6`): Keyboard focus and ring color.
- **Form Focus Violet** (`#9b60aa`): Focus border for text inputs.
- **Error Red** (`#b30000`): Ring/shadow color associated with validation-like states.

### Status

Used to flag the quality of a result or run (e.g. convergence, residuals, mesh quality, agreement with reference). Use the strong tone for text, icons, and chip fills; pair it with the matching soft tone as a background tint for the same status.

- **Good** (`#1f7a4d`) on **Good Soft** (`#e6f4ec`): Acceptable / converged / within tolerance.
- **Marginal** (`#b45309`) on **Marginal Soft** (`#fbeede`): Borderline / needs attention / partially met.
- **Bad** (`#b91c1c`) on **Bad Soft** (`#f9e6e6`): Failed / diverged / out of tolerance.

### Gradient System

Gradients are not used as a generic UI fill. Gradients and rich color fields are media-led: abstract renders, figures, and visualization imagery (contour plots, streamlines, fields, and similar). Keep UI surfaces flat; reserve gradient richness for large media panels and image bands.

## Typography

### Font Family

- **Display**: `Space Grotesk`, falling back to `Inter`, `ui-sans-serif`, and `system-ui`.
- **Body/UI**: `Inter`, falling back to `Arial`, `ui-sans-serif`, and `system-ui`.
- **Technical labels (mono)**: `Arial`, falling back to `ui-sans-serif`, and `system-ui`.
- **Icons**: thin-line geometric illustrations and a small custom icon set.

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Hero Display | Display | 96px | 400 | 1.00 | -1.92px | Report title / top-of-page scale. |
| Section Display | Display | 72px | 400 | 1.00 | -1.44px | Major section hero headlines. |
| Section Display Alt | Body | 60px | 400 | 1.00 | -1.2px | Large in-page headings. |
| Section Heading | Body | 48px | 400 | 1.20 | -0.48px | Split hero and callout headings. |
| Card Heading | Body | 32px | 400 | 1.20 | -0.32px | Feature card and list section titles. |
| Feature Heading | Body | 24px | 400 | 1.30 | 0 | Cards, filters, and item titles. |
| Body Large | Body | 18px | 400 | 1.40 | 0 | Lead text and larger paragraphs. |
| Body | Body | 16px | 400 | 1.50 | 0 | Default copy and link text. |
| Button | Body | 14px | 500 | 1.71 | 0 | Compact button labels. |
| Caption | Body | 14px | 400 | 1.40 | 0 | Metadata and small explanatory text. |
| Mono Label | Mono | 14px | 400 | 1.40 | 0.28px | Uppercase technical labels. |
| Micro | Body | 12px | 400 | 1.40 | 0 | Footer, nav microcopy, and small links. |

### Principles

- Use massive type sparingly; pages often have one oversized headline and then settle into restrained 16px–24px UI copy.
- Keep display type tight. Hero copy should feel compact and carved, not airy.
- Avoid heavy bold weights. Size, spacing, and surface contrast do most of the hierarchy work.
- Use uppercase mono labels for category and system markers, especially on technical and reference sections.
- Reference and results sections can use coral markers and links, but the base typography stays black and measured.

## Layout

### Spacing System

The system uses an 8px base with many one-off alignment values: `2px`, `6px`, `8px`, `10px`, `12px`, `16px`, `20px`, `22px`, `24px`, `28px`, `32px`, `36px`, `40px`, `56px`, `60px`, `64px`, and `80px`.

Large sections rely on dramatic vertical breathing room. The page places supporting content far below the hero media. Detail sections often hold dark panels inside fields of empty white space, then transition to dense tables or footers only near the end.

### Grid & Container

- A document header uses a three-zone layout: report or section title left, contents/section links centered, action (e.g. download) right.
- The opening block centers the report title above a two-card media composition: a wide figure card beside a narrower image card.
- Feature sections commonly use 3-column cards on desktop.
- Detail pages alternate centered title blocks, supporting strips, large single-feature bands, and 2- or 3-column card grids.
- Reference sections (results tables, run logs, references) use full-width lists with value/date and category columns instead of decorative cards.
- Forms use two-column input rows inside a rounded white card on dark or stone section backgrounds.

### Whitespace Philosophy

Whitespace is a credibility signal. Large empty intervals separate the summary, the setup, the evidence, and the discussion. Dense content appears only where it serves the information: results tables, reference lists, and form fields.

## Elevation & Depth

The system is mostly flat. Depth comes from surface alternation, media contrast, rounded corners, and thin borders rather than drop shadows.

| Level | Treatment | Use |
| --- | --- | --- |
| Flat | No shadow, white or dark field | Hero copy, reference lists, editorial surfaces |
| Bordered | 1px `#d9d9dd`, `#e5e7eb`, or dark translucent rules | Table rows, forms, pale cards, footer inputs |
| Media Lift | Rounded image or figure over contrasting section color | Hero figure cards, visualizations, image bands |
| Dark Field | Deep green or navy full-width band | Highlighted capability, summary, and detail sections |

## Shapes

### Radius Scale

| Token | Value | Role |
| --- | --- | --- |
| `xs` | 4px | Small images, input fields, thumbnails, utility elements |
| `sm` | 8px | Chips, cards, small media, dialogs |
| `md` | 16px | Medium content cards and grouped blocks |
| `lg` | 22px | Signature media-card and soft placeholder radius |
| `xl` | 30px | Filter/topic pills |
| `pill` | 32px | Primary buttons |
| `full` | 9999px | Round status elements and fully pill-shaped controls |

### Image Treatment

Images are not decorative backdrops for text except in image bands. Most imagery sits as rounded cards with visible corners: figures, visualizations, thumbnails, and abstract renders. The dominant radii are 8px and 22px.

## Components

### **`button-primary`**

Near-black or white pill button, depending on surface contrast. Uses 14px–16px body type, 12px 24px padding, and a 32px pill radius. This is the primary action style for "Submit", "Download report", and hero actions.

### **`button-secondary`**

Text-only action link, usually underlined or rule-aligned, with no filled background. Used for companion actions such as "View details", "Open figure", and other secondary actions.

### **`button-pill-outline`**

Outlined pill control with transparent fill, 1px dark border, and 30px radius. Used for filters, category tags, and lightweight taxonomy controls.

### **`media-card`**

Rounded media card used in hero blocks and detail sections. It combines a figure or abstract image with an optional overlaid dark info module. Radius is usually 22px on large cards and 8px on smaller thumbnails.

### **`figure`**

The primary evidence unit for results. Each figure sits in a bordered frame — 1px Hairline (`#d9d9dd`), 8px (`sm`) radius — on white, with the caption beneath. Figures are numbered sequentially across the whole document, not per-section.

**Caption format.** The figure number is a mono label — `Figure N.` set in the Mono face at 12–13px — followed by the caption text in Ink (`#212121`) at 14px. The number reads as a distinct mono label rather than plain bold body text; it is typically set in Ink or a muted slate, and may take a restrained accent colour where the surrounding section already uses one. (The system mono resolves to Arial via the global stack; for a true monospaced figure label, this element may set its own monospace family, e.g. `ui-monospace, "JetBrains Mono", monospace`, without changing the global Mono token.)

**Variants:**

- **Full-bleed** — breaks out to the wider content max-width for a single dominant figure.
- **Side-by-side** — two or more panels in a row with `(a)`/`(b)` panel labels, sharing one caption.
- **Dark-mount** — a Near-Black Primary (`#17171c`) background inside the frame, for images that are themselves dark (e.g. dark-background visualizations) so they don't float on white. Use sparingly and only when appropriate.

**Click-to-enlarge.** Figures open in a lightbox for inspecting fine detail (mesh resolution, gradients, near-wall regions).

### **`console-panel`**

Dark technical panel for solver/case settings, code or command snippets, console/log output, and monospace data. Background is near-black, text is white or muted, and small accent chips carry status or category color.

### **`feature-card`**

Content block with a thin-line geometric illustration, a 24px heading, body copy, and a text link. On light backgrounds, cards often have only a top rule or a subtle image relationship rather than full boxing. Useful for describing a method, setup item, or capability.

### **`dark-feature-band`**

Deep green or navy full-width section used for highlighted content, key methodology, or summary callouts. Text turns white; cards use darker translucent surfaces, pale borders, and abstract line illustrations.

### **`summary-card`**

Warm stone card used for summaries and grouped specifications. Typically 3-column on desktop, with 8px radius, generous padding, a small pill button, a divider line, and checkmark bullet rows.

### **`category-chip`**

Coral category marker that labels a section's topic or classification (e.g. turbulence model, flow regime, case family, validation case). Active markers invert to coral fill with dark text; inactive markers use coral outline and pale fill. Kept restrained — a small marker that aids scanning, not a hero-level filter control.

### **`data-table`**

Rule-separated list or table with title or quantity left, category markers centered, and value or date right. Rows are tall, white, and border-driven. Suited to results tables, run logs, mesh and convergence summaries, force/coefficient comparisons, and reference lists.

### **`section-tabs`**

An underline tab row that folds several parallel reference blocks into one compact, scannable unit instead of a long vertical stack. A `tab-row` sits on a 1px Hairline (`#d9d9dd`) baseline; each `tab-btn` is body type at 14px/400 in Muted Slate (`#93939f`), transparent, with 12px 20px padding and a 2px transparent bottom-border. The active tab moves its text to Ink (`#212121`) and turns its bottom-border Ink — a single quiet underline, no fill, in keeping with the system's rule-and-underline character. Hover darkens an inactive tab from Muted Slate to Ink. Each `tab-panel` shows one at a time and may hold any reference content: a `data-table`, a `console-panel`, side-by-side code, or a wide scrolling table.

Reserve it for parallel peer categories inspected one at a time (e.g. Solver, Schemes, etc.), not sequential narrative or headline results. Since hidden panels drop out of print and in-page search, a print/export stylesheet should force every `tab-panel` open so nothing is lost on a PDF or a skim.

### **`figure-compare`**

An in-place comparison control for two or more views that share an identical frame — same crop, scale, and axes. A toggle, or a wipe/slider, swaps them in the same position so the eye catches the difference directly, instead of scrolling between stacked figures. Built on the `figure` frame (1px Hairline `#d9d9dd`, 8px `sm` radius) with a small Muted Slate (`#93939f`) toggle or slider control on the shared frame; use a `dark-mount` background for dark images.

Use it only for co-registered visuals where spotting the delta is the point — two meshes at the same crop, a contour field at two operating points, before/after a refinement. For values, tables, or differently-framed figures, prefer side-by-side; hiding one view defeats the comparison. This is the deliberate exception to `section-tabs`' "not headline results" line — a case or operating-point comparison often *is* the result, and is allowed here because co-registration does analytical work. A print/export stylesheet should expose all views.

### **`form-card`**

Rounded white input panel set against dark green or warm stone sections. Rarely needed in a report itself — reserved for occasional input surfaces such as a data-request or contact block. Inputs are rectangular with thin gray borders, 12px–16px padding, and compact labels/placeholders. Submit uses the same near-black pill style as the primary button.

### **`footer`**

Dark footer block with white section labels and muted links. May include a single-line input field with an arrow submit marker. Legal and metadata text uses muted microcopy.

## Do's and Don'ts

### Do

- Use white canvas as the default surface; introduce dark green or navy as full-width section bands.
- Keep primary buttons pill-shaped and near-black on light surfaces.
- Use 22px radius on major media cards and placeholders.
- Use coral for category/section tags and small warm accents, not as the main button system.
- Use restrained, monochrome supporting marks with wide spacing.
- Use thin-line geometric illustrations for technical and capability icons.
- Let figures and visualizations carry color, while the UI shell stays restrained.

### Don't

- Do not turn coral or blue into broad decorative surface colors.
- Do not add heavy drop shadows to cards.
- Do not make every section card-based; prefer unframed rows, rules, and open space where they read more cleanly.
- Do not use rounded cards below 8px for major media.
- Do not collapse the display/body type split into one generic sans-serif voice.
- Do not use saturated gradients as normal UI backgrounds; keep gradients media-led.

## Responsive Behavior

### Breakpoints

| Name | Width | Key Changes |
| --- | --- | --- |
| Small Mobile | <425px | Single-column cards, compact nav, reduced hero headline scale |
| Mobile | 425–640px | Hero media stacks, card grids become one column, form rows stack |
| Large Mobile | 640–768px | Wider one-column layouts with larger media cards |
| Tablet | 768–1024px | Two-column cards begin, nav spacing tightens |
| Desktop | 1024–1440px | Full nav, 3-column card grids, split hero compositions |
| Large Desktop | 1440–2560px | Wide containers and large empty vertical intervals |

### Touch Targets

Primary buttons and pills meet comfortable touch sizing through 12px–24px padding and pill radii. Filter chips and category chips are larger than standard tags, making dense taxonomy surfaces usable on touch devices.

### Collapsing Strategy

- Nav collapses from full horizontal links to a compact mobile menu.
- Hero media moves from split cards to stacked cards.
- Card grids collapse from 3 columns to 2 and then 1.
- Form fields collapse from paired rows to a single column.
- Table rows preserve their rule-separated structure but stack metadata below titles on smaller widths.

## Iteration Guide

1. Start from a white canvas or a full-width dark green/navy band; avoid mid-tone page backgrounds unless a specific callout/form section calls for it.
2. Use `button-primary` for the single highest-priority action and `button-secondary` for the companion action.
3. Use `media-card` or `console-panel` when a section needs visual energy; show real figures and values rather than invented data.
4. For reference and results content — tables, run logs, references — combine `data-table` with restrained `category-chip` markers and `button-pill-outline` filters, rather than marketing-style cards.
5. Keep examples structurally honest: placeholder figure frames are better than invented content.

## Known Gaps

- Proprietary display fonts are not bundled; the documented fallbacks (Space Grotesk, Inter, Arial) are the effective fonts when implementing externally.
- Mobile behavior is documented from the desktop system and the established responsive patterns above.
- Some content blocks may load late; blank placeholders are documented as skeleton surfaces rather than filled cards.
