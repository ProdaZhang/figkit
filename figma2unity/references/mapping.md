# IR → Unity UI Toolkit 映射全表(ui_to_unity.py 的权威依据)

输入 = figma2html 的 `.ui.json`(IR schema 见 `../../figma2html/references/ui.json-schema.md`)。
IR 样式值是 **CSS 风格字符串**(`radius="45px"`、`border="2.0px solid rgba(...)"`、
`fill="rgba(...)"` 或 `linear-gradient(...)`),转换器逐项解析后映射到 USS。

## 命名约定(重要)

| 约定 | 规则 | 原因 |
|---|---|---|
| UXML `name` | figma id 的 `':'` 换 `'_'`(`1:30` → `1_30`) | UXML name 属性不允许冒号 |
| USS 选择器 | `.el-<name>` 类(如 `.el-1_30`),**不用** `#name` | name 常以数字开头,CSS/USS 的 `#id` 选择器不能以数字开头 |
| 帧根 | `name="screen-root"` + `.screen-root` 类 | 承载帧尺寸与 stageBg |
| 运行时反查 | `FlowBinder.SafeName(figmaId)` 用同一规则,`layer.Q(name)` 查元素 | flow.json 仍写原始 figma id,绑定器换算 |

## 结构与几何

| IR | UXML/USS | 说明 |
|---|---|---|
| `els[]` + `parent` | 按 parent 嵌套的 VisualElement 树 | 同 render.js pass1/pass2 |
| `type=TEXT`(`text≠null`) | `<ui:Label text="...">` | 换行转 `&#10;` |
| 其余 type | `<ui:VisualElement>` | — |
| `x,y`(相对帧绝对 px) | `left/top`(**父相对**:`child.x - parent.x`) | 算法照抄 render.js pass2;parent 缺失/找不到 → 挂帧根、按 (0,0) 换算 |
| `w,h` | `width/height`(px) | UI Toolkit 布局即 border-box,`box-sizing` 无需处理 |
| `z` | **无 z-index** → 同父下按 z 稳定排序生成兄弟顺序 | UI Toolkit 后出现的兄弟绘制在上,视觉等价 |
| `rot` | `rotate: <n>deg` | transform-origin 默认 center,与 render.js 一致 |
| `opacity` | `opacity`(≠1 才输出) | — |

## 样式

| IR | USS | 说明 |
|---|---|---|
| `radius`(1~4 值简写) | `border-top-left/top-right/bottom-right/bottom-left-radius` 四长写 | 按 CSS 简写展开规则(1→aaaa,2→abab,3→abcb) |
| `border`(`Wpx style color`) | `border-width` + `border-color` | USS 边框恒实线;style≠solid 记 known-loss |
| `fill`(纯色) | `background-color` | rgba 字符串 USS 原生支持 |
| `fill`(渐变) | `background-color` = **第一停靠色**回退 | USS 无渐变;记 known-loss |
| `img` | `background-image: url("...")` + `background-size`(imgSize,默认 cover)+ `background-position: center` + `background-repeat: no-repeat` | background-size 等需 Unity 2022.2+ |
| `stageBg` | 帧根 `.screen-root`:url→背景图,色→背景色,渐变→首停靠色 | — |
| `shadow` | **丢弃** | USS 无 box-shadow;记 known-loss |
| `blur` | **丢弃** | USS 无 filter;记 known-loss |

## 文字(text 子对象 → Label)

| IR | USS | 说明 |
|---|---|---|
| `content` | UXML `text` 属性 | `\n` → `&#10;` |
| `color` / `size` | `color` / `font-size` | — |
| `weight` | `-unity-font-style: bold`(≥600)/ `normal` | 数值字重丢失;非 400/700 记 known-loss |
| `alignV` + `textAlign` | `-unity-text-align: <upper\|middle\|lower>-<left\|center\|right>` | flex-start→upper、center→middle、flex-end→lower;水平取 textAlign(多行也对) |
| `ls` | `letter-spacing: <n>px` | — |
| `lh` | **丢弃** | USS 无 line-height;记 known-loss |
| `family` | **不映射** | Unity 文字需 FontAsset:在 PanelSettings 或主题里配 CJK 字体(如思源黑体 SDF),或对 `.unity-label` 全局设 `-unity-font-definition`;记 known-loss |
| `stroke` | **丢弃** | USS 无字形描边(TextMeshProUGUI 才有);记 known-loss |
| 换行策略 | 含 `\n` → `white-space: normal`;单行 → `nowrap` | 同 render.js:防字体回退偏宽被迫折行 |
| — | Label 额外 `margin:0; padding:0` | 压平 `.unity-label` 内建 padding,保 IR 几何 |

