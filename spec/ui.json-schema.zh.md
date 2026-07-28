> **注:本文是 zh-CN 镜像,不是权威版。** 权威版 = 同目录的英文 `ui.json-schema.md`;
> 改动先落英文,再镜像到这里。`tools/spec_parity.py` 会比对两边**代码块去注释后**的结构,
> 只改一边会红(散文可以有出入,schema 不行)。

> **FigKit IR Spec v1.0 — FROZEN 2026-07-03**
> 本文件是六后端(html/dsl/unity/godot/unreal/cocos)共享 IR 契约的**权威版本**;
> `figma2html/references/` 下的同名文件是随 skill 分发的工作副本(内容同源)。
> 冻结纪律:v1.0 起**只允许 additive**(新增可选字段/枚举值),不改既有字段形状;
> 下一次结构性改动须由某个后端撞出的真实缺口触发,并升 v1.1 记录于本头部变更行。
> 变更史:v1.0(2026-07-03)冻结 —— 经 6 后端互证(html 渲染/dsl 转写/unity 编译+导入/godot 实机渲染/unreal 强类型化/cocos 校验器)。

# .ui.json — 全保真渲染真源(figma_capture.py 产)

一帧 figma 的"全保真结构化快照":每个可见节点 + 全部样式,扁平绝对坐标、按 id 嵌套。
`render.js` 读它 1:1 重建 DOM(逐节点贴 CSS)。

```jsonc
{
  "spec": "1.0",                          // 本次捕获遵循的 IR 契约版本(见 spec/)
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

- `spec` 是本文件捕获时遵循的 IR 契约版本,**仅供参考、不硬失败**:缺失按 `"1.0"` 处理
  (该字段出现之前的老产物);**次版本**不同直接忽略(冻结纪律保证只增不改,老后端顶多看不见
  新的可选字段);**主版本**不同则告警而非拒绝 —— 一句"我在按旧规矩解释这份文件"胜过沉默。
- 几何=相对帧原点的绝对 px;`render.js` 嵌套时转父相对。
- `subtreeOf(cap, 根id | 根id数组)` 抽子树(弹窗叠加用)。
- 完整字段语义见 figma2dsl 的 `references/界面DSL规范-figma2dsl扩展.md §C/§0`。

## 已知限制:旋转(rot)

`rot` 由 `geom()` 从节点的 `relativeTransform` 反解(`atan2(m[1][0], m[0][0])`)。**figma REST 对组件实例(INSTANCE/COMPONENT)内部子节点常不返回 `relativeTransform`**——这类节点的 `rot` 会**回退为 0**(整簇折叠成图时内部角度同样丢失)。这是 figma API 的特性,**不是 capture 的 bug**,无法在捕获层补救。

**逃生口 = app hook**:某个节点确需角度(或任何 capture 拿不到/想覆盖的视觉),在 `app.js` 里按 `data-id`/`data-name` 定位克隆出的元素、手动覆盖即可(如宝石菱形:`el.style.transform='rotate(45deg)'`)。capture 给真值,设计覆盖归 hook —— 二者分工见 SKILL「引擎 vs hook」。
