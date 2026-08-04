> **FigKit IR Spec v1.3 — 2026-08-05** (v1.0 frozen 2026-07-03)
> This file is the **authoritative** copy of the IR contract shared by the six backends (html/dsl/unity/godot/unreal/cocos);
> the same-named file under `figma2html/references/` is the working copy shipped with the skill (same content).
> Freeze discipline: from v1.0 on, changes are **additive only** (new optional fields / enum values); existing field shapes do not change.
> The next structural change must be triggered by a real gap hit by some backend, bump to v1.1, and be recorded in the changelog line below.
> Changelog: v1.0 (2026-07-03) frozen — cross-validated by 6 backends (html render / dsl transcription / unity compile+import / godot in-engine render / unreal strong typing / cocos checker).
> v1.1 (2026-08-04) additive: **`clip`** — a Figma `isMask` layer is a clipping *shape*, not a layer of paint. Capture used to emit it as an ordinary node: a gradient rectangle whose only job was to give its siblings a rounded outline got painted over the panel it was masking, and the decoration it was supposed to clip (a 2143×680 ellipse) spilled across the whole screen. Now a mask that is a rectangle/ellipse covering its parent's box folds into the parent as `clip: true` + the mask's radius, and is not painted; anything else degrades loudly (`[capture][known-loss]` on stderr) rather than pretending. **Honoured by html only so far** — the other four backends ignore the field, which is exactly the behaviour they had before, so nothing regresses; each should declare render/approximate/drop in its `mapping.md` when it gets there.
> v1.2 (2026-08-04) additive, three fields, all from the same discovery: **things Figma does not store as images must not become images.** `paths` + `viewBox` — with `geometry=paths` on the REST call Figma hands back every vector's SVG path (`fillGeometry` / `strokeGeometry`), so a vector is *drawn*, not downloaded: no `/v1/images` render quota (which does get exhausted — 11 backoffs, 41 clusters, zero delivered), resolution-independent, recolourable without re-exporting, and downstream engines receive geometry instead of a bitmap. `strokeGeometry` is Figma's stroke already converted to a fillable outline, so it is painted as a fill in the stroke colour and needs no stroke-width maths; because the round caps of a stroke overflow `absoluteBoundingBox`, an element carrying paths is sized by `absoluteRenderBounds` with `viewBox` shifted back by the difference. `borderAlign` — Figma strokes are `INSIDE` / `OUTSIDE` / `CENTER` and CSS `border` only draws inward; mapping all three to `border` drew every OUTSIDE stroke in the wrong direction (eating N px of fill instead of adding N px outside — a 10px stroke was off by 20px). Inside stays `border`, outside becomes a `0 0 0 Npx` entry at the head of `shadow` (box-shadow follows `border-radius`, `outline` does not), centre splits. `clip` also now carries Figma's `clipsContent`, not just masks. **Honoured by html only so far**; the other four ignore all three, which is the behaviour they already had.
> Translated to English 2026-07-28; the original zh-CN text is kept alongside as `<name>.zh.md` (mirror, not authority).
> v1.3 (2026-08-05) — no new fields; three **resolutions moved into capture**, because each one was a question only Figma could answer and every backend was guessing differently. `text.wrap` (additive, from `textAutoResize`): fixed-width text wraps, auto-width text does not — previously html guessed it with a runtime hook the engines had no equivalent of. **Text geometry is now the line box**: Figma places a line block of `lh` per `textAlignVertical`, and — measured against `absoluteRenderBounds` on real text — *centres* that block when it overflows a shorter box instead of top-anchoring it. Neither Godot's `Label` nor Unity's UI Toolkit has line-height, so single-line text now ships with `y`/`h` already resolved to the line box and `alignV: "center"`; every backend only has to centre inside a box (Godot was 12px low, Unity 8.5px high). Multi-line boxes are untouched. **Stroke bands arrive pre-clipped**: Figma's `strokeGeometry` is a ±w band straddling the edge, and shipping it raw with a `clip` hint made boolean clipping the price of admission — backends without it (Painter2D) drew every stroke at double width. Capture now splits the band and emits shape + inset/outset outline as one even-odd ring, `clip` cleared; bands it cannot read fall back to the old raw+hint form, which is why `clip` on a path stays in the contract.

