# Contributing guide (FigKit)

## Running tests

One entry point, works on Windows / macOS / Linux, pure stdlib, no pytest:

```bash
python3 tools/run_all_tests.py            # spec parity + all six suites
python3 tools/run_all_tests.py godot dsl  # just those backends
python3 tools/run_all_tests.py --list     # what's available
```

Each backend's `scripts/tests/run_all.py` discovers its own `test_*.py` and exits nonzero on failure; you can still run one directly while iterating.

CI (`.github/workflows/tests.yml`) runs the same script on **ubuntu / windows / macos** with the current Python, plus one **Python 3.9** leg on ubuntu that fixes the supported floor. A change must keep every leg green.

## Core principles (understand before changing)

1. **The IR is the spine.** `spec/ui.json-schema.md` + `spec/flow-events.md` are **v1.0 FROZEN**: additive changes only (new optional fields / enum values); a structural change needs a real gap hit by a backend, and bumps the spec version. Backends consume the IR — they never invent private extensions to it.
2. **One capture, master copy in `figma2html/scripts/figma_capture.py`.** `figma2dsl` carries a byte-identical mirror guarded by `figma2dsl/scripts/tests/test_capture_parity.py`. Change capture in figma2html first, then sync the mirror.
3. **Preview = runtime, locked by tests.** `figma_capture.py rec_to_css` and `runtime/render.js applyRecStyle` are the same styling logic in two places; a whitespace-parity test guards them. Keep any style change in both.
4. **Honest degradation (known-loss).** When a backend cannot represent an IR feature (blur, gradients, text-stroke, …) it must degrade *loudly*: an entry in that backend's `references/mapping.md` known-loss table, plus a generated-file header comment or runtime log. Never drop silently.
5. **Converters are deterministic**: argv-driven, pure stdlib, no timestamps/randomness — same input, byte-identical output, enforced by per-backend golden tests.
6. **Project-neutral**: no real product names, protocol ids, or Figma file keys in code or fixtures. File keys come from `FIGMA_FILE_KEY` / `--file-key`; screen metadata comes from an external `--meta` file. `FIGMA_TOKEN` is read by a single subprocess and never written to any file.
7. **Engine-side code states its verification level.** Python is test-verified here; C# / GDScript / C++ / TS declare in their file headers what has and hasn't been verified in-engine (compile / import / render / interaction). Update the header when you raise the level — never claim beyond it.

## How to add things

- **A new backend (`figma2<engine>/`)**: consume the IR only (no capture); implement the flow semantics of `figma2html/runtime/assemble.js` (base + modal overlay, guards, toggleFlag/send, list row cloning, checkbox binding); ship `SKILL.md`, `references/mapping.md` (full mapping + known-loss), and an offline `scripts/tests/` suite with a golden test against the shared login fixtures.
- **A converter change**: keep goldens intentional — regenerate them in the same PR and note the mapping change in `mapping.md`.
- **A capture change**: figma2html first (see principle 2), keep the whitespace-parity test green.

## Translation

Most prose in this repo is **zh-CN** (see the language note in the README). Translation is the easiest way to contribute and needs no Figma account, no engine install, and no deep knowledge of the pipeline. Priority order, highest value first:

1. **`spec/ui.json-schema.md` + `spec/flow-events.md`** (98 lines total) — the IR contract every backend depends on. Translating these unblocks everyone else.
2. **`figma2html/references/*.md`** — the working copies of the same two files. They must stay byte-identical to `spec/` except for the version header; `tools/spec_parity.py` enforces this, so translate both in the same PR and run it.
3. **One backend's `references/mapping.md`** — the full IR→engine mapping plus its known-loss table. Pick the engine you actually use.
4. **`SKILL.md` files** — usage docs for each skill.

Conventions for translations: keep the file path and name unchanged (an English mirror belongs at `<name>.en.md` only if the zh version must stay authoritative), keep all identifiers, field names, code blocks and table structure byte-identical, and do not "improve" the technical claims while translating — if you think a claim is wrong, open an issue instead. Tests must stay green (`python3 tools/run_all_tests.py`).

## Conventions

- Files are **UTF-8 without BOM**; use `/` paths cross-platform.
- Skill folders are self-contained and installable individually (Claude Code `.claude/skills/`, and the same SKILL.md layout works on other harnesses).
- This repo is the **source of truth**; copies installed into projects are downstream installs.
