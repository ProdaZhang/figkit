# IR → Cocos Creator 3.x: the mapping (figma2cocos)

## IR v1.5 compatibility

`matrix`, `vectorShadows`, `text.decoration`, `text.runs`: **known-loss / drop**.
This backend reports these fields and keeps legacy x/y/rot/shadow/plain-text rendering.
HTML supports them; engine rendering has not been implemented or pixel-validated.
Reflections, rich text and vector-silhouette shadows are not faithfully rendered here yet.
Capture expands repeats into regular records; transformed repeats still require matrix support.
Capture `losses` lists known degradations, not a completeness certificate; use capture --strict as a gate.

> The zh-CN original is kept alongside as `mapping.zh.md`. English is the authority: land edits
> here first, then mirror. `tools/conformance` compares the two structurally (row counts and code
> blocks), so a one-sided edit goes red.

Input IR = the figma2html pipeline's `.ui.json` (pixels) + `flow.json` (interaction); field
semantics live in `../../figma2html/references/ui.json-schema.md` and `flow-events.md`. This table
is the implementation contract for `runtime/*.ts`.

> **Delivery statement (updated 2026-07-31): the TS under runtime has passed a strict type gate**
> (tsc `--noEmit` against the official `@cocos/creator-types` **3.8.3** engine declarations, zero
> errors) **but has not been run inside Cocos Creator.** **You can run that gate yourself**:
> `cd tools/cocos-typecheck && npm ci && python3 check.py` — until then it existed only on the
> author's machine (no tsconfig, no package.json in the repo, and CI did not run it), and a claim
> nobody can reproduce is not distinguishable from a false one. What ships = the source plus this
> integration guide; the logic is aligned with figma2html's render.js / assemble.js (the reference
> implementation that has actually been run), and the cc API usage rests on review plus type
> self-consistency. For a first integration, work through the §6 smoke checklist.

## 1. Element mapping

