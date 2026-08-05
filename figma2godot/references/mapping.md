# IR → Godot 4: the full mapping (the contract `ui_to_tscn.py` / `flow_binder.gd` implement)

> The zh-CN original is kept alongside as `mapping.zh.md`. English is the authority: land edits
> here first, then mirror. `tools/conformance` compares the two structurally (row counts and code
> blocks), so a one-sided edit goes red.

Input = figma2html's intermediate representation: `.ui.json` (the pixel snapshot, schema in
`../../figma2html/references/ui.json-schema.md`) plus `flow.json` (the interaction declaration, see
`../../figma2html/references/flow-events.md`). This table is the sole mapping authority for the backend.

## 1. Top level (cap → scene)

| IR | Godot | Notes |
|---|---|---|
| One `<stem>.ui.json` | One `<stem>.tscn` (text scene, `format=3`) | stem = the filename minus `.ui.json` |
| `w` / `h` | The root `Control`'s `offset_right` / `offset_bottom` | Root node name = stem (sanitised) |
| `stageBg` solid `rgba(...)` | A `StageBg` child (ColorRect, `mouse_filter = 2`) | First child, underneath everything |
| `stageBg` `url(path) ...` | `StageBg` (TextureRect + ext_resource, cover) | Asset placement in §6 |
| `stageBg` `linear-gradient(...)` | `StageBg` (TextureRect + GradientTexture2D) | A real gradient |
| `stageBg` radial or other gradient | `StageBg` (ColorRect, averaged colour) | known-loss (§7) |

## 2. Node naming

A tscn node name may not contain `. : @ / " %` — all of them **become `_`**: Figma id `1:40` → node
name `1_40`. `flow_binder.gd`'s `node_name()` applies the same rule, so flow.json keeps the raw
Figma ids. A sanitised collision among siblings (very rare) gets a trailing `_`. Reserved names:
`StageBg`, `Backdrop`, `CheckMark`, `modal_*`.

## 3. Geometry and hierarchy (following render.js pass2)

| IR | Godot | Notes |
|---|---|---|
| `x,y,w,h` (absolute px within the frame) | anchors all 0 (top-left, not written out by default) + `offset_left/top = (x,y) − parent(x,y)`, `offset_right/bottom = left/top + (w,h)` | Same algorithm as render.js's "absolute geometry → parent-relative" |
| `parent` | The mount path in the node tree (`parent="."` / `parent="1_10"` / nested `a/b`) | A parent id not present in this screen (subtree extraction) becomes a root |
| `z` | **Sibling tree order** (children sorted by `(z, original order)`) | A Godot Control's draw order is its tree order. `z_index` is deliberately not written (it accumulates across layers, which is different semantics). Global z interleaving across parents is known-loss (§7) |
| `rot` (degrees) | `rotation` (**radians**) + `pivot_offset = Vector2(w/2, h/2)` | Godot rotates about the top-left by default; the centre pivot is what makes it match CSS `transform-origin: center` |
| `opacity` | `modulate = Color(1, 1, 1, a)` | modulate propagates downward, like CSS opacity affecting the subtree. Do not use self_modulate |

## 4. Box styling (RECTANGLE/FRAME/… → Panel + StyleBoxFlat)

Any of `fill`/`border`/`shadow` present → `Panel` + `theme_override_styles/panel = StyleBoxFlat`;
a pure container with none of them → `Control` (an empty Panel paints the theme's default grey skin,
which has to be avoided).

