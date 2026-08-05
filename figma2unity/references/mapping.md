# IR → Unity UI Toolkit: the full mapping (the authority `ui_to_unity.py` implements)

> The zh-CN original is kept alongside as `mapping.zh.md`. English is the authority: land edits
> here first, then mirror. `tools/conformance` compares the two structurally (row counts and code
> blocks), so a one-sided edit goes red.

Input = figma2html's `.ui.json` (IR schema in `../../figma2html/references/ui.json-schema.md`).
IR style values are **CSS-flavoured strings** (`radius="45px"`, `border="2.0px solid rgba(...)"`,
`fill="rgba(...)"` or `linear-gradient(...)`); the converter parses each and maps it to USS.

## Naming conventions (load-bearing)

| Convention | Rule | Why |
|---|---|---|
| UXML `name` | Figma id's `':'` becomes `'_'` (`1:30` → `1_30`) | The UXML name attribute does not allow colons |
| USS selector | A `.el-<name>` class (e.g. `.el-1_30`), **not** `#name` | Names usually start with a digit, and a CSS/USS `#id` selector cannot |
| Frame root | `name="screen-root"` plus a `.screen-root` class | Carries the frame size and stageBg |
| Runtime lookup | `FlowBinder.SafeName(figmaId)` applies the same rule, then `layer.Q(name)` | flow.json still stores raw Figma ids; the binder converts |

## Structure and geometry

| IR | UXML/USS | Notes |
|---|---|---|
| `els[]` + `parent` | A VisualElement tree nested by parent | Same as render.js pass1/pass2 |
| `type=TEXT` (`text≠null`) | `<ui:Label text="...">` | Newlines become `&#10;` |
| Any other type | `<ui:VisualElement>` | — |
| `x,y` (absolute px within the frame) | `left/top` (**parent-relative**: `child.x - parent.x`) | Algorithm copied from render.js pass2; a missing or unresolvable parent attaches to the frame root and converts against (0,0) |
| `w,h` | `width/height` (px) | UI Toolkit layout is border-box, so `box-sizing` needs no handling |
| `z` | **no z-index** → siblings are emitted in stable z order under the same parent | In UI Toolkit a later sibling draws on top, which is visually equivalent |
| `rot` | `rotate: <n>deg` | transform-origin defaults to center, matching render.js |
| `opacity` | `opacity` (emitted only when ≠1) | — |

## Style

| IR | USS | Notes |
|---|---|---|
| `radius` (1–4 value shorthand) | the four longhand `border-top-left/top-right/bottom-right/bottom-left-radius` | Expanded by the CSS shorthand rules (1→aaaa, 2→abab, 3→abcb), then **clamped the CSS way** before Unity sees it: when adjacent radii exceed an edge, CSS scales all four by one factor while Unity clamps each axis on its own. A 57px radius on a 235×42 pill therefore renders in Unity as a 57×21 elliptical corner — a stretched olive — where the browser draws a capsule. Percentages are left alone (`50%` on a non-square box is *meant* to be elliptical) |
| `border` (`Wpx style color`) | `border-width` + `border-color` | USS borders are always solid; a non-solid style is recorded as known-loss |
| `fill` (solid) | `background-color` | USS takes rgba strings natively |
| `fill` (gradient) | `background-image` = a **PNG baked at compile time** | USS has no gradient property, so the converter bakes a 64² texture, projecting every texel onto the real gradient axis of that element (any angle, not just 0/90°). Compile-time, so the integrator gets no extra runtime code and the output stays byte-deterministic. Unparseable gradients still fall back to the first stop |
| `img` | `background-image: url("...")` + `background-size` (imgSize, default cover) + `background-position: center` + `background-repeat: no-repeat` | background-size and friends need Unity 2022.2+ |
| `stageBg` | On the frame root `.screen-root`: url→background image, colour→background colour, gradient→first stop | — |
| `shadow` | Sibling **underlay** boxes: a hard `2px 6px 0 c` is the same rounded box offset and filled; a **blurred** one gets a PNG baked at compile time (`soft_shadow_asset`) and shown as the underlay's background | USS has neither `box-shadow` nor a blur, but "another box underneath" expresses both. The blur is a rounded-rect coverage mask (per-axis elliptical corners, one-pixel antialiasing) run through **three box passes ≈ Gaussian at σ = blur/2**, which is CSS's own definition; the canvas is inflated by 3σ so the falloff is not clipped. Deterministic and content-hashed, so six identical cards share one file. Only with no writable asset dir does it fall back to known-loss |
| `blur` | **dropped** | USS has no filter; recorded as known-loss |
| `paths` + `viewBox` (v1.2) | `<figkit:FigVector>` — `runtime/FigVector.cs` drawing through **Painter2D** | Real vector drawing: no bitmap asset is produced and no extra package is needed (`com.unity.vectorgraphics` is a preview package). The element parses the SVG path (M/L/H/V/C/S/Q/T/Z, béziers flattened at a fixed step count so output stays deterministic) and fills it with the winding rule the IR asked for. **The UXML declares `xmlns:figkit` only when a screen actually has vectors** — declaring it without shipping the runtime makes the whole UXML fail to load. Stroke bands normally arrive from capture as a ready-to-fill even-odd ring (IR v1.3), so nothing special is needed. When capture cannot read a band it falls back to the raw ±2w band plus a `clip` hint, and Painter2D has no boolean clip: the OUTSIDE half is still exact — draw the band first, then let the opaque fill cover the inner half — but an INSIDE fallback draws at full width and comes out twice as thick, logged as known-loss per element. Separately, **Painter2D joins the contours of a multi-contour path into one polygon** (it shredded every stroke band into thin triangles), so contours whose bounding boxes do not overlap are filled one at a time; overlapping ones keep a single fill, because that is what carves holes out of a shape |
| `clip` (v1.1) | `overflow: hidden` | UI Toolkit's `overflow` already follows `border-radius`, so rounded clipping is exact here with no extra work (Godot needs `clip_children` to reach the same place) |
| `borderAlign` (v1.2) | a sibling box laid underneath, inflated by N with radius + N | USS has no `box-shadow`, but the outward half of a stroke *is* "another box of the same shape, N bigger" — so it is drawn rather than dropped. Same mechanism as hard shadows below |

