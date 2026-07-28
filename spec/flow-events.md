> **FigKit IR Spec v1.0 — FROZEN 2026-07-03**
> This file is the **authoritative** copy of the IR contract shared by the six backends (html/dsl/unity/godot/unreal/cocos);
> the same-named file under `figma2html/references/` is the working copy shipped with the skill (same content).
> Freeze discipline: from v1.0 on, changes are **additive only** (new optional fields / enum values); existing field shapes do not change.
> The next structural change must be triggered by a real gap hit by some backend, bump to v1.1, and be recorded in the changelog line below.
> Changelog: v1.0 (2026-07-03) frozen — cross-validated by 6 backends (html render / dsl transcription / unity compile+import / godot in-engine render / unreal strong typing / cocos checker).
> Translated to English 2026-07-28; the original zh-CN text is kept alongside as `<name>.zh.md` (mirror, not authority).

# flow.json — the flow / event declaration (assembler contract)

`assemble.js` reads `flow.json` and assembles "base screen + modal overlays + events + bindings" into a runnable client.
**This is where Events live on the Figma route**: Figma carries no interaction logic, so Events are **hand-written** here, referenced by **Figma node id**, and survive re-capture (re-importing pixels never touches them). The syntax mirrors the `## Events` section of the aigd UI-DSL (`<trigger> <element> [guard] -> result`).

## Structure

```jsonc
{
  "stage": { "w": 1080, "h": 1920 },
  "caps": {                              // name → .ui.json path (one full-fidelity capture per screen)
    "base": "/screen-15.ui.json",
    "notice": "/screen-16.ui.json",
    "serverlist": "/screen-17.ui.json"
  },
  "base": "base",                        // the base screen (always mounted)
  "modals": {                            // modal = a panel subtree lifted out of some screen and overlaid
    "notice":     { "cap": "notice",     "roots": ["45:7040"] },
    "serverlist": { "cap": "serverlist", "roots": ["46:8246","46:8279","46:8280","46:8277","49:7736","46:8263"], "panel": "46:8263" }
  },
  "state":   { "agreed": false, "selected": null },   // initial state (flags / values)
  "events": [
    { "on":"click", "el":"45:7002",            "do":"openModal",  "arg":"notice" },
    { "on":"click", "el":["45:6993","45:6997"], "do":"openModal",  "arg":"serverlist" },
    { "on":"click", "el":"45:7006",            "do":"toggleFlag", "arg":"agreed" },
    { "on":"click", "el":"45:6998", "guard":["agreed","selected"], "do":"send", "arg":"Enter" },
    { "on":"click", "el":"@panelOutside:serverlist", "do":"closeModal" },
    { "on":"click", "el":"@any:notice",        "do":"closeModal" }
  ],
  "list": { "modal":"serverlist", "container":"46:8265", "onRowClick":"selectServer" },
  "bindings": {
    "checkbox": { "el":"45:7008", "flag":"agreed", "checkedBg":"rgba(255,255,255,1)",
                  "uncheckedBg":"rgba(255,255,255,0.2)", "mark":"✓", "markColor":"rgba(27,76,87,1)" }
  }
}
```

## Fields

- **caps / base / modals**: a screen is the `.ui.json` of a complete Figma frame; `base` stays mounted; `modals[*].roots` lists the top-level node ids to lift out and overlay (a modal is often several top-level siblings — outer frame + tabs + list — hence an array); `panel` is what "click outside the panel to close" tests against.
- **events[]**: `on` (currently `click`) + `el` (a Figma node id; an array means several elements trigger the same action; the special forms are `@any:<modal>` and `@panelOutside:<modal>`) + optional `guard` (all of these state keys must be truthy to pass) + `do` (the action) + `arg`.
- **Built-in `do`**: `openModal(arg)` / `closeModal` / `toggleFlag(arg)` / `send(arg)` (forwarded to the app's `send` action). Any other `do` name is looked up among the actions the app registered.
- **list**: declares which container inside which modal is a data list; `onRowClick` names an app action. The app injects rows carrying `data-row` via `app.renderRows(modal, container, items, rowFn)` (the parameter passed to `register(app)`, i.e. the global `FigApp`), and the engine delegates row clicks.
- **bindings.checkbox**: the two checkbox states are handled generically by the engine (filled + check mark / translucent + empty). Every other domain field — writing the chosen server back, row colouring, notice text — belongs to the app's `syncBindings(base)` and actions.

## The app hook (domain-only, never in the engine)

`app.js` exports `window.APPHOOK = { register(app), init(app, net) }`:

- `register`: `app.registerActions({ send, selectServer, onPush, syncBindings, onReady, onGuardFail })`
- `init`: late initialisation — e.g. `applyBoot`: fetch the server list → `app.renderRows(...)`, select the first entry by default, fill in the notice.

The engine owns **structure and mechanics** (base screen, modals, events, guards, checkbox, row cloning); the app owns **domain semantics** (server data → rows, writing the selection back, status colours).