## known-loss 汇总(诚实降级——全部会写进生成的 .uss 文件头注释)

| 项 | 处理 | 备注 |
|---|---|---|
| `shadow` | 跳过 | 需要阴影可在 Unity 里加 9-slice 阴影图 |
| `blur` | 跳过 | 无 filter |
| 渐变 `fill`/`stageBg` | 第一停靠色纯色回退 | 需要真渐变可换渐变贴图 |
| `text.stroke` | 跳过 | 可改用 TextMeshPro 组件承载 |
| `text.lh`(行高) | 跳过 | USS 无 line-height |
| `text.family` | 不映射 | 需手配 FontAsset(见上表) |
| 数值字重(500/800 等) | 近似 normal/bold | USS 只有两档 |
| `border` 非 solid | 降级实线 | USS 边框恒实线 |
| `z` | 文档序替代 | 同父按 z 排序,跨父极端交叉遮挡无法表达 |

## 坐标与缩放(Unity 侧摆放)

- 生成的 UXML 是**固定 px 画布**(帧尺寸 = `cap.w × cap.h`,如 1080×1920),不做响应式。
- **PanelSettings**:Scale Mode = `Scale With Screen Size`,Reference Resolution = `cap.w × cap.h`,
  Screen Match Mode 按产品取向(竖屏游戏常用 Match = 1/Height 或 Expand)。
  这等价于 render.js 的 `mountStage` 视口等比缩放。
- `FlowBinder` 会建一个 `flow.stage.w × flow.stage.h` 的 stage 容器,底屏与弹窗层都铺满它。

## 图片资源摆放

- USS 里 `background-image: url("_assets/s17/xx.png")` 按**相对 USS 文件**解析:
  把 capture 导出的 `_assets/` 目录整个拷到 `.uxml/.uss` 同级(如 `Assets/UI/Screens/_assets/...`),
  Unity 导入为 Sprite/Texture 后 url 即可命中。
- 想引用工程其它位置的资源,改用绝对形式 `url("project:///Assets/...")`(或 `/Assets/...`)。
- 缺图行为与 figma2html 一致:`vec`/`img` 缺 PNG 时该节点透明,不平涂黑。

## 运行时(FlowBinder)对 assemble.js 的对齐表

| assemble.js | FlowBinder.cs | 差异 |
|---|---|---|
| `build` | `Build()`(OnEnable) | caps 从 Inspector 的 `screens[]`(VisualTreeAsset)来,不走网络 |
| `subtreeOf` + modal 层 | 实例化整屏 → `Q(root)` 抽出重挂 + 拷样式表 | UI Toolkit 样式表挂在元素上,抽离后需手动带走 |
| backdrop | 层内黑色半透 VisualElement | 同 rgba(0,0,0,0.5) |
| `wireEvents`(click/@any/@panelOutside) | `RegisterCallback<ClickEvent>` | 同语义 |
| `guardOk` | `Truthy` + `GuardOk` | null/false/0/"" 皆假,同款 |
| `renderRows`(cloneNode) | `RenderRows`(重实例化 cap 抽模板行) | UI Toolkit 无深克隆;行距采样读 resolvedStyle,**须布局完成后调用**(Init 里 `schedule.Execute` 延一帧) |
| `bindings.checkbox` | `SyncBindings()`(勾号用子 Label) | VisualElement 无 textContent |
| `app.js APPHOOK` | `IAppHook`(RegisterActions/Init) | 同分工:引擎管机制,hook 管域内语义 |
| 列表滚动(overflowY:auto) | 容器 `Overflow.Hidden` 裁切 | USS 无 overflow:scroll;需滚动由 hook 换 ScrollView 承载 |