| IR field | Where it lands in Creator | Notes |
|---|---|---|
| `el` (each) | `Node` + `UITransform` | Node name takes `el.name \|\| el.id`; the raw IR hangs on `node.__figEl` for lookup |
| `x,y,w,h` | `UITransform.contentSize` + `position` | Coordinate conversion in §2 |
| `z` | Sibling order | els are stably sorted by ascending z and then `addChild`ed in turn → append order under the same parent is draw order (equivalent to `setSiblingIndex`) |
| `parent` | Node tree parent/child | Empty = mounted on the layer root; `buildSubtree` clears the root's parent when lifting a subtree (matching `subtreeOf`) |
| `rot` | `node.angle = -rot` | CSS is positive clockwise, Creator positive counter-clockwise → negate; rotation pivot in §3 |
| `opacity` | `UIOpacity` for Sprite/Label, **multiplied into the colour** for Graphics | `UIOpacity` does **not** affect Graphics at all — not on the node itself, not cascaded from an ancestor (Graphics owns its model and never enters the UI batcher's vertex colour). Measured in-engine: a `fillColor` alpha of 51 reads back as 110 over a #333 backdrop, while both `UIOpacity = 51` spellings read pure 255. So Graphics colours get the **whole ancestor chain's** opacity folded in; leaving it out painted a `opacity: 0.38` white decoration as opaque white and smeared the entire title bar |
| `fill` (solid) | `Graphics.fillColor` + `roundRect` + `fill()` | rgba → `Color(r,g,b,a×255)` |
| `fill` (linear-gradient) | A **runtime-baked texture** on a Sprite inside a rounded Mask | Graphics has no gradient fill, so a 64² texture is generated with every texel projected onto that element's real gradient axis (any angle), then shown through a `GRAPHICS_STENCIL` Mask so the corners still round. **The texture must be uploaded via `Texture2D.reset` + `uploadData`** — building an `ImageAsset` from `_data` and assigning `tex.image` takes the image-element upload path and throws `texSubImage2D … Overload resolution failed` on every frame (4686 of them in one screen) |
| `radius` | Per-corner path (line + cubic Bézier) | Each corner keeps its own radius, so `73px 73px 0 0` renders as it should; radii are clamped by the CSS rule (adjacent pair ≤ edge) first. **Do not use `Graphics.arc` here** — see the pitfall note under §5 |
| `border` | `Graphics.lineWidth/strokeColor` + `stroke()` | CSS strokes inward (border-box) while Graphics centres on the path → the path is **inset by width/2** to approximate it |
| `shadow` | A sibling **underlay** node: hard ones are drawn with `Graphics`, **blurred** ones get a texture baked at load time (`softShadowFrame`) and shown through a `Sprite` | Creator has no `box-shadow` and no per-node blur, but "another node underneath" expresses both. The blur is a rounded-rect coverage mask run through **three box passes ≈ Gaussian at σ = blur/2** (CSS's own definition), on a canvas inflated by 3σ. Same route this backend already used for gradients — `Texture2D.reset` + `uploadData`, and `sprite.trim = false`, because Creator trims transparent borders and a shadow is nearly all transparent border |
| `blur` | **not rendered** (known-loss) | Same (a full-screen post-process does not suit per-node use) |
| `img` | `Sprite` (`SizeMode.CUSTOM`) | `resources.load(assetRoot + stem(img) + '/spriteFrame', SpriteFrame)`; missing → transparent fallback plus a warning (never a filled placeholder, matching render.js) |
| `imgSize` (cover/contain) | **always stretched to fill** (known-loss) | `SizeMode.CUSTOM` fills contentSize; capture's images are mostly 1:1 exports, so distortion is limited |
| `vec: true` with no image | Transparent fallback | Same semantics as a missing `img` |
| `text.content` | `Label.string` | |
| `text.size / color` | `fontSize` / `color` | |
| `text.lh` | `lineHeight` (`lh>0 ? lh : round(size×1.2)`) | render.js's `normal` ≈ 1.2 |
| `text.alignH / alignV` | `horizontalAlign / verticalAlign` | flex-start/center/flex-end → LEFT·TOP/CENTER/RIGHT·BOTTOM; when `textAlign` and `alignH` disagree, alignH wins (a Label has only one alignment, known-loss) |
| `text.weight` | `isBold = weight ≥ 600` | No 500/800 gradations (known-loss) |
| `text.family` | System default font | The family is not reproduced (known-loss); reproducing it needs a TTFFont asset plus a hook override |
| `text.stroke` | `LabelOutline`, **width halved** | The IR width is CSS `-webkit-text-stroke`: it straddles the glyph outline, so only the outer half shows. `LabelOutline` grows outward, so copying the number whole draws it twice as thick — measured 3.00 outline-ink ÷ glyph-ink against HTML's 1.90, with the letter gaps filled solid. Halved it lands at 1.79 |
| `text.ls` (letterSpacing) | **not rendered** (known-loss) | Label 3.x has no letter-spacing property |
| Text overflow | `Overflow.CLAMP` + `enableWrapText` from `text.wrap` | Follows the IR instead of forcing nowrap (a fixed-width body used to run off its panel on one line); a wider system font may still clip (known-loss) |
| `cap.stageBg` | A `stage-bg` child (Sprite or Graphics) | `url(..)` → Sprite; solid or gradient → Graphics (gradient takes the first colour); sibling 0, underneath |

flow.json mapping (`flow-binder.ts`, semantics aligned with assemble.js):

| flow field | Where it lands in Creator |
|---|---|
| `base` | A permanent `layer-base` node, built full-screen by `FigmaUI.buildEls` |
| `modals[*]` | One hidden layer per modal: a translucent black backdrop (Graphics `rgba(0,0,0,0.5)` over the whole stage) plus `FigmaUI.buildSubtree(cap, roots)`; `openModal` shows them mutually exclusively |
| `events[].on:"click"` | `Node.EventType.TOUCH_END`; element-level listeners set `propagationStopped=true` (matching stopPropagation) |
| `events[].el` (id) | The base screen's id→Node index (matching `baseEl`) |
| `@any:<modal>` | TOUCH_END on the layer node (touches no child intercepted bubble up to the layer) |
| `@in:<modal>:<nodeId>` (v1.1) | Looks the node up by id inside the modal layer (through the `maps` index) plus `propagationStopped`; without stopping the bubble, the layer's `@any`/`@panelOutside` would fire as well |
| `@panelOutside:<modal>` | Layer TOUCH_END plus the inverse of `panel.UITransform.getBoundingBoxToWorld().contains(point)` |
| `guard` | Every state key must be truthy to pass (null/undefined/false/0/'' are all falsy); failure calls back into `onGuardFail` |
| `openModal/closeModal/toggleFlag/send` | Built in; any other `do` name looks up an action the hook registered |
| `list` | The container's first row is cached as the template (row spacing = the y delta of the first two rows, or the row height when there is only one) → `instantiate` to clone, `rowFn` to fill, and each row binds TOUCH_END → `onRowClick` |
| `bindings.checkbox` | `paintRect` repaints the two-state background, and a `check-mark` child Label is shown or hidden |

## 2. Coordinate conversion (the core — understand it before touching anything)

IR: y points down, the origin is the frame's top-left, and geometry is **absolute px within the
frame**. Creator: y points up, and position is **the child's anchor relative to the parent's anchor**.

**Convention: every node gets `UITransform.setAnchorPoint(0,1)` (top-left anchor)** → a node's
anchor is its own top-left corner, so:

```
child.position = ( childAbsX - parentAbsX,  -(childAbsY - parentAbsY) )
```

The general form (any anchor; needed for rotated nodes): with child anchor `(ax,ay)`, parent anchor
`(pax,pay)`, and `dx/dy` the IR absolute-coordinate delta:

```
pos.x = (-pax·pw) + dx + ax·cw          // parent anchor→parent top-left + delta + child top-left→child anchor
pos.y = ((1-pay)·ph) - dy - (1-ay)·ch
```

Substituting anchor (0,1) collapses it to the convention above. **The mount root (the FigmaUI
component node, or FlowBinder's layer node) must be anchored (0,1)**; the code sets this automatically.

**Worked example** (fixture `screen-login.ui.json`): parent `1:10` server-pill is absolute
(260,1280) 560×90; child `1:12` gem is absolute (286,1302) 46×46. dx=286−260=26, dy=1302−1280=22 →
`child.position = (26, -22)`: anchored 26px right and 22px down from the parent's top-left — exactly
CSS `left:26px; top:22px`. ✓ At root level `1:10` (parent=''): position = (260, −1280), i.e. 260
right and 1280 down from the root container's top-left. ✓

- Root container: `contentSize = (cap.w, cap.h)`, anchor (0,1), **placed at the screen's top-left** —
  add a `Widget` to the component node (Left=0, Top=0 against the Canvas), see §4.

## 3. Rotation (rot)

- Direction: CSS `rotate(θdeg)` is positive clockwise; Creator's `node.angle` is positive
  counter-clockwise → **`angle = -rot`**.
- Pivot: CSS uses `transform-origin: center`; Creator rotates about the **anchor**. A rotated node
  left on anchor (0,1) would turn about its top-left and drift.
  Implementation: **nodes with rot≠0 switch to anchor (0.5,0.5)**, with position compensated by the
  §2 general form (`+cw/2, -ch/2`), which makes the pivot match CSS. Their children convert through
  the same form for the parent anchor offset, so the geometry stays correct.
- Figma REST often omits `relativeTransform` for nodes inside component instances → `rot` falls back
  to 0. This is an **upstream capture limitation** (see figma2html's `references/ui.json-schema.md`)
  and Cocos inherits it; nodes that need an angle go through a hook overriding `node.angle`.

## 4. Canvas and screen-fit

- **designResolution = cap.w × cap.h** (e.g. 1080×1920). Fit policy: portrait UI generally wants
  **Fit Width** (SHOW_ALL leaves bars on both sides; judge per product).
- Suggested scene structure:

```
Canvas (cc.Canvas, designResolution = cap.w × cap.h)
└─ FigmaRoot (UITransform anchor (0,1) + Widget: AlignTop=0, AlignLeft=0)
   ├─ FigmaUI component (single-screen preview)   ← pick one
   └─ FlowBinder component (the whole flow: base screen + modals + events)
```

- The Widget pins the root to the Canvas's top-left; cropping or letterboxing beyond
  designResolution is handled uniformly by the Canvas policy, and the IR's internal geometry takes
  no part in fitting (it is pixel-positioned).

## 5. known-loss summary

| Item | Loss | Workaround |
|---|---|---|
| `blur` | Not rendered | Use a pre-baked texture or a post-process, in the hook layer |
| Gradients that will not parse | Takes the first stop as a solid | Only radial / non-`<angle>deg` forms land here; linear ones are baked |
| Font family / exact weight | System font + `isBold(≥600)` | Attach a TTFFont asset and override `label.font` in the hook |
| `letterSpacing` | Not rendered | — |
| `textAlign` vs `alignH` conflict | alignH wins | For rich multi-line alignment, rework it with RichText |
| `imgSize` cover/contain | Always stretched to fill | Capture's images are mostly 1:1 exports, so it is usually imperceptible |
| Text clipped by CLAMP | A wider system font may clip | Reduce fontSize, or widen contentSize in the hook |
| `rot=0` inside instances | An upstream API limitation | Set `node.angle` by hand in the hook |
| `unresolved` curves in `motion.json` | That transition shows/hides instantly | Figma publishes no control points for `BOUNCY` / `*_BACK`; do not invent numbers, see below |

### Pitfall: Graphics cannot punch holes — winding order means nothing to it

There is no `fill-rule` API here, but the real problem sits one layer below "no API":
**Graphics' tessellator does not look at winding order at all**. The engine's `_expandFill` loops
over contours and calls `Earcut(earcutData, null, 3)` once per contour — that second argument is
`holeIndices`, and it is always `null`. So the trick that works on canvas and in SVG — reverse the
inner contour so the windings cancel — is a **no-op** here: both contours fill solid, and the inner
one simply covers the outer.

The cost is visible. Since v1.3 capture splits Figma's stroke band into a **ring** (outer contour +
inner contour + `evenodd`), and the three pills in the bottom bar are exactly that shape — so each
pill came out filled with its *stroke* colour: the black pills went grey, the green one went a
washed-out mint, while HTML, Godot and Unity were all correct. It was worth 5.41/255 of the
four-way pixel comparison.

The fix punches the hole with a **stencil** instead of with winding: when a path has contours fully
enclosed by another (and `rule` is `evenodd`), it gets one extra layer — the outer node carries a
`Mask` (`GRAPHICS_STENCIL`, `inverted = true`) whose stencil draws exactly those hole contours, and
the fill is drawn on its child. `inverted` means "draw everywhere except the stencil", which is
precisely a hole. Paths without holes do not get the extra layer: 3 of the 97 paths across the four
screens need one, and a minority case should not cost everyone a node. Cocos went 5.41 →
**3.86/255**, the bottom-bar strip alone 3.60.

**`rule` has to be honoured.** In a nonzero path the winding *is* the data — the cut-out fold lines
on the envelope and the 48-segment stroke geometry both depend on it — so treating every enclosed
contour as a hole would destroy it. Only `evenodd` is inspected.

### Pitfall: `Graphics.arc` is not canvas's `arc`

Rounded corners here are cubic Béziers, not arcs, and that is deliberate. The engine's
`arc(cx, cy, r, a0, a1, ccw)` differs from the canvas API in two ways, each of which corrupts the
shape on its own:

1. Its first point is emitted as `ctx.moveTo(x, y)` — an arc **always starts a new sub-path**
   instead of continuing from the current point. "Straight edge `lineTo` + four corner `arc`s"
   therefore produces four disjoint sub-paths, and `fill()` merges them into one polygon: every
   rounded box came out shredded into diagonal wedges.
2. The sweep direction is inverted. With `counterclockwise=false` it runs `while (da > 0) da -= 2π`,
   so a canvas-style `(-90° → 0°, false)` is read as **-270°** and takes the long way round — drawn
   as giant loops across the screen.

`bezierCurveTo` continues from the current point and has no direction ambiguity, so it sidesteps
both. `scripts/tests/test_runtime_source.py::test_corners_never_use_graphics_arc` keeps it that way.
This one, like the Babel constraint, passes every static gate and only shows up on real pixels.

## 5.5 Transition easing (`flow.events[].transition` + `flow.motion`)

> History: this section used to read "one block of known-loss — the runtime ignores transitions
> entirely". Implemented 2026-07-29.

### Curves are solved in Python; TS only interpolates

```
flow.json ──► scripts/bake_motion.py ──► motion.json (17 sample points per curve)
                    │ (= scripts/motion.py, a byte-identical mirror of figma2html's master)
                    ▼
              FlowBinder.motionAsset(JsonAsset) ──► linear interpolation ──► applied to the node
```

**Why not let TS solve it.** Figma hands over a specific curve (`cubic-bezier(.32,.72,0,1)`) or a
set of spring parameters; Creator's `easing.quadOut` and friends are a **different family sharing
the names**. Letting every engine pick "the closest built-in easing" turns one IR into six different
feels across six engines while every test stays green (measured: easeOutCubic differs from
`cubic-bezier(.23,1,.32,1)` by up to **19.8 percentage points**, and the worst of it is in the
opening moments). So even though cocos has no converter to hang the baking off, it **ships its own
baking CLI**, and its output goes into `tools/conformance` for point-by-point comparison against
godot / unity.

⚠️ **Interpolation between frames must be linear**: matching sample points only guarantees agreement
**at the keyframes**. Godot's default tangents flatten both ends of each segment and Unity's default
smooth tangents bow inside them — both have been caught by this. `sampleCurve()` is therefore an
explicit linear interpolation.

### Mapping

| Declaration | Where it lands in Creator |
|---|---|
| `events[].transition.type` = `DISSOLVE` / unknown | Fade only (the layer's `UIOpacity`) |
| = `SCALE_IN` / `SCALE_OUT` | The panel's `setScale`, `fromScale`→1 (reversed on exit); **about the centre**, see below |
| = `MOVE_IN` / `SLIDE_IN` / `MOVE_OUT` / `SLIDE_OUT` | The panel's `setPosition`, sliding in from a full edge of the **layer** per `direction` (cocos y points up, so `BOTTOM` is negative) |
| `duration` | Seconds = ms/1000; `schedule(step, 0)` advances per frame and normalises `elapsed/dur` |
| `motion.press` | Clickable elements scale to `scale` on `TOUCH_START` and reset on `TOUCH_END`/`TOUCH_CANCEL` |
| `motion.stagger` | `renderRows` fades each row in after `scheduleOnce(index × step)` and slides it up by `from` px |
| `motion.guardFail` | On refusal, shakes the last pressed element (`sin` phase × decay; one-shot, not reusing the transition curve) |
| `unresolved` curve (no sample points) | Skipped = that transition is instant; control points are not guessed |
| `motionAsset` not set | Everything shows and hides instantly — a declared degradation, not a silent loss |

**Two cocos-specific traps**:

1. **Scaling has to compensate the position to stay centred.** The anchor is (0,1) (§2), so
   `node.setScale` works from the **top-left**, and setting scale directly makes the panel collapse
   toward the bottom-right. Compensation: `position += (w(1−s)/2, −h(1−s)/2)` (`scaleAboutCenter()`).
2. **Translation and scale go on the panel itself; the backdrop merely fades.** The backdrop is a
   child of the modal layer — put the transform on the **layer** and the backdrop slides and scales
   with the panel: the top never dims and the edges pull in to reveal the base screen. html, godot
   and unity all had the same shape of bug, **every curve value was correct**, and it took a
   screenshot from Godot running for real to catch it. With no `flow.modals[*].panel` declared it
   only fades — it does not guess what should move.

Directional transitions travel **the stage's** dimension (the layer's size), not the panel's own box
— see `spec/flow-events.md`. `tools/conformance` pins all four backends to that basis, because the
curve values are identical either way and only the distance differs.

### Verification level (honest)

- ✅ Sample points agree with godot / unity **point by point** (`tools/conformance`,
  béziers and springs alike).
- ✅ Strict TS type gate (tsc `--noEmit` against the official `@cocos/creator-types` 3.8.3, zero errors).
  Reproducible: `cd tools/cocos-typecheck && npm ci && python3 check.py`. It runs two checks —
  zero errors, **and** that planting a certain type error into the real source makes tsc report it
  (passing alone would not prove the gate has teeth: with the config written wrong it is green too).
  `tools/conformance` adds an offline guard watching that tsconfig's `files` covers every runtime
  `.ts` and that the docs and the config name the same version.
- ✅ Source-level guards (`scripts/tests/test_runtime_source.py`): linear interpolation present,
  built-in easings not imported, transform not applied to the layer, scaling compensating the anchor.
- ✅ **Run inside Creator 3.8.8** (2026-08-05): built for `web-desktop` from a real Figma capture
  and screenshotted at 1080×1920 — mean **6.21–8.93/255** against the HTML build on the same frame,
  the same order as Godot and Unity. That run is what found the three bugs no static gate can reach:
  runtime-created nodes landing on `Layers.Enum.DEFAULT` while the UI camera only draws `UI_2D`
  (whole tree built, zero pixels, no error), the Babel conditional-expression crash that fails an
  entire script, and the `Graphics.arc` behaviour above. All three now carry source-level guards.
- ⚠️ Motion has **not** been watched in Play mode — the curve values are pinned, the picture is not.

## 6. Integration smoke checklist (do this on first integration)

1. `python3 scripts/ui_check.py flow.json <capDir>` all green, and place images per
   `assets-manifest.json` into `assets/resources/<assetRoot>/` (keeping the `_assets/...` relative
   path, same stem inside Creator).
2. Copy the `.ui.json` / `flow.json` into the project (Creator imports `screen-login.ui.json` as a
   JsonAsset named `screen-login.ui` — FlowBinder matches on that stem).
3. Build the Canvas + FigmaRoot per §4 and mount **FigmaUI** first to check geometry for a single
   screen against the Figma screenshot (watch: top-left alignment, child relative positions, z order).
4. Then mount **FlowBinder**, with the hook component calling
   `FlowBinder.registerHook({register, init})` in its own `onLoad` (FlowBinder builds in `start()`,
   so registering in onLoad is always in time).
5. Click through every event: modal open/close, guard refusal, checkbox states, cloned row clicks.

## 7. Robustness

`flowAsset` and its parsed `json` are both checked before use; Creator has already parsed the
JsonAsset at import time, so a malformed file never reaches the runtime as a string. This is the
repo-wide rule (malformed IR gets a sentence, not a traceback) and `tools/conformance` checks all
four runtimes for it.
