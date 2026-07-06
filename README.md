# FigKit — one Figma capture, six runnable outputs

[![tests](https://github.com/ProdaZhang/figkit/actions/workflows/tests.yml/badge.svg)](https://github.com/ProdaZhang/figkit/actions/workflows/tests.yml)

*Turn a Figma frame into a runnable client — **HTML, Unity, Godot, Unreal, Cocos Creator** — plus a semantic UI-DSL, all compiled from one pixel-faithful intermediate representation with **declared interactions** (modals, guards, data binding) that Figma itself doesn't carry.*

```
figma REST ──► figma_capture ──►  IR: <screen>.ui.json (pixels) + flow.json (behavior)
                                   │        spec/ v1.0 FROZEN — the shared contract
        ┌──────────┬───────────┬───┴───────┬───────────┬───────────┐
        ▼          ▼           ▼           ▼           ▼           ▼
   figma2html  figma2dsl  figma2unity figma2godot figma2unreal figma2cocos
   runnable    semantic   UXML+USS +  .tscn +     uespec +     Creator TS
   HTML client UI-DSL(md) FlowBinder  GDScript    C++ widget   interpreter
```

**What makes it different from figma-to-code exporters:** the **flow layer**. Figma has no interaction logic, so FigKit declares it in `flow.json` — keyed by Figma node ids (survives re-capture), with modals, guards, list data-binding and a clean engine-vs-app-hook split. Every backend implements the *same* flow semantics, so one declaration runs everywhere.

## Status matrix (honest, per verification level)

| backend | offline tests | in-engine verification |
|---|---|---|
| figma2html | ✅ | ✅ rendered + interactions (Edge headless screenshot) |
| figma2dsl | ✅ | ✅ (same render pipeline) |
| figma2godot | ✅ 16 | ✅ **Godot 4.3**: .tscn rendered, pixel-compared vs HTML; GDScript compiles clean |
| figma2unity | ✅ 11 | ✅ **Unity 6000.4.8f1**: C# compiles zero-warning, UXML/USS pass Unity's importer, CloneTree structure asserted (visual pass pending) |
| figma2unreal | ✅ 10 | ⏳ source + integration guide; not yet compiled in UE (risk self-assessment in `references/mapping.md`) |
| figma2cocos | ✅ 7 | ⏳ source + integration guide; not yet run in Creator |

Same IR geometry rendered by two independent backends:

| HTML (Edge) | Godot 4.3 |
|---|---|
| ![login rendered in HTML](docs/shots/login-html.png) | ![login rendered in Godot](docs/shots/login-godot.png) |

## Try it (no Figma account needed, ~1 minute)

The login example is fully self-contained — its three screens are *synthesized* through the real capture pipeline:

```bash
cd figma2html
python -m http.server 8321
# open http://localhost:8321/examples/login/app.html
# click through: notice modal, server list (row cloning), agreement guard, enter
```

Then compile the same screens for an engine:

```bash
python figma2godot/scripts/ui_to_tscn.py  figma2html/examples/login/screen-login.ui.json  out/
python figma2unity/scripts/ui_to_unity.py figma2html/examples/login/screen-login.ui.json out/
```

## Real Figma input

1. Get a personal access token (scope `file_content:read` only). It is read by a single subprocess and never written to disk.
2. `GET /v1/files/<key>/nodes?ids=<frame>` → `nodes.json`
3. `python figma2html/scripts/figma_capture.py nodes.json <frameId> s01 <assetDir> assets out/screen-01`
4. Write `flow.json` (contract: [`spec/flow-events.md`](spec/flow-events.md)) and pick a backend.

Per-skill usage lives in each `figma2*/SKILL.md`; the folders double as [Claude Code skills](https://docs.claude.com/en/docs/claude-code) — drop any of them into `.claude/skills/` and the workflow becomes conversational.

## Design principles

- **IR spec is frozen** ([`spec/`](spec/), v1.0): additive evolution only; backends never extend it privately.
- **Honest degradation**: what an engine can't render (blur, gradients, text-stroke…) is listed in that backend's `references/mapping.md` known-loss table and logged at generation/runtime — never dropped silently.
- **Deterministic converters** (stdlib-only, no timestamps) guarded by golden tests; capture has a byte-parity guard across its two copies.
- **Engine vs app-hook split**: engines own structure & mechanics (modals, guards, cloning); your code owns domain semantics via a small hook interface — identical shape in JS, C#, GDScript, C++ and TS.

## Scope (what it is not)

- It reproduces **UI screens and UI flow**, not gameplay. Real-time feel, networking and business logic stay downstream.
- Rotation of instance-internal nodes isn't provided by the Figma REST API (documented limitation; the escape hatch is an app-hook override).
- Vector clusters rasterize to PNG — the only unavoidable fidelity loss, independent of any backend.

## Lineage

FigKit grew out of [aigd](https://github.com/ProdaZhang/aigd) (中文 [aigd-zh](https://github.com/ProdaZhang/aigd-zh)) / [aidd](https://github.com/ProdaZhang/aidd) (AI-assisted design→dev methodology): `figma2dsl` feeds their UI-DSL knowledge layer, and the engine backends are the first concrete slice of their "implementation layer". Each project stands alone.

## License

[MIT](LICENSE) © 2026 ProdaZhang. Not affiliated with or endorsed by Figma, Inc.