## Text (the `text` sub-object → Label)

| IR | USS | Notes |
|---|---|---|
| `content` | The UXML `text` attribute | `\n` → `&#10;` |
| `color` / `size` | `color` / `font-size` | — |
| `weight` | `-unity-font-style: bold` (≥600) / `normal` | Numeric weights are lost; anything other than 400/700 is recorded as known-loss |
| `alignV` + `textAlign` | `-unity-text-align: <upper\|middle\|lower>-<left\|center\|right>` | flex-start→upper, center→middle, flex-end→lower; the horizontal half comes from textAlign, which is also right for multi-line |
| `ls` | `letter-spacing: <n>px` | — |
| `lh` | **dropped** | USS has no line-height; recorded as known-loss |
| `family` | `-unity-font-definition: url("fonts/FigCJK-<Regular\|Bold>.ttf")` | The converter writes the reference; **you place the two .ttf files next to the .uss** (`subset_font.py` instances and subsets them from a variable source). Two traps, both silent: a *missing* file is an import error you will see, but a file whose **subset does not cover the characters on screen** is not — Unity just falls back to another face, and the layout stays plausible. It is invisible in the outside-text metric by construction; what moves is the in-text half. Second trap: with a real Bold face loaded, stop emitting `-unity-font-style: bold` or Unity synthesises a second bold on top of it |
| `stroke` | **dropped** | USS has no glyph outline (only TextMeshProUGUI does); recorded as known-loss |
| Wrapping | contains `\n` → `white-space: normal`; single line → `nowrap` | Same as render.js: stops a wider font fallback from forcing a wrap |
| — | Labels also get `margin:0; padding:0` | Flattens `.unity-label`'s built-in padding so the IR geometry survives |

## known-loss summary (honest degradation — all of it is written into the generated `.uss` header comment)