| IR (CSS-flavoured string) | StyleBoxFlat | Notes |
|---|---|---|
| `fill: rgba(r,g,b,a)` | `bg_color` | 0-255 → 0-1, four decimals |
| `fill` empty but a border or shadow present | `bg_color = Color(0,0,0,0)` + `draw_center = false` | Draws only the edge or shadow |
| `radius: "45px"` / `"a b c d"` (CSS 1/2/3/4-value shorthand) | `corner_radius_top_left/top_right/bottom_right/bottom_left` (four independent corners) | CSS order TL TR BR BL |
| `radius: "50%"` (capture emits it for **every ELLIPSE**) | square → `corner_radius` on a StyleBoxFlat; **non-square solid fill → a compile-time `.svg` with true elliptical corners** (`radius_axes` + `rounded_rect_d`), imported as a texture | Godot's `corner_radius` is a *scalar* and cannot draw an elliptical corner, so the scalar reading turned a 2143×680 ellipse into a capsule whose top arc sat **38px flatter** than HTML — the yellow band under the mail panel ended at y=1176 instead of y=1214. Rather than keep that as a known-loss, these elements now take the same route v1.2 vectors already take: emit an `.svg` and let ThorVG rasterise it. Deterministic, no bitmap downloaded, and the alignment target is **CSS** (horizontal radii against width, vertical against height, then the §5.5 proportional shrink) — not the other backends' workaround. What still falls back to the capsule: elements that also carry a **gradient, image, border, shadow or clip**, because those need the StyleBoxFlat/texture routes; they are logged per element. This row was once **dropped entirely** because `float('50%')` raised — ellipses rendered as squares, with no warning — and is now held by tools/conformance |
| `border: "2.0px solid rgba(...)"` | `border_width_left/top/right/bottom` + `border_color` | Width rounded, minimum 1. Godot draws borders inward, the same semantics as CSS `box-sizing: border-box` |
| `shadow: "ox oy blur [spread] rgba(...)"` | `shadow_color` + `shadow_offset = Vector2(ox, oy)` + `shadow_size` | **Godot supports this natively; do not drop it.** `shadow_size ≈ blur + spread`, minimum 1 (at size=0 Godot draws nothing, which would make a CSS zero-blur hard shadow vanish, hence the floor) |
| `fill: linear-gradient(angle, stops…)` | The node becomes a `TextureRect` + `GradientTexture2D` (`Gradient` holds offsets/colors; angle → `fill_from/fill_to` UV, with CSS 0deg=up and 90deg=right) | A real gradient; stops without positions are interpolated by the CSS rules |
| `fill: radial-/conic-gradient(...)` | `Panel` + the **averaged** stop colour | known-loss (§7) |

## 5. Text (TEXT → Label)

| IR `text.*` | Godot Label | Notes |
|---|---|---|
| `content` | `text = "..."` (escaping `\\` `\"` `\n` `\t`) | When it contains `\n`, also sets `autowrap_mode = 3` (WORD_SMART, matching pre-wrap); leaving it unset on a single line matches nowrap |
| `alignH` / `alignV` (flex values) | `horizontal_alignment` / `vertical_alignment` (`flex-start→0 center→1 flex-end→2`) | With alignH absent, falls back to textAlign |
| `color` | `theme_override_colors/font_color` | |
| `size` | `theme_override_font_sizes/font_size` (int) | |
| `lh` (line height px) | `theme_override_constants/line_spacing = lh − size` | Written only when lh>0; may be negative |
| `stroke` ("wpx rgba(...)") | `font_outline_color` + `outline_size = round(w × 5/3)` | `-webkit-text-stroke` straddles the glyph outline and `paint-order: stroke` leaves the **outer half** visible, so the target is w/2 px of visible outline. But Godot's `outline_size` is **not visible pixels** — measured on this font: `outline_size` 6 → 0.63, 12 → 1.22, 18 → 1.74, 20 → 1.83 (outline ink ÷ glyph ink on the bottom tabs), against the HTML reference's 1.90, i.e. ~0.3px shows per unit. The factor is therefore a **measured calibration**, not a unit conversion; `round(w/2)` (what this row used to say) draws an outline you can barely see |
| `weight` / `family` / `ls` | **not written** | Only meaningful with a font resource; see §6 fonts and the §7 known-loss table |

## 6. Images, assets, fonts

