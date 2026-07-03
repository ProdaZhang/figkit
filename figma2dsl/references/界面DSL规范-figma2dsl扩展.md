# 界面DSL规范 — figma2dsl 扩展页

> 本页是 figma2dsl 对 aigd `界面DSL规范.md` 的增补;aigd 整合时再并入正本。

---

## §0 双轨架构:全保真捕获(渲染主路径)+ DSL(派生语义视图)

从 figma 还原界面有两条路,**同一次捕获产出、各司其职**,不要混淆:

| 产物 | 生成 | 性质 | 用途 |
|------|------|------|------|
| **`<屏>.ui.json`** | `scripts/figma_capture.py` | **全保真**(每可见节点 + 全部样式,不折叠) | **渲染真源**:harness `render.js` / 实际 app / aigd 还原 |
| `<屏>.tree.html` | `figma_capture.py` 同次 | 全保真静态预览 | 眼比设计稿、氛围稿 |
| `<屏>.md`(DSL)+ `.nodes.json` | `figma_to_dsl.py` | **语义抽象**(折叠 + flat skin,**有损是本职**) | 给人读 / AI 按意图生成 / KB 检索 / 喂 aigd |

**关键认知:折损不是 DSL 造成的,是"折叠+压扁"这套抽象选择造成的。** DSL 主动丢像素细节以换可读/语义——这是它该有的样子。**要完全还原画面,渲染走 `.ui.json`,不走 DSL。** 唯一躲不掉的损失是矢量路径→栅格 PNG(与是否用 DSL 无关,由 DOM 渲染目标决定;要纯无损可改出 SVG)。

### `figma_capture.py` 用法

```
python figma_capture.py <nodes.json> <frameId> <sNN> <assetDir> <assetRelPrefix> <out_basepath>
# 产物: <out_basepath>.ui.json  +  <out_basepath>.tree.html
```

### `.ui.json` schema(全保真,扁平绝对坐标)

```json
{ "frame": "46:8241", "w": 1080, "h": 1920,
  "stageBg": "url(_assets/s17/bg.png) center/cover no-repeat",
  "els": [ {
    "id": "46:8265", "name": "Frame 96", "type": "FRAME", "parent": "46:8263",
    "x": 199, "y": 538, "w": 684, "h": 802, "z": 26, "rot": 0, "opacity": 1,
    "radius": "37px", "border": "4.0px solid rgba(219,208,184,1)", "shadow": "0px 4px 0px rgba(0,0,0,0.6)", "blur": "",
    "fill": "rgba(255,251,242,1)", "img": "", "imgSize": "", "vec": false,
    "text": null
  } ] }
```

- 几何 = **相对帧原点的绝对 px**;`parent` = figma 父节点 id(render.js 嵌套时转父相对)。
- `fill` 纯色含透明度(`rgba`)/ 线性·径向渐变 css;`img`+`imgSize` 图片填充;`vec=true` 为矢量簇折叠图(缺 PNG 回退透明,**不平涂黑**)。
- `text`(仅 TEXT)= `{content,color,size,family,weight,lh,ls,alignH,alignV,textAlign,stroke}`,否则 `null`;`stroke` 走 `-webkit-text-stroke`+`paint-order`。
- 渲染器(render.js)消费规则:逐节点直贴样式;**单行文本(无 `\n`)用 `nowrap`** 缓解缺字体时回退字偏宽撑出文本框被迫折行。

---

## §A `## 原图` 段

DSL 文件末尾可带 `## 原图` 段,格式:

```
## 原图
元素id  相对路径
元素id  相对路径
```

- 每行一个元素:节点 id + Tab + 相对于 DSL 文件的 PNG 路径(由 `export_assets.py` 导出)
- 渲染时该元素以此图作 background(图标/立绘/背景槽 cover)
- **缺图回退 `## 皮肤` 色**;不阻断渲染
- 增量填充:补满即可取代 `.real.html` 整图氛围页

---

## §B `> 坐标系: 父相对px`

DSL 文件头部声明:

```
> 坐标系: 父相对px
```

语义:

- `@{x y w h}` = **相对父节点(最近发射祖先)的像素坐标**,不再是屏百分比
- 直接取 figma 真坐标,与 figma 对齐,易查 bug
- `ui_render` 的 `normalize_coords` 在渲染前按缩进推父、累加 px、除以 `> 尺寸` 转绝对屏百分比喂给渲染器
- **向后兼容**:无此头的旧 DSL 仍按百分比解析

---

## §C sidecar `parent` 字段

`.nodes.json`(与 DSL 同名,后缀 `.nodes.json`)每元素记录:

```json
{
  "dsl_id": "btn_start",
  "figma_id": "123:456",
  "parent": "panel_main",
  "img": "_assets/s01/n123_456.png",
  "skin": "#1A2B3C",
  "ink": "#FFFFFF",
  "text": "开始",
  "shape": "rect",
  "radius": "37px",
  "border": "4.0px solid rgba(219,208,184,1)",
  "shadow": "0px 4px 0px rgba(0,0,0,0.6)",
  "font": { "size": 36.0, "weight": 700, "lh": 48, "align": "center", "valign": "center", "ls": 0.0 }
}
```

- `parent` = 最近发射祖先的 dsl id;根级元素为 `""`
- 被跳过的隐藏中间组不作 parent,取最近的被发射祖先
- `img / skin / ink / text / shape` 供客户端重建用,富集自 figma 节点树
- **样式四件(与 `figma_to_html.py` 同源,确保 harness 渲染与氛围稿一致)**:
  - `radius` 圆角 CSS(`cornerRadius`/`rectangleCornerRadii`→`37px`/`8px 8px 0 0`;ELLIPSE→`50%`);空串=无
  - `border` 描边(`strokes`+`strokeWeight`→`4.0px solid rgba(..)`);TEXT 不画矩形 border(走字形轮廓)
  - `shadow` 阴影(`effects` 的 DROP_SHADOW→`box-shadow` 值,多条逗号分隔);空串=无
  - `font` 仅 TEXT 为 dict`{size,weight,lh,align,valign,ls[,stroke]}`,否则 `null`;`stroke` 存在时客户端用 `-webkit-text-stroke`+`paint-order:stroke fill` 画字形轮廓
- 旋转(`relativeTransform`)暂不导出:需配合非 AABB 几何,留作后续

---

## §D 跳隐藏节点

转写时跳过以下节点,不生成 DSL 行:

- figma `visible: false`
- `opacity` ≈ 0(< 0.01)
- 宽或高 = 0

parent 追溯时同样跳过:被跳过的中间组不作任何元素的 parent,取最近的**被发射**祖先(或根级 `""`)。