| Item | Handling | Note |
|---|---|---|
| blurred `shadow` | **baked to a PNG** and shown under the element | Only when there is no asset dir to write into does it become a real loss |
| `blur` | skipped | No filter |
| gradient that will not parse | falls back to the first stop as a solid | Linear **and radial** are baked to a PNG (radial as CSS's default `ellipse at center` / `farthest-corner`); only conic and malformed forms land here |
| `text.stroke` | skipped | Carry the text on a TextMeshPro component instead |
| `text.lh` (line height) | skipped | USS has no line-height |
| `text.family` | not mapped | Needs a FontAsset configured by hand (see the table above) |
| numeric weights (500/800…) | approximated to normal/bold | USS has only the two |
| non-solid `border` | degraded to solid | USS borders are always solid |
| `z` | replaced by document order | Sorted by z under the same parent; extreme cross-parent interleaving cannot be expressed |
| `flow.events[].transition` | baked into `motion.json` sample points, **and now played** | See "Transition easing" below |

## Transition easing (motion.json)

`python3 ui_to_unity.py <cap.ui.json> <outdir> <flow.json>` emits one extra file, `motion.json`:
per event carrying a transition, a **17-point evenly spaced sampled curve** (x and y are both 0..1 progress).

**Why sample points rather than a USS easing keyword.** Figma hands over a specific curve
(`cubic-bezier(.32,.72,0,1)`, or a spring's three parameters); USS's `ease-out` and friends are a
**different curve sharing the name**. Every backend picking "the closest one" means one IR becomes
six different feels across six engines while every test stays green. For scale: easeOutCubic differs
from `cubic-bezier(.23,1,.32,1)` by up to **19.8 percentage points**, and the worst of it is in the
opening moments. `tools/conformance` compares these points against godot **one by one**.

Usage: `new AnimationCurve(points.Select(p => new Keyframe(p[0], p[1])).ToArray())`, then tween it
yourself. **Do not** swap in a `transition-timing-function` keyword for convenience.

**Wiring**: drag `motion.json` onto `FlowBinder`'s `motionJson` (a TextAsset). Leave it unset and
everything shows and hides instantly — a **declared degradation**, not a silent loss. Set it and
these come to life:

| Mechanic | Behaviour | Where the curve comes from |
|---|---|---|
| Modal entrance / **exit** | `events[].transition`, covering `SCALE_IN/OUT`, `MOVE_IN/OUT`, `SLIDE_IN/OUT`, `DISSOLVE` | Declared in Figma, or filled in from the preset |
| Press feedback | Every event-bound element scales to `motion.press.scale` on `PointerDown` | Preset (Figma has no such concept) |
| List rows entering | `RenderRows` staggers each row by `motion.stagger.step` | Preset |
| Guard refusal | A shake (`motion.guardFail`) | Preset |

For the directional transitions the panel travels **the stage's** dimension, not its own box — see
`spec/flow-events.md`; `tools/conformance` pins all four backends to that basis, because the curve
values are identical either way and only the distance differs.

**Verified in Unity 6000.4.8f1 batchmode, 2026-07-29**: `FlowBinder` reads `motion.json` as 6
`AnimationCurve`s (17 keyframes each), and `Evaluate(0.25)` agrees with the Python solver **to six
decimal places on every one** (`DISSOLVE 0.378138` / `MOVE_IN 0.779131` / `SCALE_OUT 0.775382` /
`press` / `stagger`); compiles with zero errors and zero warnings. **Visual playback has not been
checked in Play Mode** (that needs the scene actually running).

| Handling | Note |
|---|---|
| **known-loss: named spring presets** | Figma publishes no control points for `GENTLE/QUICK/BOUNCY/SLOW` or `*_BACK` → marked `unresolved` and not sampled. **No invented numbers** |
| **approx: spring truncated by duration** | A spring has no fixed length, so a window shorter than its settling time cuts it off; the generator stamps `truncated:` |
| **known-loss: `SMART_ANIMATE`** | Auto-pairing same-named layers has no cross-engine equivalent; the curve is sampled, the pairing logic is not implemented |
| **known-loss: spring curves** | The points are sampled, but neither CSS nor USS has a native spring; interpolating sampled keyframes gets the shape right and gives up interruptibility |

⚠️ Use `style.scale` / `style.translate`, **not** `transform.scale` / `transform.position` — the
latter are all `[Obsolete]` as of Unity 6 and would break this backend's zero-warning claim.

Animation progress reads `TimerState.now`, a real millisecond clock, rather than adding a fixed
0.016 per callback. `.Every(16)` states an *intended* interval; treating it as the actual one makes
a 300ms transition take 400ms of wall clock whenever frames drop, while the other three backends
follow real time. `tools/conformance` guards this at source level.

## Coordinates and scaling (placement on the Unity side)

- The generated UXML is a **fixed-px canvas** (frame size = `cap.w × cap.h`, e.g. 1080×1920). It is not responsive.
- **PanelSettings**: Scale Mode = `Scale With Screen Size`, Reference Resolution = `cap.w × cap.h`,
  Screen Match Mode per product orientation (portrait games commonly use Match = 1/Height, or Expand).
  This is the equivalent of render.js's `mountStage` scaling the stage to the viewport.
- `FlowBinder` creates a `flow.stage.w × flow.stage.h` stage container; the base screen and every modal layer fill it.

## Texture import settings (do not leave these at Unity's defaults)

Unity's default importer is tuned for 3D surfaces, and every one of those defaults is wrong for UI.
`runtime/Editor/FigkitTextureImport.cs` is an `AssetPostprocessor` that fixes them for anything under
`Assets/Resources/UI/`. Three of them were caught by comparing real pixels (2026-08-05, the white
tick on the claimed-reward screen):

- **`mipmapEnabled`** — UI art is blitted 1:1, but the sampler can still drop to a lower mip, so edges
  bleed outward. The white tick came out a pixel fatter on every side than HTML with its bottom row
  sheared flat, while the gold stars in the same cell came out a pixel *thinner* — bright things
  spread, dark things shrink; same cause.
- **`textureCompression`** — DXT/BC block artefacts on exactly the high-contrast edges UI is made of.
- **`alphaIsTransparency`** — with it off, fully transparent texels keep whatever RGB they were
  authored with, and semi-transparent edges bleed dark.

Also pinned: `wrapMode = Clamp` (UI never tiles; Repeat samples the opposite edge) and
`npotScale = None`. With those set, the tick matches HTML **row for row** (24/22/20/…/5/0 white
pixels down its lower edge, identical). Point the `Root` constant somewhere else if your project
puts figkit's art elsewhere, and reimport that folder once after changing it.

## Where image assets go

- `background-image: url("_assets/s17/xx.png")` in USS resolves **relative to the USS file**:
  copy capture's exported `_assets/` directory next to the `.uxml`/`.uss` (e.g. `Assets/UI/Screens/_assets/...`),
  and once Unity imports them as Sprite/Texture the url resolves.
- To reference assets elsewhere in the project, use the absolute form `url("project:///Assets/...")` (or `/Assets/...`).
- Missing-image behaviour matches figma2html: a `vec`/`img` node whose PNG is missing renders transparent, never a black fill.

## How the runtime (FlowBinder) lines up with assemble.js

| assemble.js | FlowBinder.cs | Difference |
|---|---|---|
| `build` | `Build()` (OnEnable) | caps come from the Inspector's `screens[]` (VisualTreeAsset), not over the network |
| `subtreeOf` + modal layer | Instantiate the whole screen → `Q(root)`, detach, re-attach, and carry the stylesheets across | UI Toolkit attaches stylesheets to elements, so lifting a subtree has to bring them along |
| backdrop | A translucent black VisualElement inside the layer | Same rgba(0,0,0,0.5) |
| `wireEvents` (click / @any / @panelOutside / @in) | `RegisterCallback<ClickEvent>` | Same semantics. `@in:<modal>:<nodeId>` (v1.1) resolves inside the modal layer and stops propagation, or the `@any`/`@panelOutside` handler on the same layer fires too |
| `guardOk` | `Truthy` + `GuardOk` | null/false/0/"" are all falsy, identically |
| `renderRows` (cloneNode) | `RenderRows` (re-instantiate the cap, lift the template row) | UI Toolkit has no deep clone; row spacing is sampled from resolvedStyle, so it **must be called after layout** (`schedule.Execute` for a frame inside Init) |
| `bindings.checkbox` | `SyncBindings()` (the check mark is a child Label) | VisualElement has no textContent |
| `app.js APPHOOK` | `IAppHook` (RegisterActions/Init) | Same split: the engine owns mechanics, the hook owns domain semantics |
| list scrolling (overflowY:auto) | The container clips with `Overflow.Hidden` | USS has no overflow:scroll; if you need scrolling, have the hook swap in a ScrollView |

## Robustness

`flow.json` that is not valid JSON produces one logged sentence and a clean return, not an
unhandled exception — `MiniJson` throws, so both parse sites sit inside a `try`. A malformed
`motion.json` degrades to instant transitions, which is the same behaviour as not supplying one.
This is the repo-wide rule (malformed IR gets a sentence, not a traceback) and
`tools/conformance` checks all four runtimes for it.
