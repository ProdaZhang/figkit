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
| `radius` (1–4 value shorthand) | the four longhand `border-top-left/top-right/bottom-right/bottom-left-radius` | Expanded by the CSS shorthand rules (1→aaaa, 2→abab, 3→abcb) |
| `border` (`Wpx style color`) | `border-width` + `border-color` | USS borders are always solid; a non-solid style is recorded as known-loss |
| `fill` (solid) | `background-color` | USS takes rgba strings natively |
| `fill` (gradient) | `background-color` = **first stop colour** fallback | USS has no gradients; recorded as known-loss |
| `img` | `background-image: url("...")` + `background-size` (imgSize, default cover) + `background-position: center` + `background-repeat: no-repeat` | background-size and friends need Unity 2022.2+ |
| `stageBg` | On the frame root `.screen-root`: url→background image, colour→background colour, gradient→first stop | — |
| `shadow` | **dropped** | USS has no box-shadow; recorded as known-loss |
| `blur` | **dropped** | USS has no filter; recorded as known-loss |

## Text (the `text` sub-object → Label)

| IR | USS | Notes |
|---|---|---|
| `content` | The UXML `text` attribute | `\n` → `&#10;` |
| `color` / `size` | `color` / `font-size` | — |
| `weight` | `-unity-font-style: bold` (≥600) / `normal` | Numeric weights are lost; anything other than 400/700 is recorded as known-loss |
| `alignV` + `textAlign` | `-unity-text-align: <upper\|middle\|lower>-<left\|center\|right>` | flex-start→upper, center→middle, flex-end→lower; the horizontal half comes from textAlign, which is also right for multi-line |
| `ls` | `letter-spacing: <n>px` | — |
| `lh` | **dropped** | USS has no line-height; recorded as known-loss |
| `family` | **not mapped** | Unity text needs a FontAsset: configure a CJK font (e.g. Source Han Sans SDF) in PanelSettings or the theme, or set `-unity-font-definition` globally on `.unity-label`; recorded as known-loss |
| `stroke` | **dropped** | USS has no glyph outline (only TextMeshProUGUI does); recorded as known-loss |
| Wrapping | contains `\n` → `white-space: normal`; single line → `nowrap` | Same as render.js: stops a wider font fallback from forcing a wrap |
| — | Labels also get `margin:0; padding:0` | Flattens `.unity-label`'s built-in padding so the IR geometry survives |

## known-loss summary (honest degradation — all of it is written into the generated `.uss` header comment)

| Item | Handling | Note |
|---|---|---|
| `shadow` | skipped | Add a 9-slice shadow sprite in Unity if you need one |
| `blur` | skipped | No filter |
| gradient `fill`/`stageBg` | falls back to the first stop as a solid | Swap in a gradient texture if you need a real one |
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
opening moments. `tools/conformance` compares these points against godot and unreal **one by one**.

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
