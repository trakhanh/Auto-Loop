# KT Loop Station - Design system v2 ("Calm Editor")

Status: spec only. No app code was changed to produce this document.
Baseline screenshots: `docs/ui/before/*.png` (regenerate with `.venv\Scripts\python.exe tools\shots.py [--out DIR] [--palette neon|ocean|sunset|classic] [--font 10]`).

## 0. Direction in one paragraph

Today the app is "neon glass": every surface carries a violet-to-pink gradient, a radial glow sits behind every page, every card has a coloured top border, and at least five different elements per screen use the accent gradient. Target: a **calm, neutral, slightly cool-grey workspace** (DaVinci Resolve / CapCut desktop) where the content (clips, thumbnails, preview, timeline) is the only colourful thing, and **one flat accent colour** is reserved for: the single primary action, the selected item, focus, and progress. Gradients and glows are removed from chrome. The neon palette survives as the default *accent* (violet `#8b5cf6`), the pink second colour is kept only for the logo, welcome hero and timeline "music" accents.

Principles
1. Surface steps, not borders: hierarchy comes from 4 surface levels; borders are 1px, low contrast.
2. One accent, one primary button per view. Everything else is secondary/ghost.
3. Same thing looks the same: one button family, one input family, one card, one chip, one row.
4. State is always visible: hover, pressed, focus (keyboard), disabled, selected, busy, error - all defined once in the central QSS.
5. Idle means still: no animation runs while nothing is happening.
6. Readable at 100-200 % DPI and font-size 9-14 pt (Settings): all sizes scale from one factor.

---

## 1. Tokens

