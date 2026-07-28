---
name: figma2html
description: Use when you have a figma design frame (or several) and want to turn it into a high-fidelity, runnable HTML client — pixel-faithful rendering plus declared interactions (modals, data binding, guards). For figma-sourced UIs; non-figma authoring (brief/screenshot) goes through the 界面 DSL instead.
---

# figma2html — figma 节点树 → 高保真可跑 HTML

## 这个 skill 干什么

figma 帧 → **全保真 `.ui.json`(像素)** + **`flow.json`(声明的交互/Events)** → 通用引擎组装成**可点可跑**的 HTML 客户端。

- **像素**:`figma_capture.py` 把每个可见节点 + 全部样式抠成 `.ui.json`,`render.js` 1:1 重建 DOM。
- **交互**:figma 没有交互逻辑,**Events 在 `flow.json` 手写**(按 figma node id、抗重抓);`assemble.js` 读 flow 把"底屏 + 弹窗叠加 + 事件 + 绑定"装起来。**域内语义(数据→行、回填、状态色)由 app hook 注册**,引擎不写死。

边界:**figma 进 → 本 skill**(像素优先);**非 figma 进(brief/截图)→ 界面 DSL → ui_render**(语义优先)。两边共享 figma node id 键空间 + Events 语法。

## 内容

```
scripts/   figma_capture.py(节点树→ui.json+tree.html)· subset_font.py(字体子集woff2)· shoot.py(Edge无头截图)
           tests/(capture 冒烟:夹具→断言 records;`python3 scripts/flow_check.py <flow.json>   # 手写完 flow.json 先跑这个:坏引用离线就报,
                                            # 别等浏览器里"点了没反应"才发现
python3 scripts/tests/run_all.py`)
runtime/   render.js(ui.json→DOM,subtreeOf抽子树)· assemble.js(通用引擎:flow→底屏+弹窗+事件+绑定)· app.tmpl.html
references/ ui.json-schema.md(含「已知限制:旋转」)· flow-events.md(flow/Events 契约)
examples/login/ 自足可跑示例:make_fixture.py(合成三屏,走真 capture 管线)+ screen-*.ui.json + flow.json + app.js + net.js(mock)+ app.html + README(起 http.server 即点;Edge 截图已核验)
```

## 用法(管线)

1. **拉节点树**:figma REST `/v1/files/<key>/nodes?ids=…` → `nodes.json`(token 只进单子进程、用完即删)
2. **捕获**:`python3 scripts/figma_capture.py nodes.json <frameId> <sNN> <assetDir> <assetRel> <out>` → `.ui.json` + `.tree.html`
3. **导素材**:位图填充走 `/v1/files/<key>/images`(按 imageRef,**不卡配额**);矢量图标走 `/v1/images`(**有配额**)。缺图:`vec` 回退透明、`img` 回退无背景。
4. **字体**:`python3 scripts/subset_font.py <font.ttf> fonts/cjk.woff2 <ui.json...>` → 几十 KB,@font-face 离线可移植
5. **写 flow.json**:声明 base / modals(抽哪些根叠加)/ events / list / bindings(见 `references/flow-events.md`)
6. **组装**:`app.tmpl.html` 套 `render.js + assemble.js + flow.json + app.js(hook)` → 可跑;`python3 scripts/shoot.py <url> out.png` 截图核验

## 关键规则(都在 figma_capture / assemble 里)

- **资产感知折叠**:矢量簇有 PNG 才折叠成图;缺 PNG 不折叠、渲可渲染形状子(治"勾选框/图标因缺图整体消失");`vector_leaf_count≤4` 防爆。
- **图片填充按 imageRef 命名** → 跨屏复用、可直接喂 figma 导出。
- **阴影圆角修正**:无圆角但带 DROP_SHADOW → 继承铺满圆角子的圆角。
- **架构 = 底屏 + 弹窗叠加**(非一屏屏 swap):底部 UI 只一份,弹窗 `subtreeOf` 抽子树叠加 + 遮罩 → 状态不跨屏串。
- **引擎 vs hook**:`assemble.js` 管结构/机制(底屏/弹窗/事件/守卫/勾选/列表克隆);`app.js` 管域内语义(数据→行、回填、状态色)。
- **capture 拿不到的 → app hook 覆盖**:figma 实例内部子节点常无 `relativeTransform` → `rot` 回退 0(API 限制,见 references「已知限制:旋转」);任何 capture 取不到或想做设计覆盖的视觉(角度、菱形宝石等),在 hook 按 `data-id`/`data-name` 定位手改,别去捕获层硬凑。
- **改样式同步两处**:`figma_capture.py rec_to_css`(出 tree.html 预览)与 `render.js applyRecStyle`(出运行时 DOM)是同一套贴样式逻辑,改一处必同步另一处(`../../` 路径差是有意的,别对齐)。

## 硬约束

- UTF-8 无 BOM。**FIGMA_TOKEN** 只读进单子进程、绝不进对话/文件/CHANGELOG、用完即删。
- **figma_capture.py 主拷贝在本 skill**;同级 `figma2dsl/scripts/` 持镜像(其 tests 有 parity 守卫)。改捕获逻辑只在这里改,再同步过去。
- 运行时全局名 `window.FigApp`(app hook 一律用 register(app) 的形参,别直引全局);子集字体族名 `FigCJK`。
- **下游引擎后端**:同级 `figma2unity / figma2godot / figma2unreal / figma2cocos` 消费本 skill 产的 `.ui.json + flow.json`(它们不含 capture,只做编译/解释)。
- 跳隐藏节点(visible:false / opacity≈0 / 0尺寸)。
- 服务端零依赖(Node)即可:POST /api + SSE + 静态服务(**.woff2 MIME**)。