# .ui.json — the full-fidelity render source (produced by figma_capture.py)

A full-fidelity structured snapshot of one Figma frame: every visible node plus all of its styling, flattened to absolute coordinates and nested by id.
`render.js` reads it and rebuilds the DOM 1:1 (CSS applied node by node).

```jsonc
{
  "spec": "1.3",                          // IR contract version this capture follows (see spec/)
  "frame": "46:8241", "w": 1080, "h": 1920,
  "stageBg": "url(_assets/s17/bg.png) center/cover no-repeat",   // frame backdrop (solid colour / gradient also allowed)
  "els": [{
    "id": "46:8265", "name": "Frame 96", "type": "FRAME",
    "parent": "46:8263",                  // figma parent id (render nests by it; same key space, joinable with DSL/flow)
    "x": 199, "y": 538, "w": 684, "h": 802, "z": 26,   // absolute px within the frame + stacking order
    "rot": 0, "opacity": 1,
    "radius": "37px", "border": "4.0px solid rgba(219,208,184,1)", "shadow": "0px 4px 0px rgba(0,0,0,0.6)", "blur": "",
    "fill": "rgba(255,251,242,1)",        // solid incl. alpha / linear or radial gradient css / empty
    "img": "", "imgSize": "",             // image fill (named after imageRef, shared across screens)
    "clip": false,                         // v1.1: true = clip children to this box (a figma isMask sibling folded in; its radius lands in `radius`)
    "paths": [], "viewBox": "",            // v1.2: vector drawn from figma geometry — [{d, rule, fill}] + the svg viewBox (sized by renderBounds)
    "borderAlign": "",                     // v1.2: "inside" | "outside" | "center" — where the stroke sits; outside/centre also land in `shadow`
    "vec": false,                          // true = collapsed vector cluster (missing PNG degrades to transparent, never a flat black)
    "text": null                           // TEXT only: {content,color,size,family,weight,lh,ls,alignH,alignV,textAlign,wrap,stroke}
  }]
}
```

- `spec` names the IR contract version the file was captured against. It is **advisory**: consumers treat a missing field as `"1.0"` (files captured before the field existed), ignore a differing *minor* (the freeze discipline makes those additive, so an older backend simply doesn't see the new optional fields), and warn on a differing *major* rather than refuse — a loud "I am reading this by the old rules" beats silence.
- Geometry is absolute px relative to the frame origin; `render.js` converts to parent-relative while nesting.
- For **TEXT**, that box is the *line box* (v1.3): `y`/`h` are already resolved from Figma's text frame + `lh` + `textAlignVertical`, and `alignV` is `center`, so a backend without line-height still lands the glyphs where Figma draws them. Boxes tall enough for two or more lines are left as Figma reports them.
- `subtreeOf(cap, rootId | [rootId, ...])` extracts a subtree (used for modal overlays).
- Full per-field semantics live in figma2dsl's `references/界面DSL规范-figma2dsl扩展.md` §C/§0 (still zh-CN).

## Known limitation: rotation (rot)

`rot` is recovered by `geom()` from the node's `relativeTransform` (`atan2(m[1][0], m[0][0])`). **The Figma REST API often omits `relativeTransform` for nodes inside a component instance (INSTANCE/COMPONENT)** — for those nodes `rot` **falls back to 0** (and when a whole cluster is collapsed into an image, its interior angles are lost the same way). This is a property of the Figma API, **not a capture bug**, and cannot be repaired at the capture layer.

**Escape hatch = the app hook**: when a node genuinely needs its angle (or any other visual capture cannot see, or that you want to override), locate the cloned element by `data-id` / `data-name` in `app.js` and set it yourself — e.g. for a diamond gem, `el.style.transform='rotate(45deg)'`. Capture provides ground truth; design overrides belong to the hook — see "engine vs hook" in the SKILL doc for the split.