| IR | Godot | Notes |
|---|---|---|
| `img` (project-relative path, named by imageRef so it is reused across screens) | `TextureRect` + `[ext_resource type="Texture2D" path="res://<img>"]` | **Asset placement**: copy figma2html's exported `_assets/` directory into the Godot project root verbatim (keeping every path segment), and `res://` + the IR path resolves. Multiple references to the same imageRef share one ext_resource |
| `imgSize: cover` (or empty) | `expand_mode = 1` + `stretch_mode = 6` (KEEP_ASPECT_COVERED) | Fills proportionally and crops |
| `imgSize: contain` | `expand_mode = 1` + `stretch_mode = 5` (KEEP_ASPECT_CENTERED) | Fits proportionally and centres |
| Any other imgSize | `stretch_mode = 0` (SCALE) | Stretch fallback |
| `vec: true` with no PNG | No fill → `Control` (transparent placeholder) | Matches render.js: a missing image falls back to transparent, never a black fill |
| Fonts | Project-level configuration: attach a CJK font (e.g. Source Han Sans) in the Godot theme (or `theme_override_fonts/font`), with Regular/Medium/Bold cuts to serve `weight` | The converter emits no font resources. The woff2 that figma2html's `subset_font.py` produces is not directly usable by Godot; use ttf/otf |

## 7. Known-loss table (what conversion drops or approximates — read before accepting)

