# Contributing guide (FigKit)

## Running tests

One entry point, works on Windows / macOS / Linux, pure stdlib, no pytest:

```bash
python3 tools/run_all_tests.py            # spec parity + cross-backend conformance + all six suites
python3 tools/run_all_tests.py godot dsl  # just those backends
python3 tools/run_all_tests.py --list     # what's available
```

Each backend's `scripts/tests/run_all.py` discovers its own `test_*.py` and exits nonzero on failure; you can still run one directly while iterating.

CI (`.github/workflows/tests.yml`) runs the same script on **ubuntu / windows / macos** with the current Python, plus one **Python 3.9** leg on ubuntu that fixes the supported floor. A change must keep every leg green.

## Core principles (understand before changing)

1. **The IR is the spine.** `spec/ui.json-schema.md` + `spec/flow-events.md` are **v1.0 FROZEN**: additive changes only (new optional fields / enum values); a structural change needs a real gap hit by a backend, and bumps the spec version. Backends consume the IR — they never invent private extensions to it.
2. **One capture, master copy in `figma2html/scripts/figma_capture.py`.** `figma2dsl` carries a byte-identical mirror guarded by `figma2dsl/scripts/tests/test_capture_parity.py`. Change capture in figma2html first, then sync the mirror.
3. **Preview = runtime, locked by tests.** `figma_capture.py rec_to_css` and `runtime/render.js applyRecStyle` are the same styling logic in two places; a whitespace-parity test guards them. Keep any style change in both.
4. **Honest degradation (known-loss).** When a backend cannot represent an IR feature (blur, gradients, text-stroke, …) it must degrade *loudly*: an entry in that backend's `references/mapping.md` known-loss table, plus a generated-file header comment or a log line at generation/runtime. Never drop silently. **This is enforced**, not just documented — see the conformance suite below.
5. **Cross-backend conformance.** Per-backend tests only compare a backend against its own hand-written expectations; nothing there notices when two backends read the same IR differently. `tools/conformance/` closes that gap: one `kitchen-sink.ui.json` exercising every visual feature, and `expectations.json` where each backend declares, per feature, whether it renders it, approximates it, or drops it. The suite then checks the declaration against the real artifact, that every approximation/drop leaves a trace, and that it is actually written down in that backend's `mapping.md`. Adding an IR feature or a backend means extending both files. (This is how `radius: "50%"` — which capture emits for *every* Figma ellipse — was found silently dropped by the Godot backend and misread as `50px` by the Cocos one, while every existing test stayed green.)
6. **Converters are deterministic**: argv-driven, pure stdlib, no timestamps/randomness — same input, byte-identical output, enforced by per-backend golden tests.
7. **Project-neutral**: no real product names, protocol ids, or Figma file keys in code or fixtures. File keys come from `FIGMA_FILE_KEY` / `--file-key`; screen metadata comes from an external `--meta` file. `FIGMA_TOKEN` is read by a single subprocess and never written to any file.
8. **Engine-side code states its verification level.** Python is test-verified here; C# / GDScript / C++ / TS declare in their file headers what has and hasn't been verified in-engine (compile / import / render / interaction). Update the header when you raise the level — never claim beyond it.

## How to add things

- **A new backend (`figma2<engine>/`)**: consume the IR only (no capture); implement the flow semantics of `figma2html/runtime/assemble.js` (base + modal overlay, guards, toggleFlag/send, list row cloning, checkbox binding); ship `SKILL.md`, `references/mapping.md` (full mapping + known-loss), and an offline `scripts/tests/` suite with a golden test against the shared login fixtures.
- **A converter change**: keep goldens intentional — regenerate them in the same PR and note the mapping change in `mapping.md`.
- **A capture change**: figma2html first (see principle 2), keep the whitespace-parity test green.

## Translation

`spec/` is English (done — the zh original lives on as `spec/*.zh.md`). Most other prose is still **zh-CN**. Translation is the easiest way to contribute: no Figma account, no engine install, no deep knowledge of the pipeline. Priority order, highest value first:

1. **One backend's `references/mapping.md`** — the full IR→engine mapping plus its known-loss table, ~100 lines. Pick the engine you actually use; this is what a user reads to know what will and won't survive the conversion.
2. **`SKILL.md` files** — usage docs for each skill.
3. **`figma2html/examples/login/README.md`** — the demo walkthrough.

Conventions for translations:

- Keep the file path and name unchanged. Only add a `<name>.zh.md` mirror when the zh version must remain readable to its maintainer — that's what `spec/` does.
- Keep all identifiers, field names, code blocks and table structure byte-identical. Don't "improve" a technical claim while translating: if you think one is wrong, open an issue instead.
- `spec/` has two guards, both in `tools/spec_parity.py`: the English file must stay byte-identical to the `figma2html/references/` shipped copy apart from the version header, and its **code blocks (comments stripped)** must still match `spec/*.zh.md`, so a schema change can't land in one language only.
- Tests must stay green: `python3 tools/run_all_tests.py`.

## Conventions

- Files are **UTF-8 without BOM**; use `/` paths cross-platform.
- Skill folders are self-contained and installable individually (Claude Code `.claude/skills/`, and the same SKILL.md layout works on other harnesses).
- This repo is the **source of truth**; copies installed into projects are downstream installs.
