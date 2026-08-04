# Contributing guide (FigKit)

## Running tests

One entry point, works on Windows / macOS / Linux, pure stdlib, no pytest:

```bash
python3 tools/run_all_tests.py            # spec parity + cross-backend conformance + all seven suites
python3 tools/run_all_tests.py godot dsl  # just those backends
python3 tools/run_all_tests.py --list     # what's available
```

Each backend's `scripts/tests/run_all.py` discovers its own `test_*.py` and exits nonzero on failure; you can still run one directly while iterating.

CI (`.github/workflows/tests.yml`) runs the same script on **ubuntu / windows / macos** with the current Python, plus one **Python 3.9** leg on ubuntu that fixes the supported floor. A change must keep every leg green.

## Core principles (understand before changing)

1. **The IR is the spine.** `spec/ui.json-schema.md` and `spec/flow-events.md` are both at **v1.1**, under the same discipline as the v1.0 freeze: additive changes only (new optional fields / enum values / new special selector forms); a structural change needs a real gap hit by a backend, and bumps the minor version. v1.1 is what that looks like in practice — `@in:<modal>:<nodeId>` landed only after the gap had sat recorded-but-unpatched in the spec since v1.0. Backends consume the IR — they never invent private extensions to it. Every capture stamps the version it followed into `.ui.json` as `spec`, and consumers treat it as **advisory**: missing means `"1.0"`, a differing minor is ignored (additive by construction), a differing major warns instead of refusing. Bumping the version means changing `IR_SPEC` in `figma_capture.py`, both spec files plus the zh mirror, and `IR_SPEC_SUPPORTED` in each backend that reads it.
2. **Broken references are caught offline.** `flow.json` is hand-written and holds nothing but Figma node ids pointing at screens, so a typo is the likeliest first mistake anyone makes. Every backend that consumes flow validates those references before doing any work — `figma2html/scripts/flow_check.py` and `figma2cocos/scripts/ui_check.py` — and exits 2 naming what is wrong. (html got its checker late: for a while a mistyped id there was only a browser console warning you'd discover by clicking and getting nothing.)
3. **Malformed IR gets a sentence, not a traceback.** Each artifact-emitting backend validates its input (`check_ir`) before converting: top-level shape, per-element `id` and geometry, no duplicate ids, no dangling `parent`. The check is duplicated per backend on purpose — skill folders must stay self-contained and installable individually, so cross-directory imports would break the moment one is installed as a plugin. What keeps the copies honest is the conformance suite: every backend must reject the same malformed inputs the same way.
4. **One capture, master copy in `figma2html/scripts/figma_capture.py`.** `figma2dsl` carries a byte-identical mirror guarded by `figma2dsl/scripts/tests/test_capture_parity.py`. Change capture in figma2html first, then sync the mirror.
5. **Preview = runtime, locked by tests.** `figma_capture.py rec_to_css` and `runtime/render.js applyRecStyle` are the same styling logic in two places; a whitespace-parity test guards them. Keep any style change in both.
6. **Honest degradation (known-loss).** When a backend cannot represent an IR feature (blur, gradients, text-stroke, …) it must degrade *loudly*: an entry in that backend's `references/mapping.md` known-loss table, plus a generated-file header comment or a log line at generation/runtime. Never drop silently. **This is enforced**, not just documented — see the conformance suite below.
7. **Cross-backend conformance.** Per-backend tests only compare a backend against its own hand-written expectations; nothing there notices when two backends read the same IR differently. `tools/conformance/` closes that gap: one `kitchen-sink.ui.json` exercising every visual feature, and `expectations.json` where each backend declares, per feature, whether it renders it, approximates it, or drops it. The suite then checks the declaration against the real artifact, that every approximation/drop leaves a trace, and that it is actually written down in that backend's `mapping.md`. Adding an IR feature or a backend means extending both files. (This is how `radius: "50%"` — which capture emits for *every* Figma ellipse — was found silently dropped by the Godot backend and misread as `50px` by the Cocos one, while every existing test stayed green.)
8. **Converters are deterministic**: argv-driven, pure stdlib, no timestamps/randomness — same input, byte-identical output, enforced by per-backend golden tests. One consequence worth knowing before you touch `motion.py`: its Newton iteration runs a **fixed** number of steps instead of exiting early on a tolerance. Early exit makes the step count depend on the last bit of the platform's libm, so the three-OS CI matrix would disagree on byte-compared goldens. Same reason samples are rounded to 6 decimals.
9. **Motion is solved once, mirrored byte-for-byte.** `figma2html/scripts/motion.py` is the master; `figma2godot` / `figma2unity` / `figma2cocos` carry byte-identical copies (self-containment again — see principle 3), and `tools/conformance` fails on any drift, then independently checks that all four bake the *same sampled points*. Land the edit on the master and run `python3 tools/sync_shared.py --sync` (no argument = check only); it also covers `figma_capture.py`'s second copy in `figma2dsl`, and refuses to run when a mirror is *newer* than the master, since that usually means the edit landed on the copy and syncing would delete it. Never map a Figma easing onto an engine's built-in enum: they share names and differ in shape, which is the silent-divergence trap this whole layer exists to close. If Figma doesn't publish control points for a named curve, leave it `unresolved` and let the caller log a known-loss — a curve that is 20 points off looks completely normal in the artifact and wrong on screen.
10. **Project-neutral**: no real product names, protocol ids, or Figma file keys in code or fixtures. File keys come from `FIGMA_FILE_KEY` / `--file-key`; screen metadata comes from an external `--meta` file. `FIGMA_TOKEN` is read by a single subprocess and never written to any file.
11. **Engine-side code states its verification level.** Python is test-verified here; C# / GDScript / C++ / TS declare in their file headers what has and hasn't been verified in-engine (compile / import / render / interaction). Update the header when you raise the level — never claim beyond it.

## How to add things

- **A new backend (`figma2<engine>/`)**: consume the IR only (no capture); implement the flow semantics of `figma2html/runtime/assemble.js` (base + modal overlay, guards, toggleFlag/send, list row cloning, checkbox binding); ship `SKILL.md`, `references/mapping.md` (full mapping + known-loss), and an offline `scripts/tests/` suite with a golden test against the shared login fixtures.
- **A converter change**: keep goldens intentional — regenerate them in the same PR and note the mapping change in `mapping.md`.
- **A capture change**: figma2html first (see principle 3), keep the whitespace-parity test green.

## Translation

`spec/` and all four backends' `references/mapping.md` are English (done — each zh original lives on as a `*.zh.md` mirror). Most other prose is still **zh-CN**. Translation is the easiest way to contribute: no Figma account, no engine install, no deep knowledge of the pipeline. Priority order, highest value first:

1. **`SKILL.md` files** — usage docs for each skill, and the largest remaining block of zh-only prose.
2. **`figma2html/examples/*/README.md`** — the demo walkthroughs.
3. **`figma2dsl/references/`** — the UI-DSL spec extension.

Conventions for translations:

- Keep the file path and name unchanged. Only add a `<name>.zh.md` mirror when the zh version must remain readable to its maintainer — that's what `spec/` does.
- Keep all identifiers, field names, code blocks and table structure byte-identical. Don't "improve" a technical claim while translating: if you think one is wrong, open an issue instead.
- `spec/` has two guards, both in `tools/spec_parity.py`: the English file must stay byte-identical to the `figma2html/references/` shipped copy apart from the version header, and its **code blocks (comments stripped)** must still match `spec/*.zh.md`, so a schema change can't land in one language only.
- `mapping.md` has its own guard in `tools/conformance`: table row counts must match its `.zh.md`, code blocks that are real code (no CJK) must match byte for byte, and the English file must contain no CJK at all. **A mirror nobody guards will drift, and a drifted mirror is worse than none — it still looks true.** Prose can differ; structure cannot. Land edits in English first, then mirror.
- Tests must stay green: `python3 tools/run_all_tests.py`.

## Conventions

- Files are **UTF-8 without BOM**; use `/` paths cross-platform.
- Skill folders are self-contained and installable individually (Claude Code `.claude/skills/`, and the same SKILL.md layout works on other harnesses).
- This repo is the **source of truth**; copies installed into projects are downstream installs.