All tokens live in ONE dict in `theme.py` (`T`, replacing today's `C`; keep `C` as a thin alias during migration). Hex values below are for the default (neon/violet). Neutrals are shared by every palette and tinted by at most **3 %** of the accent (today 3-14 %, which is why borders and surfaces look purple).

### 1.1 Surfaces (dark)

| Token | Hex | Use | Today (neon) |
|---|---|---|---|
| `bg` | `#0e1015` | window, behind panels, page canvas | `#0a0b11` + radial glow |
| `panel` | `#14171e` | sidebar, header, cards, list/table body, dock | `surface` `#11141e`, gradient |
| `raised` | `#1a1e27` | secondary buttons, table header, hovered rows, combo popup | `surface2` `#181d2b` |
| `overlay` | `#222733` | menus, tooltips, dialogs, toast, popovers | `surface3` `#212839` |
| `field` | `#0b0d12` | input wells, list wells, code/log, player letterbox | `field` `#0c0e16`, `#080a0f`, `#000` |

Rule: a child is always one step lighter than its parent (`bg` -> `panel` -> `raised` -> `overlay`) except `field`, which is an inset well (darker than parent).

### 1.2 Lines

| Token | Hex | Use |
|---|---|---|
| `line_subtle` | `#1d212b` | dividers inside a card, table grid, row separators |
| `line` | `#2a3040` | card / input / button borders (default) |
| `line_strong` | `#3a4255` | hovered input/button, checkbox border, splitter handle hover base |

### 1.3 Text

| Token | Hex | Contrast on `panel` | Use |
|---|---|---|---|
| `text` | `#e8eaf0` | 14.5:1 | primary text, values |
| `text_2` | `#aab1c3` | 8:1 | secondary labels, table body secondary line |
| `text_muted` | `#7d869b` | 4.8:1 | hints, captions, placeholder (min allowed for real text) |
| `text_disabled` | `#4b5265` | 2.3:1 | disabled only (WCAG exempt) |
| `text_on_accent` | `#ffffff` | 4.8:1 on `#8b5cf6` | text on filled accent |

Banned for text: `#646c80`, `#64708d`, `#525a70`, `#475066` etc. (3-3.5:1). They are used today for section labels, hints and chip-off text.

### 1.4 Accent (palette-driven)

| Token | Derivation (neon) | Use |
|---|---|---|
| `accent` | `#8b5cf6` | primary button fill, selected indicator, slider fill, progress, checkbox on |
| `accent_hover` | mix(accent, white, 12 %) -> `#9b72f8` | hover of filled accent |
| `accent_pressed` | mix(accent, black, 18 %) -> `#7249d6` | pressed |
| `accent_subtle` | accent @ 16 % over parent | selected row, tonal button, selected tab/nav, chip-accent |
| `accent_subtle_hover` | accent @ 24 % | hover of subtle |
| `accent_text` | `mid` today (`#a78bfa`) | accent-coloured text/icons on dark (must be >= 4.5:1) |
| `focus` | accent @ 70 % | focus border; plus 2px ring accent @ 35 % (see 4.1) |
| `accent2` | `#ec4899` | **brand only**: logo, welcome hero, music-lane colour in timeline. Never on controls. |

### 1.5 Semantic (palette-independent)

| Token | Base | Subtle bg (14 %) | Border (40 %) | Text on dark |
|---|---|---|---|---|
| `success` | `#34b27b` | rgba(52,178,123,.14) | rgba(...,.40) | `#6ee7b7` |
| `warn` | `#e0a030` | rgba(224,160,48,.14) | rgba(...,.40) | `#f5c76a` |
| `danger` | `#e5534b` | rgba(229,83,75,.14) | rgba(...,.40) | `#f59a95` |
| `info` | `#4c9be8` | rgba(76,155,232,.14) | rgba(...,.40) | `#9cc8f5` |

Replaces the ~15 ad-hoc greens/ambers/reds in code (`#10b981`, `#34d399`, `#6ee7b7`, `#14532d`, `#f59e0b`, `#fbbf24`, `#fcd34d`, `#ef4444`, `#f87171`, `#fca5a5`, `#93c5fd`, `#60a5fa`, `#22d3ee`...). Status is never colour-only: pair with an icon or word.

### 1.6 Media-specific (timeline, waveform, thumbnails) - tokens too

`lane_clip` = info `#4c9be8` @ 85 %, `lane_music` = success-teal `#2fb5a4` @ 85 %, `lane_ambient` = `#8b7cf0`, `playhead` = `#f4f5f8`, `ruler_text` = `text_muted`, `lane_bg` = `field`, `seam_marker` = `warn`. These are read through `theme.qcolor(token)` at paint time, so palette switching stays live.

### 1.7 Palette mapping (palette switching keeps working)

A palette now defines only: `accent`, `accent2` (brand), `accent_text`, and optional `accent_on` (text colour on filled accent: white unless the accent is light).

| Key | Name | accent | accent_text | accent2 (brand) | Note |
|---|---|---|---|---|---|
| `neon` (default) | Neon tim hong -> rename "Tim (mac dinh)" | `#8b5cf6` | `#a78bfa` | `#ec4899` | default; keep key for saved prefs |
| `ocean` | Dai duong | `#0891b2` (darkened from `#06b6d4` so white text passes 4.5:1) | `#67e8f9` | `#6366f1` | accent_on `#ffffff` |
| `sunset` | Hoang hon | `#ea580c` (from `#f97316`) | `#fdba74` | `#e11d48` | accent_on `#ffffff` |
| `classic` | Tim xanh (ban cu) | `#7c5cff` | `#a78bfa` | `#3b82f6` | |

Add a build-time check (unit test in `tests/`): for every palette, contrast(`text_on_accent`, `accent`) >= 4.5 and contrast(`accent_text`, `panel`) >= 4.5. `set_palette()` no longer mixes the neutrals by 3-14 %; it uses `mix(neutral, accent, 0.03)` for `bg/panel/raised/overlay/field` and no tint on lines.

Remove: `_OLD` replace-table, `grad`, `grad_hover`, `grad_diag`, `grad_soft`, `card_bg` gradient, radial `pageStack` background, `sidebar` / `header` / `welcomeCard` gradients, coloured `border-top-color` on cards.

---

## 2. Typography (Segoe UI; numbers Consolas -> `Cascadia Mono, Consolas`)

Sizes are pt at the default 10 pt app size and scale with `Settings -> Co chu` (factor `k`, as today). Weights limited to 400 / 600 / 700 (drop 800).

| Role | pt | Weight | Line height | Use |
|---|---|---|---|---|
| `caption` | 8.5 | 400 | 1.3 | badges, helper under a field, timeline ruler |
| `small` | 9 | 400/600 | 1.35 | table secondary line, chips, tooltips, buttons `sm` |
| `body` | 10 | 400 | 1.45 | default text, inputs, table body |
| `label` | 10 | 600 | 1.35 | field labels, buttons, tabs, nav, table header (in `text_2`) |
| `subtitle` | 11 | 600 | 1.35 | card titles, dialog section titles, primary button (lg) |
| `title` | 13 | 700 | 1.3 | page title, dialog title |
| `display` | 17 | 700 | 1.2 | home / welcome heading only |
| `mono` | 9.5-10 | 600 | 1.2 | time codes, sizes, counts (tabular); right aligned |

Rules
- Merge today's 8 steps (8.5/9/10/10.5/11.5/12.5/13.5/17) into the 7 above; no 10.5/11.5/12.5/13.5.
- Section headers in sidebar/panels: sentence case `label` in `text_muted`. Drop the tracked-out ALL CAPS with `letter-spacing: 1px` ("QUY TRINH 3 BUOC", "TRINH PHAT") - it is low contrast and decorative.
- No single accented word in headings (Home hero "hom nay?" is pink gradient text): use `text` throughout.
- Line length <= ~90 characters for prose (Home tip strip, step guide hint, Help body): set max width 720 px for prose blocks.
- Vietnamese diacritics need line-height >= 1.3; never clip labels at fixed pixel heights - use `min-height` from the control-height scale (3.2).

## 3. Spacing, radius, size, elevation, motion

### 3.1 Spacing (4-pt grid)
`2 (hairline gap) · 4 · 8 · 12 · 16 · 24 · 32`. Existing `SP` keys map: `xs=4, sm=6 -> 8, md=8, lg=12, xl=16, xxl=24`; add `2xs=2`, `3xl=32`. 6 px is retired (use 4 or 8).
- Page margins `16/12/16/12` -> `16` all round (24 for Home/Settings/Help prose pages).
- Gap between cards 12; inside card padding 16 (12 compact); label-to-field 6 -> 4; field rows 8; toolbar items 8, toolbar groups 16 with a 1px `line_subtle` separator.
- Sidebar item padding 8 x 12; header height 48; step guide height 40; timeline dock 96 (see 4.9).

### 3.2 Control heights
`sm 24 · md 32 (default) · lg 40` px (scale by `k`). Buttons, inputs, combos, spinboxes of the same row MUST share a height (today: inputs ~32, pills ~24, accent buttons ~32 and primary ~44 in one row).

### 3.3 Radius (today: 15 distinct values 3-21 px)
`radius_sm 4` (chips, checkbox, scrollbar, small badges) · `radius_md 6` (buttons, inputs, combos, tabs, list rows, nav items) · `radius_lg 8` (cards, panels, tables, tooltips, menus) · `radius_xl 12` (dialogs, overlays, welcome card, toast) · `radius_pill 999` (status chips and the play button only).
Mapping: 3,4,5 -> 4 · 6,7,8,9 -> 6 (controls) or 8 (containers) · 10,11,12,13,14 -> 8 (cards) / 12 (overlays) · 18, 21 -> 12 / pill.

### 3.4 Elevation
Qt widgets have no CSS shadows; use surface level + border for everything inside the window.
| Level | Surface | Border | Shadow (QGraphicsDropShadowEffect, only on top-level popups) |
|---|---|---|---|
| 0 canvas | `bg` | - | - |
| 1 panel/card | `panel` | `line_subtle` or none | - |
| 2 raised control | `raised` | `line` | - |
| 3 popup (menu, combo list, tooltip) | `overlay` | `line` | blur 16, y 4, rgba(0,0,0,.45) |
| 4 dialog / overlay / toast | `overlay` | `line` | blur 32, y 8, rgba(0,0,0,.55) + dim backdrop rgba(0,0,0,.55) |
Never attach a QGraphicsEffect to a scrolling list, the preview, or the timeline (repaint cost).

### 3.5 Motion
| Token | Value | Use |
|---|---|---|
| `dur_fast` | 120 ms | hover/pressed colour on custom-painted widgets (QSS hover is instant - that is fine) |
| `dur_base` | 180 ms | nav pill slide, segment pill slide, toast in/out, expanders |
| `dur_slow` | 240 ms | page cross-fade (`AnimatedStackedWidget`), overlay in |
| easing | `OutCubic` (enter), `InOutCubic` (move), `InCubic` (exit) | - |
Rules
- **No continuous animation when idle.** No pulsing glow, shimmer or looping spinner unless a job is running; any `QTimer`/`QVariantAnimation` used for visuals must `stop()` when the widget is hidden or the job ends. Busy states: determinate progress bar, or a static "Dang do..." label with `[busy="true"]` styling, not an endlessly redrawing widget.
- Only animate `opacity`/position of small overlays; never animate layout of the working area.
- Respect OS "Show animations" (Windows `SPI_GETCLIENTAREAANIMATION`): if off, durations = 0. Expose via one `theme.motion_enabled()`.
- Total transition budget per user action <= 240 ms.

---

## 4. Components

QSS selectors use **dynamic properties** (see 6.2), not per-widget stylesheets. Colours below are token names.

### 4.1 Focus (global rule)
Keyboard focus must be visible on every interactive control. QSS cannot tell keyboard from mouse focus, so: (a) inputs/combos/spins use `border-color: focus` on `:focus`; (b) buttons, checkboxes, tabs, list rows, nav items get a 2 px ring drawn by a small `QProxyStyle` subclass (`ThemeStyle.drawPrimitive(PE_FrameFocusRect)`: rounded rect, `focus` colour, 1.5 px, 2 px outside), shown only for `Qt.TabFocusReason`/`BacktabFocusReason`. Remove the global `* { outline: none; }` once this exists.

### 4.2 Buttons (`QPushButton`, property `variant` + `size`)
Common: height by size (md 32), padding 0 14, radius 6, `label` font, icon 16 (sm 14), icon gap 8, `cursor: pointing-hand`, `min-width` 64 for text buttons.

| Variant | Rest | Hover | Pressed | Disabled |
|---|---|---|---|---|
| `primary` (max 1 per view) | bg `accent`, text `text_on_accent`, no border | bg `accent_hover` | bg `accent_pressed` | bg `raised`, text `text_disabled` |
| `tonal` (replaces `accentBtn`, `nextStepBtn`) | bg `accent_subtle`, text `accent_text`, no border | bg `accent_subtle_hover` | accent @ 32 % | bg `raised` 60 %, text `text_disabled` |
| `secondary` (default) | bg `raised`, 1px `line`, text `text` | border `line_strong`, bg `overlay` | bg `field` | text `text_disabled`, border `line_subtle`, bg `panel` |
| `ghost` | transparent, text `text_2` | bg rgba(255,255,255,.06), text `text` | rgba(255,255,255,.10) | text `text_disabled` |
| `danger` | like `ghost` but text `danger` (text `danger-text`), no fill | bg `danger` 14 %, border `danger` 40 % | danger 22 % | `text_disabled` |
| `danger-solid` (confirm dialogs only) | bg `danger`, white text | lighten 10 % | darken 15 % | - |
Sizes: `lg` 40 px (the single Export "Bat dau xuat" button, dialog primary), `md` 32, `sm` 24 (table/list inline actions, replaces `pill`). Icon-only buttons: square (`sm` 24x24, `md` 32x32), ghost, tooltip required.
"Xoa het" (clear all) is `danger` ghost and moves into the overflow menu "..." of the list toolbar; "Xoa" stays visible as ghost.

### 4.3 Inputs (`QLineEdit`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox`, `QPlainTextEdit`)
Height 32 (sm 24), bg `field`, border 1px `line`, radius 6, padding 0 10, text `text`, placeholder `text_muted`, selection `accent` @ 45 %.
Hover: border `line_strong`. Focus: border `focus`. Invalid (`[state="error"]`): border `danger`; helper text below in `danger-text` + icon. Warning: `[state="warn"]` border `warn`. Disabled: bg `panel`, text `text_disabled`, border `line_subtle`.
Spinbox buttons: 16 px wide, no per-button border, chevron icons `text_muted`, hover bg `raised`. Time boxes (`#timeBox`): Consolas, centred, no arrows.
Combo: drop-down chevron 12 px `text_muted`; popup `overlay`, 1px `line`, radius 8, item height 28, selected item bg `accent_subtle` + text `text` (not a gradient + white).
Layout rule: in forms, label column fixed width (e.g. 160 px), left-aligned, `text_2`; fields fill remaining width and share the same left edge across all cards on a page.

### 4.4 Checkbox / radio / switch
Indicator 16 px, radius 4, border `line_strong`, bg `field`; checked: bg `accent`, white check; hover border `accent_text`; disabled checked `accent` @ 35 %. The *unchecked* box must always be visible (today it nearly disappears on "Quet thu muc con" in the toolbar). Label spacing 8. Use a 32x18 switch for on/off settings that apply immediately (GPU decode, notifications); checkbox for things applied on action.

### 4.5 Slider
Groove 4 px `line` (radius 2), filled part `accent` flat (no gradient), handle 14 px circle `text` with 2 px `accent` border (hover: 16 px, `accent_text`), focus ring per 4.1, disabled: groove `line_subtle`, fill/handle `text_disabled`. Seek bar in the player and volume slider use the same slider; seek bar groove 4 px with buffered/cut markers drawn in `warn`.

### 4.6 Tabs, segmented controls, nav
- **Sub-tabs (`QTabBar`)** (Do dai / Khung & Tieng / Mau & Logo): underline style - transparent tab, text `text_muted`, padding 8 x 14, hover text `text`, selected text `text` + 2 px `accent` bottom border; bar has 1px `line_subtle` bottom. No pill boxes.
- **Segmented (`segBox`, mode switch Video co nhac / Chi video / Chi nhac, product kind)**: container `field`, 1px `line`, radius 8, padding 2; segment radius 6, text `text_2`; selected segment bg `raised` + text `text` + (optional 2 px accent underline); the sliding pill (`motion.SegmentBox`) keeps working with `raised` fill and no border. One component for all segmented choices; delete `segL/segM/segR`.
- **Sidebar nav (`nav`)**: height 36, radius 6, icon 18 (`text_muted`), label `label`; hover bg rgba(255,255,255,.05); selected bg `accent_subtle` + 3 px `accent` bar on the left edge inside the item, text `text`, icon `accent_text`. Drop the 3-layer treatment (gradient + border + left bar). Section labels: `small` `text_muted` sentence case, margin-top 16. Step badges ("(6)", "(10 bai, 1 nen)") become right-aligned `caption` chips so they stop shifting the label.
- **Step guide**: ONE navigation affordance for steps. Keep it in the page header zone as a compact stepper (3 steps, `sm` ghost buttons, done = check icon `success`, current = `accent` dot + `text`), remove the duplicate "QUY TRINH 3 BUOC" label in the sidebar OR remove the stepper; hint text is one line `text_2` with ellipsis + tooltip, max ~110 chars.

### 4.7 Chips / badges (`QLabel[chip]`, property `tone`)
Height 22, radius pill, padding 0 10, `small` 600. Tones: `neutral` (bg `raised`, border `line`, text `text_2`), `accent` (bg `accent_subtle`, text `accent_text`), `success|warn|danger|info` (bg subtle 14 %, border 40 %, text token). The header "Tong 3:00:00" chip becomes a plain stat (`mono` value + `text_muted` caption), not a gradient pill. Encoder chips on Settings are fixed-width (96 px) in a grid, tone `success` (available) / `neutral` + `text_disabled` (not available), icon check/dash instead of text glyphs.

### 4.8 Lists, tables, cards with thumbnails (`QTreeWidget#clips`, tracks, chapters)
- Container: bg `panel`, 1px `line_subtle`, radius 8, no inner padding. Header: bg `panel`, text `text_muted` `label`, 32 high, bottom 1px `line`, no vertical separators; sortable header hover text `text`.
- Rows: clips 56, tracks/chapters 32 (comfortable) - 28 (compact). Row separator 1px `line_subtle` (replaces alternating colour `#161b28`). Hover bg rgba(255,255,255,.04). Selected bg `accent_subtle`, plus 2 px `accent` left bar; text stays `text` (not white-on-gradient). Disabled/unchecked row text `text_disabled`, thumb 50 % opacity.
- Clip row anatomy: [checkbox 16] [thumb 64x36, radius 4, 1px `line` ] [name `body` 600 elide-middle + tooltip with full path / secondary line `small` `text_muted`: "1920x1080 - 24 fps - 8.0 s"] [numeric columns].
- Column alignment: text left; **all numbers and durations right-aligned in Consolas** with consistent header alignment; editable cells show a 1px `line` underline on hover to signal "double-click to edit" (instead of relying on the footer hint).
- Cards (`QFrame[card]`, replaces `QGroupBox` look): bg `panel`, 1px `line_subtle`, radius 8, padding 16. Title is a normal `subtitle` label row (not `QGroupBox::title` at an odd offset), with optional right-aligned action. No coloured top border.
- Home cards (`homeCard`): same card, 1px `line_subtle`; hover border `line_strong` + bg `raised`; the category colour is only the 32 px icon tile (`info`/`success`/... at 14 %), borders are neutral.

### 4.9 Timeline dock
Dock `panel`, top 1px `line`; fixed height 96-112 (collapsible to 28 with a chevron; remember state). Lane well `field`, radius 6. Ruler 20 px, ticks `line_strong`, labels `caption` `text_muted`, mono. Lane labels ("CLIP", "NHAC") `small` `text_2` with a 14 px icon, not all-caps. Blocks radius 3, 1px darker inner border, label `caption` white on lane colour (check 4.5:1; use dark text on light lanes). Playhead 2 px `playhead` with a 10 px rounded handle at top; selected segment outlined in `accent`. Seams marked with a `warn` triangle. Waveform neutral `text_muted` @ 55 % (today it is a rainbow of per-column colours which is the loudest thing on screen).
Total length / loop count chips at right in `mono`.

### 4.10 Player panel
Panel `field`, left 1px `line`. Title "Trinh phat" `label` `text_muted` (no caps) + resolution chip (neutral). Video letterbox fills available height (16:9 centred, never a tiny 16:9 floating in a tall black area: let it use width, align top with 12 px margin, controls docked under it). Seek bar full width directly under video; time code `mono` `text` / total `text_muted`; transport row centred: prev, -10, **Play (40 px circle, flat `accent`, white icon)**, +10, volume, fullscreen - all other buttons ghost icon 32 px with tooltips + shortcuts ("Phat / Dung (Space)"). Empty state: dimmed controls + centred hint "Them clip de xem truoc".

### 4.11 Dialogs, overlays, toast, menus, tooltips
- Dialog: `overlay` bg, 1px `line`, radius 12, padding 24, title `title`, body `body` `text_2`, footer right-aligned buttons with 12 gap: secondary "Huy" then primary; destructive confirm uses `danger-solid`. Min width 420, max prose width 480. Title bar frame stays dark (`branding.apply_window_frame`).
- Welcome / first-run overlay: backdrop rgba(0,0,0,.55); card `overlay`, radius 12, 1px `line`, padding 32; step cards `panel` radius 8; step number badges flat `accent_subtle` + `accent_text` (not gradient discs); one `primary` "Bat dau".
- Toast: `overlay`, radius 12, 1px `line`, 4 px left bar in tone colour, icon 16, auto-dismiss 4 s (8 s for warn), hover pauses; max 1 line + optional action.
- Menu: `overlay`, 1px `line`, radius 8, padding 4; item height 28, radius 4, hover/selected bg `accent_subtle`; separators `line_subtle`; shortcut text right `text_muted`.
- Tooltip: `overlay`, 1px `line` (not accent), radius 6, padding 6 x 10, `small`, max width 320, delay 500 ms. Every icon-only button and every truncated text has one; tooltips state action + shortcut, never repeat the label.

### 4.12 Scrollbars
Width/height 10 (hit area), track transparent, handle `line_strong` radius 4 with 2 px margin (visual 6 px), hover `text_muted` @ 60 %, pressed `accent`; min handle 32; no arrows. Show only while hovering the scroll area or scrolling (opacity via handle colour alpha) - no animation needed. Nested scroll: pages are in `QScrollArea` (keep) but the working list must not create a second scrollbar inside the page when avoidable (see 7.2).

### 4.13 Progress
`QProgressBar`: height 8 (determinate bars in lists/cards) or 20 (export main bar with centred percentage), bg `field`, 1px `line`, chunk flat `accent` radius 4, text `mono` `text`. Success: chunk `success` at 100 % for 2 s. Error: chunk `danger`. Indeterminate (probing, size estimate): no marquee; show `Dang do...` text in `text_muted` and a static 2 px accent line, so idle UI never repaints.

### 4.14 Empty states
Centre of the region: 40 px tonal icon tile, title `subtitle` ("Chua co video hoac anh"), one sentence `body` `text_2` stating what to do, and a **button** doing it (`secondary` "Them file", plus "Keo tha vao day"). The dashed drop zone (`QFrame[drop]`: 1px dashed `line_strong`, radius 8) highlights with `accent` border + `accent_subtle` bg on drag-over. Same pattern for: clip list, playlist, queue, timeline ("Keo tha video hoac nhac vao du an de xem dong thoi gian"), chapters list.

### 4.15 Info / callout bar (`QLabel#info`, Help `tip/warn/ex` boxes, Home tip strip)
One component `callout[tone]`: bg tone subtle 10 %, left 3 px bar tone, radius 6, padding 10 x 14, icon 16 + text `body` `text_2`. Help HTML boxes use the same tone tokens via the CSS variable substitution (see 6.4) instead of hard-coded `#13233f / #3a2a0f / #1d1838`.

---

## 5. Current styling inventory (measured 2026-10-23)

`loopstation/ui/*.py`, 15,000 lines:
- Inline `setStyleSheet`: **14 calls outside theme.py** (`trim_dialog` 5, `video_tab` 2, `widgets` 2, `batch_dialog`, `home_page`, `look_panel`, `motion`: 1 each) + the global one.
- Hard-coded hex literals: **247 uses / 87 distinct** outside `theme.py` (theme.py itself: 95). Top offenders by file: `help_page` 41, `timeline_bar` 37, `video_tab` 25, `widgets` 18, `batch_dialog` 16, `music_tab` 14, `preview_player` 14, `trim_dialog` 14, `export_tab` 10.
- `QColor(...)` constructions: ~140 (`timeline_bar` 25, `video_tab` 23, `preview_player` 20, `effects` 12, `splash` 12, `widgets` 11, `music_tab` 9, `trim_dialog` 7).
- `rgba(` in QSS: 40 in theme.py (+2 `video_tab`); `font-size` in QSS: 26 in theme.py + 9 inline.
- Already token-aware: `theme.C[...]`/`qcolor(...)` used ~46 times outside theme.py; `SP`, `FS` used in few files. `setObjectName` is used ~170 times (good base for property-based variants).
- Most repeated colours outside theme: `#ffffff` x22, `#8c96b0` x16 (muted), `#eef1f8` x12 (text), `#f59e0b` x10, `#fca5a5` x10, `#fcd34d` x9, `#646c80` x9, `#f87171` x7, `#fbbf24` x7, `#14532d` x7, `#334155` x7, `#f8fafc` x6, `#22d3ee` x5, `#10b981` x5, `#93c5fd` x5, `#cbd5e1` x5, `#1e293b` x5. About 20 of the 87 are near-duplicates of the same 5 greys, 4 ambers, 4 reds, 4 blues.
- Border radii in use: 3,4,5,6,7,8,9,10,11,12,13,14,18,21 px (`10` x14, `8` x13 most common). Font sizes in QSS: 8.5/9/10/10.5/11/11.5/12.5/13.5/14/16/17 pt.
- Fixed neutrals in theme.py with no token: `#2c3347`, `#475066`, `#525a70`, `#566079`, `#1e2433`, `#3d465e`, `#161b28`, `#080a0f`, `#0b0d13`, `#cbd5e1`, etc. (disabled/scrollbar/alt row).

### Hex -> token cheat sheet (for the mechanical replace)
`#0b0d13/#0b0d12/#0b0d14/#0c0e16/#080a0f` -> `field` · `#0e1015/#0a0b11` -> `bg` · `#121621/#11151f/#171c2b/#161b28/#1f2330` -> `panel` · `#1a2030/#181d2b/#1e2538/#1e293b` -> `raised` · `#232b3e/#222733` -> `overlay` · `#242b3d/#252c3f/#232838/#2a2f3c/#232a3c` -> `line` · `#334155/#343e58/#3d465e/#2c3347` -> `line_strong` · `#eef1f8/#f8fafc/#e5e7f0/#e7e9f0/#ffffff(text)` -> `text` · `#cbd5e1/#c3cbe0` -> `text_2` · `#8c96b0/#64748b/#646c80/#64708d/#7c86a2/#78839e` -> `text_muted` · `#475066/#4d556a/#525a70/#566079` -> `text_disabled` · `#f59e0b/#fbbf24/#fcd34d` -> `warn`/`warn-text` · `#10b981/#34d399/#6ee7b7/#14532d` -> `success`/`success-text`/subtle · `#ef4444/#f87171/#fca5a5` -> `danger`/`danger-text` · `#3b82f6/#60a5fa/#93c5fd/#22d3ee` -> `info`/`info-text` · `#a78bfa/#c4b5fd/#ddd6fe/#7c5cff/#8b5cf6` -> `accent*`.

---

## 6. Migration plan

Goal: zero behaviour change, visuals change in 4 small PRs, each shippable and reversible. Run `tools/shots.py --out docs/ui/after-N` after each and diff against `before`.

### 6.1 Phase A - tokens + central QSS (theme.py only, ~1 day)
1. Introduce `T` (tokens, section 1) and `set_palette()` per 1.7. Keep `C = T` alias and old keys (`surface`, `surface2`, `surface3`, `border`, `border_light`, `muted`, `mid`, `soft`, `ok`) as read-only aliases so unmigrated files keep working: `surface->panel`, `surface2->raised`, `surface3->overlay`, `border->line`, `border_light->line_strong`, `muted->text_muted`, `mid->accent_text`, `soft->accent_text`, `ok->success`.
2. Add `px(n)` (scales by font factor `k`), `pt(role)`, `radius(name)`, `space(name)` helpers. Replace the regex font-size scaling in `qss()` by calling `pt()` in the template (keep the regex only for legacy inline strings until Phase C finishes).
3. Split `_qss_base()` into small functions that return QSS per component group (`_q_buttons`, `_q_inputs`, `_q_lists`, `_q_nav`, `_q_dialogs`, ...) using the tokens; delete gradients and the radial glow. Write selectors for the new property variants AND keep the old `objectName` selectors as aliases mapping to the new look:
   `#accentBtn -> variant tonal`, `#nextStepBtn -> variant primary size md`, `#primary -> variant primary size lg`, `#danger -> variant danger`, `#ghost -> ghost`, `#pill -> secondary sm`, `#segL/#segM/#segR -> segmented`, `#chip/#chipAccent/#chipOk/#chipWarn/#chipError/#chipOff -> chip tones`, `#info -> callout`.
   Result: the whole app restyles with no other file touched.
4. Add `ThemeStyle(QProxyStyle)` for the focus ring (4.1) and `theme.repolish(widget)` (`style().unpolish/polish`) helper; `app.setStyle(ThemeStyle("Fusion"))`.
5. Palettes: add accent-contrast unit test; adjust `ocean`/`sunset` accents per 1.7.
6. Add `tests/test_theme_tokens.py`: every token present for every palette, contrast checks, `qss()` contains no `qlineargradient`, no unreplaced `{...}`.

### 6.2 Phase B - property-based variants (touch widgets that set styles inline)
Pattern, instead of `w.setStyleSheet("color:#fca5a5; font-weight:600")`:
```python
w.setProperty("tone", "danger")      # or variant="primary", size="sm", role="muted"
theme.repolish(w)                    # only needed if changed after show()
```
QSS: `QLabel[role="muted"] { color: {text_muted}; }`, `QPushButton[variant="primary"] {...}`, `QLabel[tone="danger"] {...}`. Helper `theme.tag(widget, variant=..., size=..., tone=..., role=...)` sets all and repolishes once.
Per-file list (do in this order, smallest first):

| File | Work |
|---|---|
| `widgets.py` (2 setStyleSheet, 18 hex, 11 QColor) | line colour -> `line` token; match label colour -> `tone`; `MediaList`/delegates: paint with `theme.qcolor()`; `ListToolbar` -> new button variants + overflow "..." menu; empty-state placeholder -> 4.14 |
| `motion.py` | `NavPill`, `SegmentBox`, `Toast` colours -> tokens; dot `setStyleSheet` -> `tone`; add `motion_enabled()` guard + dur tokens |
| `home_page.py` | remove local stylesheet; card + icon tile via properties; remove per-card coloured borders; hero heading plain |
| `look_panel.py`, `batch_dialog.py` (16 hex), `sequence_dialog.py`, `interleave_dialog.py` | replace hex with tokens; dialog footer pattern 4.11; `kl` label style -> `role` |
| `trim_dialog.py` (5 setStyleSheet, 14 hex) | replace with `QFrame[card]` / `[player]`; Consolas time label -> `role="mono"`; letterbox `field` |
| `video_tab.py` (2 + 25 hex, 23 QColor), `music_tab.py` (14 hex), `export_tab.py` (10 hex), `mixer_panel.py` (7), `settings_page.py`, `main_window.py` (6) | swap hex -> tokens; `suggestBar` -> `callout` tone accent; chip creation uses `chip(text, tone)`; buttons get `variant`/`size` instead of `objectName` mix |
| `help_page.py` (41 hex) | HTML/CSS strings read tokens through `theme.css_vars()` (see 6.4) |
| `timeline_bar.py` (37 hex, 25 QColor), `preview_player.py` (14/20), `effects.py`, `splash.py`, `branding.py`, `step_guide.py`, `welcome.py` | painted widgets: replace literals with `theme.qcolor("lane_clip")` etc., read at paint time; waveform neutral |

### 6.3 Phase C - delete legacy
After B: remove the objectName aliases that no code uses (grep each), remove the `C` alias keys, the `_OLD` map, regex font scaling, the `grad*` helpers. Add a lint test: `grep -E "#[0-9a-fA-F]{6}" loopstation/ui/*.py` outside `theme.py`, `icons.py`, `splash.py`/`branding.py` (brand art) must be 0, and `setStyleSheet(` outside theme.py must be <= 3 (documented exceptions, dynamic colours only).

### 6.4 Help page HTML
`theme.css_vars()` returns a dict of tokens; `help_page.py` uses `Template` substitution (`$text`, `$panel`, `$success_subtle`...) so `<table bgcolor="#11151f">` etc. follow the palette. Callout boxes use the tone tokens.

### 6.5 Icons (`icons.py`)
Keep SVG icons but unify: 24-unit viewBox, 1.75 stroke, round caps/joins, colour from token via `currentColor` replacement (`text_muted` rest, `text` hover/selected, `accent_text` active). Render through `QIcon` with SVG engine / pixmaps at `devicePixelRatioF()` so 200 % DPI is crisp; sizes 14/16/18/20 only. Replace text glyphs used as icons (`✓`, `✗`, `↻`, `→`, `①②③`) with icons or plain text. Provide Normal/Active/Disabled/Selected modes.

### 6.6 DPI / scaling checks
- All control heights/paddings in QSS go through `px()` (scales with the font-size preference); icon sizes likewise.
- Verify at 100 %, 150 %, 200 % (`QT_SCALE_FACTOR=1.5/2` with `tools/shots.py`) and font 9/10/12/14: no clipped Vietnamese diacritics, no elided primary labels, no horizontal scroll at 1280x720 (the minimum supported window).
- Add `--scale` and `--font` loops to `tools/shots.py` for a visual regression sheet (4 palettes x 2 scales).

### 6.7 Definition of done
No gradient in QSS; <= 3 inline `setStyleSheet`; 0 stray hex outside theme/brand art; one primary button per page; all interactive controls show keyboard focus; contrast tests pass for 4 palettes; no timers/animations running at idle (check with `tools/bench_ui.py --idle 5`, CPU ~0 %); screenshots reviewed against section 7.

---

## 7. Page-by-page improvements (from `docs/ui/before/`)

Numbers refer to the screenshots at 1440x900.

### 7.1 Global shell (`main_window.py`, all pages)
1. **Header (48 px) is overloaded and inconsistent** (`02`, `05`): project-name box is clipped ("Mau - 3 tieng lap cl"), 4 ghost buttons with 12 px icons in 9 pt text, a 3-segment mode switch that looks like tabs, a gradient "Tong 3:00:00" pill and a "Dong thoi gian" outline button all use different heights/radii. -> Left: project name (inline editable label, ellipsis + tooltip, flexible width 160-320). Middle: segmented mode control (4.6). Right: total duration as `mono` stat, timeline toggle as ghost icon button with tooltip. File actions (Moi/Mo/Luu/Luu thanh...) move into a single "Tep" menu button + a Save icon button; shortcuts shown in the menu.
2. **Three step indicators** (sidebar section, step-guide strip, header badges `1. Video v`): one stepper only (4.6). The guide hint wraps to 2-3 lines at 1440 and reads like a paragraph (`05`, `06`) -> single line, ellipsis, full text in tooltip; next-step action is the page's own `primary` button.
3. **Sidebar** (`01`): remove gradient + 3-layer selected state; "Cong cu / Xuat hang loat..." looks like a nav item but is an action -> make it a secondary button in a "Cong cu" block or move to the Export page; the GPU card at the bottom looks like a button -> plain status row (icon + "GPU: NVIDIA, Intel", tooltip with details, click opens Settings). Section labels sentence case, readable muted colour.
4. **Backgrounds**: remove radial glow and gradient header; the right half of every page is darker than the left (`02`, `05`), which reads as a rendering bug.
5. **Working-area vertical budget** (`05`, `06`, `07`): header 54 + guide 44 + timeline dock 96 leaves ~690 px; list shows 5-6 rows, the "Dat nhanh" card and sub-tabs are cut off at the bottom edge. -> Timeline dock default collapsed to a 36 px strip (expand on demand / auto-expand when project has clips and window height >= 900); guide merged into header zone (saves 44 px); card list uses `QSplitter` so the user can trade list height vs settings (`workSplit` already exists, extend it vertically).

### 7.2 Video page (`02`, `05`)
- **Toolbar** is 12 controls in 2 wrapped rows with 5 styles (accent outline, ghost, red, pill, text checkbox). -> Row 1: `[+ Them file]` (`secondary`, the only "add" primary-ish), `[Thu muc]`, search field (right, 240 px); Row 2 (selection actions, ghost icons with tooltips): move up/down, sort A-Z, shuffle, select-menu, delete; "Xoa het" and "Quet thu muc con" go into a "..." menu / the folder-add dialog. Unchecked checkbox visible (4.4).
- **Table**: truncated names and meta ("01 Mua de...h pho.mp4", "1920x1080 - 24 fps - 8.0s - C...") -> elide in the middle only for names with tooltip, secondary line shortened; numbers right-aligned mono; header muted; remove tinted gradient behind the table; row hover/selection per 4.8; editable-cell hint in the column header tooltip.
- **"Dat nhanh (dong chon)" card**: row of 9 mixed controls (spin, 5 pills, accent "Ap dung", ghost "Cat doan", "Hoan tac") -> one `card` with 2 aligned rows: [Label + spin + quick values as `sm` segmented chips + `Ap dung` tonal] and [Cat doan & hoa hinh dropdown + Hoan tac ghost]. The helper paragraph below (3 lines of `muted` text) becomes a tooltip/"?" icon or collapses after first use.
- **Sub-tabs** (Do dai / Khung & Tieng / Mau & Logo) -> underline tabs (4.6); dot indicator "Khung & Tieng ." keeps as 6 px `accent` dot.
- **Empty state** (`02`): good concept, improve per 4.14: add an actual "Them file" button inside the drop zone; the stray empty rounded box next to "TRINH PHAT" (empty resolution chip) must be hidden when empty; "Chua co clip" top-right chip duplicates the list's "0 clip" -> keep one.

### 7.3 Music page (`03`, `06`)
- Blue info callout at top (3 lines) is the first thing you read -> `callout` (4.15), one line + "Chi tiet" link.
- Two stacked tables (playlist, chapters) with different header styles and a 3-line grey helper paragraph between them -> same table component; chapters table gets its own card title with `chip` "61 luot phat"; helper text collapses to a "?" tooltip.
- Chapter timestamps are blue links (`#7aa2f7`-like) while elsewhere accent is violet -> `accent_text`, mono, right aligned.
- "Danh sach Bai nhac (Playlist)" title + count chip + toolbar: same layout as Video page (shared `ListToolbar`), same positions.
- Mixer panel (`mixer_panel.py`): sliders with consistent label column (96 px), value readout mono right aligned; "Nghe thu" is a `secondary` with play icon, not accent.

### 7.4 Export page (`04`, `07`)
- Form cards: labels have ragged widths and inputs start at different x per row ("Do phan giai", "Chat luong hinh anh", "Gioi han dung luong") -> fixed 160 px label column, fields align to one left edge across both cards ("Noi luu" card too).
- Estimate row: "Du doan dung luong  Dang do..." mixes sizes and baselines, then an orphan helper sentence and a centred "Tuy chon nang cao" link -> one row: label, value (`mono` `subtitle`), busy state static; "Tuy chon nang cao" is a left-aligned disclosure with chevron.
- Action zone (`07` bottom): 4 buttons of similar weight, two disabled, progress bar + status text crammed under; cut by the page bottom. -> Sticky footer bar (always visible, `panel`, top 1px `line`): left summary (resolution - fps - duration - audio, `text_2`), right: `Them vao hang doi` (secondary) + `Bat dau xuat video` (`primary` lg). Cancel/Open-folder appear only while running / after finishing (replace in place, no disabled clutter). Progress bar sits on top of the footer with % and ETA in `mono`.
- Queue and log: log in `field` well, `mono` `small`; queue is the shared list component with row-level status chip (waiting/running/done/failed) and per-row progress 4 px.
- Top border accent colour on every card removed (4.8).

### 7.5 Settings (`08`)
- Two uneven columns with different card heights; "Kiem tra lai phan cung" button floats at the title row -> single column max width 880, centred, 24 px padding, cards stacked; page title `title` + subtitle `text_muted`.
- Hardware table: label/values with irregular spacing; encoder availability uses stretched full-width pills of different widths (`CUDA 13.2` bar, `8.1.1-full_build` bar) -> definition-list rows (label 160 px, value left) and fixed-width chips grid (4.7); long ffmpeg path elided in the middle with copy button.
- "Giao dien hien thi" (font size, palette) is at the bottom of the right column, below the fold -> move to the top ("Giao dien"), with a live palette preview (4 round swatches, selected has ring) instead of a combo + tiny gradient swatch; label "Neon tim hong" -> "Tim neon".
- Checkbox + paragraph pairs: use the switch for immediate settings, helper text `text_muted` directly under the label (not wrapped to 3 lines at 400 px).
- Destructive "Xoa bo nho dem" is a red-bordered button inside a normal row -> `danger` ghost, right-aligned, with confirm dialog showing freed MB.

### 7.6 Help (`09`)
- Selected TOC item is a loud violet-pink gradient pill -> `accent_subtle` + left bar (same as nav); TOC section headers sentence case; search field `sm` height 32 aligned with the TOC.
- Content sits in a bordered box inside a page that already has padding -> remove the outer border, keep a reading column max 760 px, headings `title`/`subtitle`, `body` line-height 1.55; code/keys `mono` on `raised` with 1px `line` (keycaps).
- Header action buttons (Thu 3 tieng, Thu Loop 70 lan, Huong dan test bo mau, Thu muc nhat ky) are 4 different styles -> `secondary sm` ×3 + ghost link; callouts per 4.15; embedded screenshot gets 1px `line` + radius 8.

### 7.7 Home and Welcome (`01`, `00`)
- Home: 6 cards with 6 coloured borders (teal, amber, pink, blue, green) - the opposite of "one accent". -> neutral card borders, coloured icon tiles only; equal heights, 2 text levels (title `subtitle`, description `body` `text_2`; the "Vi du:" line becomes a muted `small` single line with ellipsis). Three primary kinds (Video co nhac / Chi video / Chi nhac) first row; tools (Tieng nen, Xuat hang loat, Mo du an) second row, visually quieter.
- Lower half of the page is empty -> add "Du an gan day" list (last 5 projects, thumbnail + name + date + duration; empty = sample projects "Thu: 3 tieng / Thu: Loop 70 lan" as cards). Move the "Cach lam chung" strip under the hero as a 3-step inline stepper; limit width to 720 px.
- Hero: "Ban muon lam gi hom nay?" - remove pink gradient on "hom nay?"; subtitle without the brand repetition ("KT Loop Station - By Khanh Tra" already in sidebar).
- Welcome overlay: flat `overlay` card with 1px `line`; step badges flat; "Mo du an mau (Loop 70 lan)" is a tiny secondary next to the primary - give it `secondary md`; paragraph at bottom-left to 2 lines max.

### 7.8 Cross-cutting labels / tooltips / microcopy
- Keep action verbs consistent: "Them file" / "Them thu muc", "Xoa" / "Xoa het" (-> "Xoa tat ca"), "Luu" / "Luu thanh..." (-> "Luu thanh ban sao...").
- Every icon-only control: tooltip "Action (Shortcut)". Truncated text: tooltip with the full text.
- Replace text glyph icons (`✓`, `✗`, `↻`, `→`, `①②③`) with SVG icons or plain words.
- Keep Vietnamese UI copy but avoid sentence-long labels inside buttons; helper sentences go under fields in `caption` `text_muted`, max 2 lines.
- Disabled controls get a tooltip saying why ("Can them clip truoc").

---

## 8. Top visual problems to fix first (ranked)

1. Gradient/glow everywhere (page radial glow, sidebar, header, cards, welcome card, TOC) - noisy, uneven, hurts text contrast.
2. Two-colour accent gradient on 5+ elements per screen; no clear single primary action.
3. Header bar overloaded: clipped project name, 5 control styles, gradient total pill.
4. Triple step navigation (sidebar, guide strip, header badges) and multi-line hint text.
5. Video/Music list toolbar: 12 controls, 5 styles, wrapped to two rows, always-visible red "Xoa het", near-invisible unchecked checkbox.
6. Cramped vertical space: fixed timeline dock + guide strip leave a ~6-row list and cut off the next card and tabs.
7. Low-contrast tiny text (`#646c80`, `#64708d`, `#525a70`, all-caps 8.5 pt tracked labels) and 8 font sizes / 3 weights without a scale.
8. Inconsistent radius (14 values), borders (accent top border on cards), and spacing (6/8/10/12/14 mix).
9. Table alignment: truncated names, centred vs right-aligned numerics, mixed header styles, alternating row colour in a different hue.
10. Player panel: tiny video floating in a tall black area, controls disconnected from the video; Export action area cut off and cluttered with disabled buttons.
11. Rainbow waveform in the timeline - loudest element on screen, competes with content.
12. Hard-coded styling: 247 hex literals (87 distinct), 14 inline stylesheets, ~140 QColor constants - palette switching only partially restyles painted widgets.
