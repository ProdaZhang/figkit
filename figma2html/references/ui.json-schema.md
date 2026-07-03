# .ui.json — 全保真渲染真源(figma_capture.py 产)

一帧 figma 的"全保真结构化快照":每个可见节点 + 全部样式,扁平绝对坐标、按 id 嵌套。
`render.js` 读它 1:1 重建 DOM(逐节点贴 CSS)。

```jsonc
{
  "frame": "46:8241", "w": 1080, "h": 1920,
  "stageBg": "url(_assets/s17/bg.png) center/cover no-repeat",   // 帧底图(纯色/渐变亦可)
  "els": [{
    "id": "46:8265", "name": "Frame 96", "type": "FRAME",
    "parent": "46:8263",                  // figma 父 id(render 据此嵌套;同键空间可与 DSL/flow join)
    "x": 199, "y": 538, "w": 684, "h": 802, "z": 26,   // 相对帧绝对 px + 层级
    "rot": 0, "opacity": 1,
    "radius": "37px", "border": "4.0px solid rgba(219,208,184,1)", "shadow": "0px 4px 0px rgba(0,0,0,0.6)", "blur": "",
    "fill": "rgba(255,251,242,1)",        // 纯色含透明 / 线性·径向渐变 css / 空
    "img": "", "imgSize": "",             // 图片填充(按 imageRef 命名,跨屏复用)
    "vec": false,                          // true=矢量簇折叠图(缺 PNG 回退透明,不平涂黑)
    "text": null                           // 仅 TEXT:{content,color,size,family,weight,lh,ls,alignH,alignV,textAlign,stroke}
  }]
}
```

- 几何=相对帧原点的绝对 px;`render.js` 嵌套时转父相对。
- `subtreeOf(cap, 根id | 根id数组)` 抽子树(弹窗叠加用)。
- 完整字段语义见 figma2dsl 的 `references/界面DSL规范-figma2dsl扩展.md §C/§0`。

## 已知限制:旋转(rot)

`rot` 由 `geom()` 从节点的 `relativeTransform` 反解(`atan2(m[1][0], m[0][0])`)。**figma REST 对组件实例(INSTANCE/COMPONENT)内部子节点常不返回 `relativeTransform`**——这类节点的 `rot` 会**回退为 0**(整簇折叠成图时内部角度同样丢失)。这是 figma API 的特性,**不是 capture 的 bug**,无法在捕获层补救。

**逃生口 = app hook**:某个节点确需角度(或任何 capture 拿不到/想覆盖的视觉),在 `app.js` 里按 `data-id`/`data-name` 定位克隆出的元素、手动覆盖即可(如宝石菱形:`el.style.transform='rotate(45deg)'`)。capture 给真值,设计覆盖归 hook —— 二者分工见 SKILL「引擎 vs hook」。
