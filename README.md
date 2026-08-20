# FigKit — one Figma capture, five runnable outputs

[![tests](https://github.com/ProdaZhang/figkit/actions/workflows/tests.yml/badge.svg)](https://github.com/ProdaZhang/figkit/actions/workflows/tests.yml)

*Turn a Figma frame into a runnable client — **HTML, Unity, Godot, Cocos Creator** — plus a semantic UI-DSL, all compiled from one pixel-faithful intermediate representation. Figma's own prototype links and transitions are imported; the **application semantics** on top (guards, data binding, app hooks) are declared once and run on every backend.*

| Figma (the design) | HTML (Edge) | Unity | Godot | Cocos Creator |
|---|---|---|---|---|
| ![the Figma frame this screen was captured from](docs/shots/mail-figma.png) | ![mail rendered in HTML](docs/shots/mail-html.png) | ![mail rendered in Unity](docs/shots/mail-unity.png) | ![mail rendered in Godot](docs/shots/mail-godot.png) | ![mail rendered in Cocos Creator](docs/shots/mail-cocos.png) |

One frame out of a shipping game's Figma file, captured once and compiled four ways. The first
column is the Figma export itself — the design, in its own language; the demo is translated, since
a UI kit should be readable by people who don't read Chinese. Each of the other four is measured
**against that first column**, not against each other.

**Mean difference from the Figma frame, outside text** (`/255`; why *outside text* is
[below](#how-close-is-it-really)):

| screen | HTML | Unity | Godot | Cocos |
|---|---|---|---|---|
| list | **0.81** | **0.81** | **1.13** | **1.13** |
| detail, with attachments | **0.53** | **0.59** | **0.65** | **0.57** |
| detail, nothing to claim | **0.59** | **0.62** | **0.63** | **0.63** |

The frames are committed in [`examples/mail/design/`](figma2html/examples/mail/design), so this
reproduces from a clone:

```bash
python3 tools/design-diff/check.py figma2html/examples/mail/screen-list.ui.json \
                                   figma2html/examples/mail/design/screen-list.png
```

```
figma REST ──► figma_capture ──►  IR: <screen>.ui.json (pixels) + flow.json (behavior)
                                   │        spec/ v1.1 — the shared contract, additive-only
        ┌──────────┬───────────┬───┴───────┬───────────┐
        ▼          ▼           ▼           ▼           ▼
   figma2html  figma2dsl  figma2unity figma2godot figma2cocos
   runnable    semantic   UXML+USS +  .tscn +     Creator TS
   HTML client UI-DSL(md) FlowBinder  GDScript    interpreter

        └──────────┴───────────┴──── figkit-motion ────┘
             the catalog all five share: 59 effects, 63 tokens, 6 algorithms
```

**What makes it different from figma-to-code exporters:** the **flow layer**. Figma's prototype
interactions are real — FigKit imports them — but they run *inside the Figma player, against static
frames*: prototype semantics. `flow.json` adds what a shipping client needs and Figma cannot
express — guards over app state, list rows cloned from real data, and a clean engine-vs-app-hook
boundary — keyed by Figma node ids so it survives re-capture. Every backend implements the *same*
flow semantics, so one declaration runs everywhere.

## Status matrix (honest, per verification level)

Numbers are the mail list screen against the Figma frame, outside text. The long version of each
row — every defect a real engine run found, in the order it was found — is in
[`docs/verification.md`](docs/verification.md).

| backend | offline tests | in-engine verification |
|---|---|---|
| figma2html | ✅ 94 | ✅ rendered + interactions, with the runtime's **behaviour** asserted in a real browser rather than looked at: 8 checks in [`tools/html-smoke/`](tools/html-smoke/), in CI on windows. They read numbers out of the page — offsets, row texts, guard outcome, whether each string fits its box — not pixels. **0.81/255** |
| figma2dsl | ✅ 19 | ✅ (same render pipeline) |
| figma2godot | ✅ 34 | ✅ **Godot 4.3**, re-verified on **4.7.1**. A real capture found what fixtures cannot reach: instance ids carry `;` while `sub_resource` ids accept only `[A-Za-z0-9_]`, so every StyleBoxFlat on an instanced element silently failed to register; and `clip_children` **cannot nest**. `radius: 50%` on a non-square box used to come out a capsule — `corner_radius` is a scalar — and now compiles to an `.svg` with true elliptical corners. **1.13/255** |
| figma2unity | ✅ 31 | ✅ **Unity 6000.4.8f1** and **2022.3.62f3**, the latter as a real built Windows player at 1080×1920, not a batchmode import check — which is how it caught that **one invalid USS selector voids the entire stylesheet** (129 rules applied to nothing, screen black). `paths`, `clip`, outside borders, gradients and now blurred shadows are implemented rather than declared away; the last two bake to PNG at compile time. **0.81/255** — level with HTML |
| figma2cocos | ✅ 19 | ✅ **Cocos Creator 3.8.8**, built for `web-desktop` and screenshotted at 1080×1920. Three bugs only an engine can show: nodes built in code land on the wrong layer, so the whole tree exists and **nothing draws, with no error**; `Graphics.arc` is not canvas's `arc`; and `UIOpacity` does not affect `Graphics` at all. Blurred shadows bake to a texture at load time. **1.13/255** |
| figkit-motion | ✅ 6 | 📖 **not a backend** — the motion catalog the other five share: 59 effects (when to use one, **and when not to**), 63 parameter tokens with a `calibration` status, 6 shared algorithms. No runtime, no artifact. Its `tokens.json` and `motion.py`'s `PRESET` are compared token-by-token by the conformance suite, so the prose and the values figkit writes can't drift apart |

Per-backend tests only compare a backend against its own expectations, so
**31 more live in [`tools/conformance/`](tools/conformance/)**: one fixture exercising every IR feature, a table where
each backend declares what it renders / approximates / drops, and checks that the declaration
matches the real artifact and that every degradation is logged. Three of those exist because the
suite itself had a hole — when the IR grew to v1.2 the new fields reached the schema and capture but
never the fixture, so `paths` and `clip` were silently dropped by every backend with everything
green. Now every schema field must be claimed by a feature, every feature's carrier element must
hold a **non-default** value, and a backend meeting a field it doesn't implement has to say so on
stderr. The same suite pins all backends to identical handling of malformed IR and broken
`flow.json` refs, to the same sampled curve points, and to the same displacement basis and shake
waveform. (Counts above are verified by `tools/run_all_tests.py`, so they can't go stale.)

## Try it (no Figma account, no install, ~10 seconds)

### ▶ [Open the live demo](https://prodazhang.github.io/figkit/)

Or clone and **double-click [`figma2html/examples/login/app.html`](figma2html/examples/login/app.html)** — no server, no build step: the demo's fixtures are inlined into `fixtures.js`, so it runs straight off `file://`. Either way, click through: notice modal, server list (row cloning), agreement guard, enter.

![the login demo: notice fading in, the server list sliding up with its rows staggering, the agreement guard refusing, then entering](docs/shots/demo.gif)

*(Recorded deterministically by [`tools/docs-assets/`](tools/docs-assets/) — each frame is a fresh page replayed to a given step, with the real animation objects paused at a given millisecond.)*

### A real Figma file — and the half FigKit deliberately doesn't do

**[`figma2html/examples/mail/app.html`](figma2html/examples/mail/app.html)** — the screens at the
top of this page. Four of them, 129 elements on the list alone, three overlays, and all the things
a hand-built fixture never thinks of: component-instance ids carrying semicolons, stroke geometry
that arrives as a pre-cut band, an item frame rounded by an `isMask` sibling, a panel sweep whose
`radius: 50%` is a genuine *ellipse*. Every one of those broke a backend at least once; every one
now has a measured entry in a `references/mapping.md`.

![the mail demo: a mail opening, its attachment claimed and the panel swapping state in place, then closing, then a mail with nothing to claim](docs/shots/demo-mail.gif)

The close buttons took a spec bump. Until **v1.1**, `events[].el` could only name nodes on the base
screen, so the most common link in any real Figma file — the button *inside* a popup — had no
representation; the workarounds meant "click anywhere" or "click outside", which is not the same
thing. It is now `@in:<modal>:<nodeId>`.

The claim is the point of the GIF. Pressing it does not close one popup and open another — the same
panel *swaps state in place*, into the claimed version with its watermark and its green delete
button, on the `DISSOLVE` the flow declares. **FigKit implements none of that**, because it has no
idea that two overlays are two states of one mail. It lives in
[`examples/mail/app.js`](figma2html/examples/mail/app.js), in ten lines. That is the boundary this
repo keeps: **the engine owns mechanics, you own meaning.**

The screens are a real capture, so re-capturing them needs the Figma file — but everything
downstream of the IR runs from what is committed here:

```bash
python3 figma2godot/scripts/ui_to_tscn.py  figma2html/examples/mail/screen-list.ui.json out/ figma2html/examples/mail/flow.json
python3 figma2unity/scripts/ui_to_unity.py figma2html/examples/mail/screen-list.ui.json out/ figma2html/examples/mail/flow.json
```

(The third argument is optional; give it `flow.json` and the converter also bakes `motion.json` — the sampled transition curves.)

## How close is it really

The question worth asking is not whether the backends agree with each other — it is whether they
agree with **the design**. Four renderers can be identical and identically wrong: if capture
misreads the frame, all four move together and a backend-vs-backend table doesn't budge. So the
baseline is the Figma export at 1×, and [`tools/design-diff/`](tools/design-diff/) measures every
renderer against it.

The error is split in two, because the halves mean different things. Figma, Chromium, Godot, Unity
and Cocos each rasterise glyphs their own way and always will; that difference is noise, and on
these screens it dominates — whole-frame the same renders read 5–6/255. Everything else — geometry,
colour, corners, strokes, images — is the actual claim, and that is the table at the top of this
page: every backend within **1.2/255**. Reporting one blended number would say the opposite.

Splitting it is also what lets the comparison survive a translation. The design frames are Chinese
and the demo is English, so a whole-frame number would mostly measure the translation. The
non-text half doesn't: rebuilding all four backends from the pre-translation IR moves eleven of
those twelve cells by ≤0.02. Comparing layout rather than ink is exactly what a team does when it
checks a localised build.

It holds on one condition — the translated copy must still **fit the boxes the design captured**.
When it doesn't, the overflow lands in the "outside text" half and reads as a geometry error:
English body copy wrapping one line past its box moved a cell from 0.53 to 0.82 with not a pixel of
rendering changed. So it's asserted, not remembered —
[`tools/html-smoke/`](tools/html-smoke/) measures every string in the demo against its own box in a
real browser and fails on a line that doesn't fit.

Measuring this way is what found the last round of defects, and it found them precisely where
backend-vs-backend was blind — three backends agreeing with each other and disagreeing with Figma.
Godot's `radius: 50%` capsule, and blurred shadows dropped by both Unity and Cocos (a card UI is
mostly blurred shadows). All three are fixed above.

Because engines can't be built on every push, a second, cheap comparison runs against the HTML
output — same IR, same scale, no Figma file needed. It answers a different question: **whether the
backends still understand the IR the same way.**

| | vs HTML, outside text | pixels off by >24 |
|---|---|---|
| Unity 6000.4.8f1 | 0.15/255 | 0.2% |
| Godot 4.7.1 | 0.50/255 | 0.5% |
| Cocos Creator 3.8.8 | 0.55/255 | 1.1% |

All four share one subsetted design font. Before that each backend fell back to its own system font
and even the line breaks disagreed, so the numbers measured little except glyph noise.

The mail example's fourth screen is deliberately absent from the design comparison: its export is a
**later variant** of the frame, so it measures 4.22 and measures nothing about fidelity. That's the
first thing to suspect when the tool returns a bad number, and it's written down in
[its README](tools/design-diff/README.md) rather than quietly dropped.

## Real Figma input

1. Get a personal access token (scope `file_content:read` only). It is read by a single subprocess and never written to disk.
2. `GET /v1/files/<key>/nodes?ids=<frame>` → `nodes.json`
3. `python3 figma2html/scripts/figma_capture.py nodes.json <frameId> s01 <assetDir> assets out/screen-01`
4. **Import the prototype links you already drew in Figma** — `python3 figma2html/scripts/flow_from_figma.py nodes.json flow.json base=screen-01.ui.json notice=screen-02.ui.json` turns `interactions[]` (overlays, back/close, transitions) into a `flow.json` draft. Anything it *can't* carry is listed on stderr with the reason — it never guesses, because a wrong event looks exactly like a right one.
   Add `--motion-defaults` and it also writes in motion for the mechanics the engine owns — pressed states, modal enter **and exit**, list rows entering one after another, an element shaking when a guard rejects it. Most real Figma files have no prototype wiring at all, and a button that does nothing when pressed doesn't read as "undecorated", it reads as broken. Priority is always **Figma > your overrides > preset**, every added line carries `"source"` so you can see it, change it or delete it, and re-running adds nothing new.
5. Fill in the half Figma has no way to express — guards, list data-binding, app hooks (contract: [`spec/flow-events.md`](spec/flow-events.md)) — then check it with `python3 figma2html/scripts/flow_check.py flow.json`; a mistyped node id is otherwise only a console warning you'd hit by clicking. Now pick a backend.

Every step above is runnable with no Figma account: `examples/login/nodes.json` is a real-shaped REST response, and importing it reproduces the demo's `stage` / `caps` / `base` / `modals` exactly — the remaining `list`, `bindings` and guards are precisely the application semantics you write by hand.

## Install as agent skills

Each skill folder is a self-contained agent skill — a `SKILL.md` carrying YAML frontmatter plus the scripts it names, no build step and no dependencies beyond Python. Two hosts are verified.

### Claude Code

The repo doubles as a plugin marketplace:

```shell
/plugin marketplace add ProdaZhang/figkit
/plugin install figma2godot@figkit      # or figma2html / figma2dsl / figma2unity / figma2cocos / figkit-motion
```

Prefer no plugin machinery? Just copy a folder into `.claude/skills/`.

### DeepSeek Harness

Copy a folder into either skill root — user-wide, or scoped to one project:

```shell
cp -r figma2html ~/.dsh/skills/                  # user-wide
cp -r figma2html <projectRoot>/.dsh/skills/      # this project only; outranks the user root
```

No restart needed: the local provider watches both roots and attaches to one you create while it is running. Invoke with `/figma2html` in the composer — DSH injects the skill body together with a `Base directory for this skill: <path>` hint, which is what makes the relative script paths written throughout each `SKILL.md` resolve.

Verified against DSH `0.1.0-rc.8`: all six skills discovered and listed with their descriptions, and `figma2html`'s own suite (94 assertions, 6 modules) run green from inside a session.

Per-skill usage lives in its `SKILL.md`.

**What a skill install leaves behind.** [`tools/`](tools/) — `design-diff` (pixel-diff against a Figma export), `html-smoke`, `conformance`, `spec_parity` — sits at the repo root, outside every skill folder, so a skill-only install does not get it. Clone the repo when you want to measure fidelity rather than just produce it. One portability note: every `SKILL.md` spells the interpreter `python3`, which usually does not exist on Windows — use `python` there.

> **Language note (honest version)**: English covers **this README, `CONTRIBUTING.md`, and the [`spec/`](spec/) IR contract** — the parts you need to understand or extend the format. Still **zh-CN**: the six `SKILL.md` usage docs, every `references/mapping.md` (including the known-loss tables), and all of `figkit-motion/`. Always language-independent: all code, all tests, all JSON/field names. The zh original of the spec is mirrored at `spec/*.zh.md`, and `tools/spec_parity.py` compares the two so the schema can't drift apart. Translating one backend's `mapping.md` is the highest-value PR — see [Translation in CONTRIBUTING](CONTRIBUTING.md#translation).

## Design principles

- **IR spec is frozen** ([`spec/`](spec/), v1.0): additive evolution only; backends never extend it privately.
- **Honest degradation**: what an engine can't render is listed in that backend's `references/mapping.md` known-loss table and logged at generation/runtime — never dropped silently.
- **Curves are solved, never approximated by name.** Figma hands over a specific curve — `cubic-bezier(.32,.72,0,1)`, or a spring's `{mass, stiffness, damping}`. Every engine also ships easing *enums* that share those names and have different shapes. Picking "the closest enum" per backend is how one IR becomes five different feels while every test stays green — the measured gap between `easeOutCubic` and `cubic-bezier(.23,1,.32,1)` is **19.8 percentage points**, right in the opening moments. So `motion.py` samples the real curve (Newton inversion for béziers, the analytic solution for springs) and the conformance suite compares the sampled points backend against backend. What Figma doesn't publish control points for (`BOUNCY`, `*_BACK`) stays `unresolved` rather than being guessed.
- **Deterministic converters** (stdlib-only, no timestamps) guarded by golden tests; capture has a byte-parity guard across its two copies.
- **Engine vs app-hook split**: engines own structure & mechanics (modals, guards, cloning); your code owns domain semantics via a small hook interface — identical shape in JS, C#, GDScript and TS.

## Scope (what it is not)

- It reproduces **UI screens and UI flow**, not gameplay. Real-time feel, networking and business logic stay downstream.
- Rotation of instance-internal nodes isn't provided by the Figma REST API (documented limitation; the escape hatch is an app-hook override).
- Vector clusters rasterize to PNG — the only unavoidable fidelity loss, independent of any backend.

## Lineage

FigKit grew out of [aigd](https://github.com/ProdaZhang/aigd) (中文 [aigd-zh](https://github.com/ProdaZhang/aigd-zh)) / [aidd](https://github.com/ProdaZhang/aidd) (AI-assisted design→dev methodology): `figma2dsl` feeds their UI-DSL knowledge layer, and the engine backends are the first concrete slice of their "implementation layer". Each project stands alone.

## License

[MIT](LICENSE) © 2026 ProdaZhang. Not affiliated with or endorsed by Figma, Inc.
