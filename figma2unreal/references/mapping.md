# IR → UMG: the full mapping (figma2unreal)

> The zh-CN original is kept alongside as `mapping.zh.md`. English is the authority: land edits
> here first, then mirror. `tools/conformance` compares the two structurally (row counts and code
> blocks), so a one-sided edit goes red.

> **Statement: the C++ runtime (runtime/) has not been compile-verified inside the engine** — what
> ships = the source plus this integration guide. Target engine **UE 5.3+**; for a first
> integration, compile by the steps below. Should individual APIs differ across engine point
> releases, the fixes are local (concentrated in FSlateBrush/FSlateFontInfo fields and UMG setters)
> and do not touch the architecture.
>
> **Engine-free gates (already in place, run by CI every time)**: not being able to install the
> engine does not mean nothing is checked — two deterministic static gates hold the line.
> `scripts/uespec_contract.py` (two-way reconciliation between the fields Python emits and the
> fields C++ reads, with every §4 known-loss item corresponding to one of its WAIVERS declarations)
> and `scripts/uht_lint.py` (UE reflection conventions R1–R6: generated.h last, GENERATED_BODY,
> UINTERFACE pairing, BlueprintNativeEvent dispatched through Execute_, GC visibility of UObject
> members, include-module registration ⊆ the §5 Build.cs). **They check conventions and contracts,
> not API truth** — whether `FSlateFontInfo` really has a `LetterSpacing` field is still a question
> only a real compile can answer.

