# .ui.json — the full-fidelity render source (produced by figma_capture.py)

A full-fidelity structured snapshot of one Figma frame: every visible node plus all of its styling, flattened to absolute coordinates and nested by id.
`render.js` reads it and rebuilds the DOM 1:1 (CSS applied node by node).

```jsonc
{
  "spec": "1.5",                          // IR contract version this capture follows (see spec/)
  "frame": "46:8241", "w": 1080, "h": 1920,
  "stageBg": "url(_assets/s17/bg.png) center/cover no-repeat",   // frame backdrop (solid colour / gradient also allowed)
  "els": [{
    "id": "46:8265", "name": "Frame 96", "type": "FRAME",
    "parent": "46:8263",                  // figma parent id (render nests by it; same key space, joinable with DSL/flow)
    "x": 199, "y": 538, "w": 684, "h": 802, "z": 26,   // absolute px within the frame + stacking order
    "rot": 0, "opacity": 1,
    "matrix": [1, 0, 0, 1, 199, 538],      // optional: local box -> frame affine transform, supersedes x/y/rot
    "vectorShadows": [],                   // optional: [{x,y,blur,spread,color}], blur = Gaussian sigma
    "radius": "37px", "border": "4.0px solid rgba(219,208,184,1)", "shadow": "0px 4px 0px rgba(0,0,0,0.6)", "blur": "",
    "fill": "rgba(255,251,242,1)",        // solid incl. alpha / linear or radial gradient css / empty
    "img": "", "imgSize": "", "imgPos": "",   // image fill (named after imageRef, shared across screens);
                                          // v1.4: figma crop fills carry px size + px offset here, else "cover"/"" (centred)
    "clip": false,                         // v1.1: true = clip children to this box (a figma isMask sibling folded in; its radius lands in `radius`)
    "paths": [], "viewBox": "",            // v1.2: vector drawn from figma geometry — [{d, rule, fill}] + the svg viewBox (sized by renderBounds)
    "borderAlign": "",                     // v1.2: "inside" | "outside" | "center" — where the stroke sits; outside/centre also land in `shadow`
    "vec": false,                          // true = collapsed vector cluster (missing PNG degrades to transparent, never a flat black)
    "text": null                           // TEXT only: {content,color,size,family,weight,lh,ls,alignH,alignV,textAlign,wrap,stroke}
  }],
  "losses": []                             // optional: [{nodeId,property,code,disposition,message}]
}
```

- `spec` names the IR contract version the file was captured against. It is **advisory**: consumers treat a missing field as `"1.0"` (files captured before the field existed), ignore a differing *minor* (the freeze discipline makes those additive, so an older backend simply doesn't see the new optional fields), and warn on a differing *major* rather than refuse — a loud "I am reading this by the old rules" beats silence.
- Geometry is absolute px relative to the frame origin; `render.js` converts to parent-relative while nesting.
- For **TEXT**, that box is the *line box* (v1.3): `y`/`h` are already resolved from Figma's text frame + `lh` + `textAlignVertical`, and `alignV` is `center`, so a backend without line-height still lands the glyphs where Figma draws them. Boxes tall enough for two or more lines are left as Figma reports them.
- `subtreeOf(cap, rootId | [rootId, ...])` extracts a subtree (used for modal overlays).
- Full per-field semantics live in figma2dsl's `references/界面DSL规范-figma2dsl扩展.md` §C/§0 (still zh-CN).

## v1.5 fidelity additions

- `matrix` is an optional six-number CSS/SVG affine matrix mapping the record's local box to the **frame**, not its parent. HTML derives the relative transform as inverse(parent matrix) times child matrix, with transform-origin 0 0 and one border-inset correction. It supersedes `x/y/rot`; `w/h` remain local box dimensions. Missing matrix means legacy geometry. Subtree extraction keeps frame placement. Transformed branches require source transforms; missing ones are reported.
- `text.decoration`: optional `none`, `underline`, or `line-through`. Uniform character overrides are resolved on the parent. Optional `text.runs` is an ordered array of full styles `{content,decoration,color,size,family,weight,ls}`; concatenated content equals `text.content`. Override offsets are UTF-16 code units. Mixed text uses inline spans inside one line wrapper, not sibling flex items.
- `vectorShadows` replaces rectangular `shadow` for path nodes in HTML. Each entry is `{x,y,blur,spread,color}` in local px; blur is sigma (Figma radius / 2), spread uses alpha morphology. Multiple shadows independently sample SourceAlpha and merge behind SourceGraphic. The old shadow string remains for legacy consumers; do not draw both.
- One-seed RELATIVE LINEAR horizontal/vertical repeats are expanded into regular records, including nested repeats. Original seed IDs remain; generated IDs are deterministic and collision-checked. Max count 1024, max expanded records 20000; unsupported/oversized modifiers are reported, not guessed.
- `losses` lists known capture degradations; it is **not** a completeness certificate. CUSTOM paint, multiple fills, unsupported effects/repeats and missing transforms are reported. CLI `--strict` returns 1 on known losses or missing assets, while keeping diagnostic outputs.
- HTML renders matrix, decoration/runs and vectorShadows. DSL keeps these in the capture sidecar but its semantic markdown drops them. Unity/Godot/Cocos currently **drop** these new semantics and must report them; expanded repeats use ordinary records, but transformed repeats still need matrix support. See each backend's mapping. No engine pixel acceptance is implied.

## Known limitation: missing source rotation (rot)

`rot` is recovered by `geom()` from the node's `relativeTransform` (`atan2(m[1][0], m[0][0])`). **The Figma REST API often omits `relativeTransform` for nodes inside a component instance (INSTANCE/COMPONENT)** — for those nodes `rot` **falls back to 0** (and when a whole cluster is collapsed into an image, its interior angles are lost the same way). This is a property of the Figma API, **not a capture bug**, and cannot be repaired at the capture layer.

**Escape hatch = the app hook**: when a node genuinely needs its angle (or any other visual capture cannot see, or that you want to override), locate the cloned element by `data-id` / `data-name` in `app.js` and set it yourself — e.g. for a diamond gem, `el.style.transform='rotate(45deg)'`. Capture provides ground truth; design overrides belong to the hook — see "engine vs hook" in the SKILL doc for the split.
