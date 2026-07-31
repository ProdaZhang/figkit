# flow.json — the flow / event declaration (assembler contract)

`assemble.js` reads `flow.json` and assembles "base screen + modal overlays + events + bindings" into a runnable client.
**This is where Events live on the Figma route.** Figma *does* carry interactions — the REST API exposes `interactions[]` (triggers, `NAVIGATE`/`OVERLAY`/`BACK`, conditionals, variables) — and `flow_from_figma.py` imports them into the skeleton below. But those are **prototype semantics**: which frame to jump to, played inside Figma against static frames. What a shipping client needs on top — guards over app state, list rows cloned from real data, a boundary between engine mechanics and domain code — has no representation in Figma at all, and is declared here by hand. Either way Events are keyed by **Figma node id**, so they survive re-capture (re-importing pixels never touches them). The syntax mirrors the `## Events` section of the aigd UI-DSL (`<trigger> <element> [guard] -> result`).

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
- **events[]**: `on` (currently `click`) + `el` (a Figma node id; an array means several elements trigger the same action; the special forms are `@any:<modal>`, `@panelOutside:<modal>` and, since v1.1, `@in:<modal>:<nodeId>` — see below) + optional `guard` (all of these state keys must be truthy to pass) + `do` (the action) + `arg`.
- **`@in:<modal>:<nodeId>`** (v1.1): an element **inside** a modal. Until v1.1 `events[].el` could only name nodes on the **base** screen — every binder resolved ids against the base layer — so the single most common link in a real Figma file, *the ✗ button inside a popup*, had no representation at all. The v1.0 idioms `@any:` / `@panelOutside:` mean "click anywhere / outside", which is not "click this button". Parsing: everything after `@in:` up to the **first** colon is the modal name, and all the rest is the node id, because Figma ids contain colons (`@in:bag:4:99`). The node must be inside the subtree that modal actually lifts (its `roots`), not merely somewhere in that screen — the offline checkers verify exactly that, since a node outside `roots` is never in the layer at runtime. Binders stop propagation on it, or the `@any:` / `@panelOutside:` handler on the same layer fires too and pressing ✗ would also count as clicking outside.
- **Built-in `do`**: `openModal(arg)` / `closeModal` / `toggleFlag(arg)` / `send(arg)` (forwarded to the app's `send` action). Any other `do` name is looked up among the actions the app registered.
- **events[].transition** (optional, additive): the animation the designer attached to this link in Figma, carried through verbatim — `{ "type", "duration", "direction"?, "matchLayers"?, "easing": { "type", "bezier"?, "spring"? } }`. `type` is one of Figma's `DISSOLVE / SMART_ANIMATE / SCROLL_ANIMATE / MOVE_IN / MOVE_OUT / PUSH / SLIDE_IN / SLIDE_OUT`; `spring` keeps Figma's `{mass, stiffness, damping}` triple. **The IR records what the design said, not how a backend solves it** — the conversion to a decoupled (damping ratio, response) pair and the sampling of a curve into engine-native keyframes both happen backend-side (`motion.py` / `motion.ts`). A backend that cannot animate must declare the drop in its known-loss table. For the directional types, `direction` is the edge the panel travels **from**, and the distance it travels is **the stage's**, not the panel's own box: on a 1080×1920 stage an 860×1160 panel starts 1920px below its resting place, not 1160. v1.0 left that unsaid and the backends split two ways on it — same curve, same millisecond, one of them showing 380px of panel already on screen where the others showed none. Curve values alone can never catch that, so `tools/conformance` now pins the basis directly.
- **motion** (optional, additive): default motion for the mechanics the engine itself owns — `press` (pressed state for every event-bound element), `stagger` (list rows entering one after another), `guardFail` (the element saying "no"). Figma has no concept for any of these, so anything here is authored by `flow_from_figma.py --motion-defaults` from a named preset and carries `"source": "preset:<name>"`. **Written into the file, never injected at runtime** — you can see what was added, change it, or delete it. Priority is always **Figma > project override > preset**; the importer never touches a transition Figma declared, and re-running it adds nothing new.
- **Preset transition types**: alongside Figma's eight, `events[].transition.type` may be `SCALE_IN` / `SCALE_OUT` (`fromScale` / `toScale`, default `0.95`) — the default entrance and exit, which Figma's vocabulary has no name for. Never `scale(0)`: nothing in the real world grows out of nothing. Exits are deliberately **shorter** than entrances; a symmetrical open/close reads as slower than it is.
- **list**: declares which container inside which modal is a data list; `onRowClick` names an app action. The app injects rows carrying `data-row` via `app.renderRows(modal, container, items, rowFn)` (the parameter passed to `register(app)`, i.e. the global `FigApp`), and the engine delegates row clicks.
- **bindings.checkbox**: the two checkbox states are handled generically by the engine (filled + check mark / translucent + empty). Every other domain field — writing the chosen server back, row colouring, notice text — belongs to the app's `syncBindings(base)` and actions.

## The app hook (domain-only, never in the engine)

`app.js` exports `window.APPHOOK = { register(app), init(app, net) }`:

- `register`: `app.registerActions({ send, selectServer, onPush, syncBindings, onReady, onGuardFail })`
- `init`: late initialisation — e.g. `applyBoot`: fetch the server list → `app.renderRows(...)`, select the first entry by default, fill in the notice.

The engine owns **structure and mechanics** (base screen, modals, events, guards, checkbox, row cloning); the app owns **domain semantics** (server data → rows, writing the selection back, status colours).