Division of labour (mirroring figma2html's two layers):

| Layer | Artifact | Responsibility |
|---|---|---|
| Python preprocessor `scripts/ui_to_uespec.py` | `<screen>.uespec.json` / `flow.uespec.json` | **Parses every CSS string** into strongly typed numbers/structures, plus reference validation; testable offline (tests all green) |
| C++ interpreter `runtime/FigmaUiWidget` | The Widget tree | **Zero parsing**: builds the UI from the uespec with WidgetTree (visuals) |
| C++ interpreter `runtime/FigmaFlowComponent` | Interaction | assemble.js semantics: base screen + modals / guards / toggleFlag / send / row cloning / checkbox; domain semantics go through `IFigmaAppHook` |

## 1. Element mapping

| IR field (.ui.json) | uespec strong type | Where it lands in UMG | Fidelity |
|---|---|---|---|
| `x,y,w,h` (absolute px within the frame) | `absX/absY` + `localX/localY` (parent-relative, following render.js pass2) | `UCanvasPanelSlot::SetPosition(local)/SetSize`; a lifted subtree's root uses abs | Exact |
| `parent` nesting | Same | Container elements → `UCanvasPanel` (their own visual fills it as a background), children mounted into the panel | Exact |
| `z` | `z` (int) | `UCanvasPanelSlot::SetZOrder` (capture order is draw order) | Exact |
| `rot` | `rot` (degrees) | `SetRenderTransformAngle` + a centre pivot (= CSS `transform-origin:center`) | Exact (rot missing inside a Figma INSTANCE is an upstream API limitation, same as the HTML build) |
| `opacity` | `opacity` | `SetRenderOpacity` | Exact |
| `fill: rgba(...)` | `{type:"solid",rgba:[r,g,b,a]}` | `UBorder` + `FSlateBrush` (RoundedBox) `TintColor` | Exact (sRGB→linear via `FromSRGBColor`) |
| `fill: linear-gradient(...)` | `{type:"linear",angleDeg,stops:[{rgba,pos}]}` | **First-stop solid fallback + UE_LOG** (known-loss; the material route is in §4) | Fallback |
| `fill: radial-gradient(...)` | `{type:"radial",stops:[...]}` | Same fallback | Fallback |
| `radius: "37px"` / four values / `50%` | `[tl,tr,br,bl]` px floats (`50%`→`min(w,h)/2`) | `FSlateBrush::OutlineSettings.CornerRadii` (UE5 RoundedBox has native per-corner radii) | Exact (the `50%` elliptical corner is a scalar approximation) |
| `border: "4px solid rgba(..)"` | `{width,rgba}` | `OutlineSettings.Width/Color` (RoundedBox outline) | High (sub-pixel difference between CSS's inward border and Slate's centred outline) |
| `shadow: "0px 4px 0px rgba(..)"` | `[{dx,dy,blur,rgba}]` | **Not rendered + UE_LOG(Verbose)** (known-loss) | Lost |
| `blur: "blur(4px)"` | `{radius}` | **Not rendered + UE_LOG(Verbose)** (known-loss; `UBackgroundBlur` blurs what is behind, not the element itself, which is not equivalent) | Lost |
| `img` / `imgSize` | `{path,mode}` (mode: cover/contain/stretch/tile) | `UImage` + `LoadObject<UTexture2D>` (path convention in §3); **a missing image falls back to transparent + UE_LOG(Warning)**, never a filled placeholder | High (cover≈stretch: Figma's exported image has the element's aspect ratio; contain/tile fall back to stretch) |
| `vec:true` (a flattened vector cluster) | `vec` (recorded only) | Goes through the ordinary image path (capture already flattened the cluster to png); a missing image is a transparent placeholder. **The runtime does not consume the `vec` flag itself** | Same as img |
| `stageBg` | `{type:solid/linear/radial/image,...}` | A full-frame UBorder/UImage at ZOrder −10000 (modal layers do not draw it) | Same as fill/img |

## 2. Text mapping

| IR text field | uespec | Where it lands in UMG | Fidelity |
|---|---|---|---|
| `content` | Same | `UTextBlock::SetText` (FText preserves `\n`) | Exact |
| `color` | An `rgba` array (with `#hex` fallback parsing) | `SetColorAndOpacity` | Exact |
| `size` (px) | `size` | `FSlateFontInfo::Size = round(px×0.75)` (CSS px→Slate pt at 96dpi) | High |
| `weight` | `weight` | Literal split: ≥600→"Bold", otherwise "Regular" (the engine's Roboto has those two faces) | Approximate |
| `family` | `family` (recorded only) | **No specific font is mapped**; everything uses `DefaultFontObject` (unset → the engine's Roboto) → known-loss. **CJK requires a Chinese font asset set on a Blueprint subclass** | Lost (family) |
| `lh` (px) | `lh` | `SetLineHeightPercentage(lh/(size×1.2))`, approximate | Approximate |
| `ls` (px) | `ls` | `FSlateFontInfo::LetterSpacing = round(ls/size×1000)` (1/1000 em) | High |
| `alignH/alignV` (in-box alignment) | `start/center/end` | The wrapping `UBorder`'s `SetHorizontalAlignment/SetVerticalAlignment` (= render.js flex alignment) | Exact |
| `textAlign` | Same | `SetJustification` (justified→Left) | Exact |
| `stroke` (-webkit-text-stroke) | `{width,rgba}` | `FSlateFontInfo::OutlineSettings` (FontOutline) | Approximate (CSS `paint-order:stroke fill` puts the stroke underneath, and FontOutline is likewise an outer outline, so they look close; a thick stroke reads slightly heavier) |

## 3. flow / interaction mapping (assemble.js semantics ↔ FigmaFlowComponent)

| flow.uespec | UE implementation |
|---|---|
| `base` | `UFigmaUiWidget` permanently `AddToViewport(0)` |
| `modals[*].roots` | `BuildFromSpec(cap, roots)` lifts the subtree (roots use absX/absY, = render.js `subtreeOf`), `AddToViewport(50+i)`, initially `Collapsed`; the backdrop is a full-frame `UBorder rgba(0,0,0,0.5)` at ZOrder −20000 |
| `events[].targets` `kind:node` | A **fully transparent UButton** overlaid on the element's geometry on the base screen (all visual Widgets are HitTestInvisible so the button owns the hit; chosen over `OnMouseButtonDown` because it neither disturbs the visual tree nor hand-rolls hit testing — see the `AddClickOverlay` comment) |
| `kind:in` (v1.1) | The same overlay, but inside that modal's widget, at ZOrder 40000 — it **must** sit above `kind:any`'s full-frame layer (30000), or the ✗ inside a popup is covered and unclickable |
| `kind:any` | A full-frame transparent button on that modal layer (ZOrder 30000, topmost) |
| `kind:panelOutside` | A full-frame transparent button (ZOrder 9000) plus a **panel shield** (a click-swallowing button over the panel's geometry, ZOrder≈10000+z) → only clicks outside the panel fire |
| `guard` | `IsTruthy`: null/false/0/"" are falsy (= assemble.js `guardOk`); failure calls back into `OnGuardFail` |
| `do: openModal/closeModal/toggleFlag` | Built into the component; `send`→`IFigmaAppHook::OnSend`; anything else→`OnCustomAction` |
| `list` | `PopulateList(Count)`: the container's first child is the template row, the second row's top delta is the step, N rows are cloned (element ids inside a row become `"<originalId>#<rowIndex>"`), and a row click calls `OnListRowClicked(i)`; row copy is filled by the hook through `GetModalWidget(...)->SetElementText("3:23#0", ...)` |
| `bindings.checkbox` | Two states: `SetElementBrushColor` (checked/unchecked rgba) plus a lazily created centred check-mark `UTextBlock` (24px Bold, = assemble.js) |
| `state` | `TMap<FString, FJsonValue>` verbatim; `SetStateString/ToggleFlag` automatically runs `SyncBindings` + `OnStateChanged` after a change |

## 4. known-loss summary

| Item | Current state | Future route (not implemented — do not build it in this version) |
|---|---|---|
| Linear / radial gradients | First-stop solid fallback + `UE_LOG(Warning)` | A general gradient material (`M_FigmaGradient`: a 2–8 stop parameterised `UMaterialInstanceDynamic`) with `UImage::SetBrushFromMaterial`; angleDeg/stops are already carried in the uespec |
| box-shadow | Not rendered + `UE_LOG(Verbose)` | A nine-slice shadow sprite, or a RetainerBox post-process |
| layer blur | Not rendered + `UE_LOG(Verbose)` | `UBackgroundBlur` (semantically it blurs the backdrop, so it substitutes only in some cases) |
| Font family | Everything uses DefaultFontObject/Roboto; weight only splits Regular/Bold | A project font table: family→UFont asset mapping |
| Text stroke | FontOutline approximation (not paint-order semantics) | — |
| imgSize contain/tile | Stretch fallback + `UE_LOG(Verbose)` (cover≈stretch, since Figma's export matches the element's ratio) | Brush tiling or custom UVs |
| Elliptical `50%` corners | `min(w,h)/2` scalar approximation (exact on circles, slightly off on non-squares) | — |
| `flow.events[].transition` | Baked into `motion.json` sample points, **FigmaFlowComponent is not wired to them = not played** | See "Transition easing" below |

### Transition easing (motion.json)

When given a `flow.json`, `ui_to_uespec.py` emits one extra file into outdir, `motion.json`: per
event carrying a transition, a **17-point evenly spaced sampled curve** (x and y are both 0..1 progress).

**Why sample points rather than an `EEasingFunc`.** Figma hands over a specific curve
(`cubic-bezier(.32,.72,0,1)`, or a spring's three parameters); `EEasingFunc::EaseOut` is a
**different curve sharing the name**. Every backend picking "the closest one" means one IR becomes
six different feels across six engines while every test stays green. For scale: easeOutCubic differs
from `cubic-bezier(.23,1,.32,1)` by up to **19.8 percentage points**, and the worst of it is in the
opening moments. `tools/conformance` compares these points against godot and unity **one by one**.

It also matches this backend's **responsibility boundary**: Python does all the numeric solving and
C++ parses nothing — `FRichCurve::AddKey(x, y)` per point is enough, with no need to implement
bézier inversion or a spring ODE in C++.

| Handling | Note |
|---|---|
| **known-loss: not played** | `FigmaFlowComponent` is **not wired yet**; the generator stamps `[known-loss]`, so it is not a silent loss |
| **known-loss: named spring presets** | Figma publishes no control points for `GENTLE/QUICK/BOUNCY/SLOW` or `*_BACK` → marked `unresolved` and not sampled. **No invented numbers** |
| **approx: spring truncated by duration** | A spring has no fixed length, so a window shorter than its settling time cuts it off; the generator stamps `truncated:` |
| **known-loss: `SMART_ANIMATE`** | Auto-pairing same-named layers has no cross-engine equivalent; the curve is sampled, the pairing logic is not implemented |

⚠️ `motion.json` **does not go into `flow.uespec.json`**; it is a separate parallel artifact — so it
cannot disturb the python↔C++ field contract that `uespec_contract.py` guards (every entry in that
table must have a reader on the C++ side).

## 5. Integration steps

1. **Module dependencies**, in the project's `Source/<Game>/<Game>.Build.cs`:

   ```csharp
   PublicDependencyModuleNames.AddRange(new string[] {
       "Core", "CoreUObject", "Engine", "InputCore",
       "UMG", "Slate", "SlateCore", "Json", "JsonUtilities"
   });
   ```

2. **Copy the source**: `runtime/FigmaUiWidget.h/.cpp` and `runtime/FigmaFlowComponent.h/.cpp` into
   `Source/<Game>/FigmaUi/`, then regenerate the project files and compile (that first compile is
   this code's moment of verification).

3. **uespec placement**: put `ui_to_uespec.py`'s output (the whole set of `<screen>.uespec.json`
   plus `flow.uespec.json`) into `Content/FigmaUi/Spec/` (**as raw json files**, not imported as
   uassets; when packaging, add that directory under Project Settings → Packaging → *Additional
   Non-Asset Directories to Copy*). `FigmaFlowComponent.SpecDirectory` already defaults to
   `FigmaUi/Spec`.

4. **Asset placement**: import capture's `_assets/**.png` into `Content/FigmaUi/Assets/` (keeping
   subdirectories). Texture convention: `_assets/s17/bg.png` → the asset
   `/Game/FigmaUi/Assets/s17/bg` (LoadObject path `"/Game/FigmaUi/Assets/s17/bg.bg"`, i.e. after
   import the **package name is the filename without its extension** — do not rename). Suggested:
   texture group UI, mips off, and leave sRGB alone (keep the default, on).

5. **Startup**: attach `FigmaFlowComponent` to any Actor (commonly a manager Actor held by the HUD
   or PlayerController), set `AppHook` (a Blueprint or C++ implementation of `IFigmaAppHook`), and
   call `InitFlow(PlayerController)` in BeginPlay. For a single-screen preview,
   `CreateWidget<UFigmaUiWidget>` + `BuildFromSpecFile("FigmaUi/Spec/screen-login.uespec.json")`
   works directly.

6. **DPI scaling**: uespec geometry is the **true pixel** size of `cap.w × cap.h` (e.g. 1080×1920),
   and the Widget tree is built 1:1 px. Project Settings → User Interface → DPI Scaling: use a
   **Shortest Side** DPI curve with Scale=1.0 at the design short edge (1080, say), so the engine
   scales everything proportionally across resolutions (the equivalent of render.js's `mountStage`
   `scale = min(vw/fw, vh/fh)`). Do not multiply by a scale again inside the Widget.

7. **CJK fonts**: create a Blueprint subclass of `UFigmaUiWidget` and set `DefaultFontObject` to a
   font asset containing Chinese glyphs, or assign it in C++. Leaving it unset falls back to the
   engine's Roboto and Chinese renders as tofu boxes.

## 6. Robustness

A `.uespec.json` that fails to parse produces one `UE_LOG(Error)` and a clean return —
`FJsonSerializer::Deserialize` returns a bool and the result is checked. This is the repo-wide rule
(malformed IR gets a sentence, not a traceback) and `tools/conformance` checks all four runtimes for it.