| IR feature | Handling | What is lost |
|---|---|---|
| `blur` (filter blur) | **dropped** | Control has no per-node filter. If you truly need it, add a BackBufferCopy/shader in-engine — a manual post-process |
| `clip` (v1.1) | `clip_contents` without a radius, **`clip_children`** with one | Two mechanisms, and picking the wrong one is a bug rather than a rounding error. `clip_contents` is a *rectangular scissor* — it ignores `corner_radius`. Figma's common idiom is "a rounded clipping container with something bleeding out of it", and `clip_contents` renders that with square corners: an item card's quality gradient came out a red square, and a 275×170 texture inside a 41px-radius pill spilled a rectangular block of dots out of the left end. `clip_children` masks children by **the shape the node itself draws**, so such a container is emitted as a Panel carrying a rounded StyleBoxFlat (opaque — an empty mask would clip everything away) plus `clip_children = 1`, or `2` when it also has its own fill to draw. **`clip_children` cannot nest** — one per ancestor chain — so when rounded clips nest, the **outermost** one gets it and the inner ones degrade to a rectangular `clip_contents` (logged). That order matters: the outer clip is the silhouette read against the background (losing it squared off an 80px-radius panel's bottom corners), while inner clips sit inside an already-opaque parent, where a rectangular scissor only leaves a little same-coloured square in the corner |
| `paths` + `viewBox` (v1.2) | a sibling `.svg` beside the scene, referenced as a `Texture2D` | Godot has no SVG-path node but it does have an SVG importer (ThorVG), which already handles winding rules, holes and multiple subpaths — so geometry is written out as a real `.svg` rather than triangulated by hand or fetched as a bitmap. ThorVG parses SVG 1.1, where `fill="rgba(...)"` is CSS Color 4 and silently renders **black**, so fills are emitted as `#rrggbb` + `fill-opacity` |
| `borderAlign` (v1.2) | `border_width_*` + `expand_margin_*` | Godot's border, like CSS's, only draws inward. The outward half arrives at the head of `shadow` as a `0 0 0 Npx` ring; it is split back out and expressed as an equal `expand_margin`, which grows the StyleBox outward so the stroke sits outside the box instead of eating into the fill |
| `radial-/conic-gradient` | Averaged colour fallback | Not covered by StyleBoxFlat or by GradientTexture2D as used in this pipeline. GradientTexture2D does have a radial fill, but its centre/radius semantics do not line up with CSS, so an explicit degradation is preferred |
| `linear-gradient` together with radius / border / shadow | Gradient preserved; radius, border and shadow **dropped** | Once the node becomes a TextureRect there is no StyleBox. If you need both, wrap it manually in a Panel parent and clip |
| `text.ls` (letter spacing) | dropped | Needs FontVariation `spacing_glyph`, which depends on a font resource |
| `text.weight` / `family` | not written | See §6 fonts; without a theme it renders in the engine default font |
| `text.stroke` width | `outline_size = round(w × 5/3)`, calibrated by measurement | Godot's constant is not visible pixels; the factor was fitted against the HTML reference and is font-dependent in principle |
| CSS hard shadow with `blur=0` | **a solid copy panel underneath**, not `shadow_size` | `shadow_size` means "how many pixels to spread outward", while `0px 6px 0px` means "copy the whole shape, offset, filled with the shadow colour". Routed through `shadow_size` it gets clamped to `max(1, blur+spread)` = 1 and the design's chunky drop shadow collapses into a 1px rim. A Panel with the same corner radii is emitted **before** the node itself (earlier sibling = drawn below). Blurred shadows still use the native `shadow_size` — that is what it can actually express |
| `shadow` on a TEXT or img element | dropped | box-shadow is not a font shadow; a Label only has a font shadow, and the semantics differ too much to fake |
| Global `z` interleaving across parents | Approximated by sibling ordering | Correct within siblings; cross-parent interleaving (rare) is flattened |
| List scrolling (overflow-y auto) | `clip_contents = true` clips without scrolling | To scroll, wrap the container in a ScrollContainer by hand |
| `rot` on a node inside a component instance | Already lost upstream (capture falls back to 0) | A Figma REST limitation, see figma2html's "known limitation: rotation"; work around it in the hook |
| `flow.events[].transition` | Baked into `motion.json` sample points, **and played** | See "Transition easing" below |

### Transition easing (motion.json)

Pass `flow.json` as `ui_to_tscn.py`'s third argument and it emits one extra file into outdir,
`motion.json`: per event carrying a transition, a **17-point evenly spaced sampled curve** (x and y
are both 0..1 progress).

**Why sample points rather than a `Tween.EASE_*` enum.** Figma hands over a specific curve
(`cubic-bezier(.32,.72,0,1)`, or a spring's three parameters); `Tween.EASE_OUT` is a **different
curve sharing the name**. Picking "the closest enum" means every backend picks its own — one IR
becomes six different feels across six engines while every test stays green. For scale: easeOutCubic
differs from `cubic-bezier(.23,1,.32,1)` by up to **19.8 percentage points**, and the worst of it is
in the opening moments. Sample points have no such freedom, and `tools/conformance` compares them
against unity **one by one**.

Usage: build a `Curve` resource with `add_point(Vector2(x, y))` per point, then `tween_method`
interpolating through `curve.sample(t)`.

**Wiring**: `flow_binder.gd`'s `motion_path` (default `res://motion.json`). File absent = everything
shows and hides instantly, a **declared degradation**, not a silent loss. Present and it takes
effect automatically: modal entrance / **exit** · press · list stagger · guard shake.

**Verified in Godot 4.3-stable, 2026-07-29**: 6 curves read as `Curve` (17 points each), and
`sample(0.3)` agrees with the Python solver *and* the Unity side — three-way, **to six decimal
places**. Transitions genuinely play (mid-`MOVE_IN`: `alpha=0.509 / offsetY=942.5` → final
`1.000 / 0.0`; after the exit, `visible=false`).

⚠️ **Translation and scale go on `modals[*].panel` only; the backdrop merely fades.** Transform used
to be applied to the modal **layer**, and Backdrop is a child of that layer — so the backdrop slid
and scaled along with the panel: the top never dimmed, and the edges pulled in to reveal the base
screen. **Every curve value was correct; only a screenshot from the running engine caught it.** html
and unity had the same shape of bug and were fixed together. A modal with no declared `panel` only
fades — it does not guess which node should move.

⚠️ Directional transitions travel **the stage's** dimension, not the panel's own box (see
`spec/flow-events.md`). `layer.size` is what the multiplication uses; html once used a CSS
percentage, which is relative to the element, and started an 860×1160 panel 1160px away where the
engines started it 1920px away. Curve values are identical either way, so `tools/conformance` pins
the basis directly.

⚠️ **Use `sample()` and set the tangents to `TANGENT_LINEAR`.** `sample_baked()` quantises to
`bake_resolution` (100 by default) and lands ~1.4e-3 away from the others; the default tangent (0)
flattens both ends of every segment. Matching sample points **only guarantees agreement at the
keyframes** — with different interpolation between them, every engine still computes its own thing.
`tools/conformance` guards this at source level.

| Handling | Note |
|---|---|
| **known-loss: named spring presets** | Figma publishes no control points for `GENTLE/QUICK/BOUNCY/SLOW` or `*_BACK` → marked `unresolved` and not sampled. **No invented numbers** (numbers that are "about right" produce an artifact that looks normal and feels wrong) |
| **approx: spring truncated by duration** | Figma's springs carry a duration, and a spring has no fixed length; a window shorter than its settling time cuts it off, and the generator stamps `truncated:` |
| **known-loss: `SMART_ANIMATE`** | Auto-matching same-named layers has no cross-engine equivalent; the curve is sampled, **the pairing logic is not implemented** |

## 8. Coordinate system and scaling

- The generated scene is a **fixed-pixel stage** (root Control = `w×h`, e.g. 1080×1920) with
  everything absolutely positioned inside; it **does not participate** in Godot's layout containers
  (HBox and friends) — the same semantics as render.js's absolute DOM.
- To fit the whole scene to the window: project settings `display/window/size/viewport_width/height =
  the frame size`, `stretch/mode = canvas_items`, `stretch/aspect = keep` — the equivalent of
  figma2html's `mountStage` proportional scaling. To embed it inside another scene as a sub-UI, wrap
  it in a `SubViewport` or set `scale` on the root Control.
- Pivot: every rotated node already carries `pivot_offset = size/2` (centre), so a scale animation
  about the centre works directly too.
- `flow_binder.gd` as the stage root: `binder.size = flow.stage`, with the base screen scene and
  every modal layer mounted beneath it.

## 9. flow.json → runtime (flow_binder.gd, semantics aligned with assemble.js)

| flow field | Godot behaviour |
|---|---|
| `caps` | `.ui.json` path → the `.tscn` of the same stem (loaded from `scene_dir`) |
| `base` | The base screen scene stays instantiated (including its own StageBg) |
| `modals[*].roots/panel` | That screen's scene is instantiated and then **pruned by roots** (only the roots subtrees survive at the top level; StageBg and the rest are freed), with a `Backdrop` (translucent ColorRect) overlaid. `panel` drives the `get_global_rect` test for `@panelOutside`. Whole-scene-instantiate-and-prune beats show/hide because the top-level children's geometry is already frame-absolute px — prune and it lines up — and SubResource references stay intact |
| `events[]` | `gui_input` bound by node name (the bound element gets `MOUSE_FILTER_STOP` + `accept_event()`, ≈ stopPropagation). `@any:` / `@panelOutside:` bind on the modal layer, with all modal content set to `MOUSE_FILTER_PASS` so clicks bubble (imitating DOM bubbling). `guard` → every state key must be truthy to pass (failure calls back into `onGuardFail`) |
| `@in:<modal>:<nodeId>` (v1.1) | `find_el` inside the modal layer; that node goes from `_pass_through`'s `MOUSE_FILTER_PASS` back to `STOP` to receive the click, and `accept_event()` blocks the bubble |
| `list` | `render_rows()`: `duplicate()` the container's first row as the template, derive the step from the second row's offset delta, fill each item through the callback plus `set_meta("item")`, and dispatch row clicks to the `onRowClick` action |
| `bindings.checkbox` | Handled generically by the engine: change the Panel's StyleBoxFlat `bg_color` and fill a dynamic `CheckMark` Label with the `mark` character |
| Any other `do` name / domain write-back | The action dictionary the app hook registers (`app_hook.example.gd`); the engine hard-codes none of it |

## 10. Robustness

`flow.json` that fails to parse produces one `push_error` and a clean return — `JSON.parse_string`
returns null rather than throwing, and the result is checked. This is the repo-wide rule (malformed
IR gets a sentence, not a traceback) and `tools/conformance` checks all four runtimes for it.
