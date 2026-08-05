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
| `radius`(1~4 值简写) | `border-top-left/top-right/bottom-right/bottom-left-radius` 四长写 | 按 CSS 简写展开规则(1→aaaa,2→abab,3→abcb),然后**按 CSS 的口径先夹紧**再交给 Unity:相邻半径之和超过边长时,CSS 把四角按同一比例缩,Unity 却是逐轴各夹各的 —— 235×42 的药丸配 57px 圆角在 Unity 手里成了 57×21 的椭圆角(一颗被拉长的橄榄),浏览器画的是胶囊。百分比不动(`50%` 在非正方形盒子上本来就该是椭圆角) |
| `border`(`Wpx style color`) | `border-width` + `border-color` | USS 边框恒实线;style≠solid 记 known-loss |
| `fill`(纯色) | `background-color` | rgba 字符串 USS 原生支持 |
| `fill`(渐变) | `background-image` = **编译期烘的 PNG** | USS 没有渐变属性,转换器自己烘一张 64² 纹理:每个纹素按该元素**真实 w/h** 投影到渐变轴再插值,任意角度都准(不是只处理 0/90°)。放在编译期做,集成方不用多加运行时代码,产物也保持逐字节确定。解析不了的渐变仍退首色 |
| `img` | `background-image: url("...")` + `background-size`(imgSize,默认 cover)+ `background-position: center` + `background-repeat: no-repeat` | background-size 等需 Unity 2022.2+ |
| `stageBg` | 帧根 `.screen-root`:url→背景图,色→背景色,渐变→首停靠色 | — |
| `shadow` | 兄弟**垫层**盒子:硬阴影 `2px 6px 0 c` 就是同一个圆角盒子按位移填色;**带模糊**的则在编译期烘一张 PNG(`soft_shadow_asset`)当垫层的底 | USS 既没有 `box-shadow` 也没有模糊,但"底下多垫一个盒子"把两者都表达得了。模糊那半 = 圆角矩形覆盖率(逐轴椭圆角、带一像素抗锯齿)过**三次盒滤波 ≈ σ=blur/2 的高斯**,这正是 CSS 自己的定义;画布按 3σ 外扩,免得拖尾被裁。产物按内容哈希命名,六张一样的卡共用一张图。只有在**没有可写素材目录**时才退回 known-loss |
| `blur` | **丢弃** | USS 无 filter;记 known-loss |
| `paths` + `viewBox`(v1.2) | `<figkit:FigVector>` —— `runtime/FigVector.cs` 用 **Painter2D** 真画 | 货真价实的矢量绘制:不产任何图片资产,也不用额外的包(`com.unity.vectorgraphics` 是预览包)。元素自己解析 SVG 路径(M/L/H/V/C/S/Q/T/Z,贝塞尔按固定步数采样以保确定性),按 IR 要的 winding rule 填充。**UXML 只在这一屏真有矢量时才声明 `xmlns:figkit`** —— 声明了却没把 runtime 拷进工程,整份 UXML 会加载失败。描边带一般由捕获层直接发成可填的 evenodd 环(IR v1.3),这里照填即可。捕获层读不懂的带子会退回「原样 ±2w + `clip` 提示」,而 Painter2D 没有布尔裁剪:OUTSIDE 那半仍是精确的 —— 先画带子、再让不透明的填充盖住内侧那一半;退回来的 INSIDE 只能全宽画,粗一倍,逐元素记 known-loss。另有一条:**Painter2D 会把同一条路径的多个轮廓连成一个多边形**(实测把描边带整块绞成细长三角),所以包围盒互不相交的轮廓逐个填,相交的仍走一次填充 —— 形状上的洞正是靠那一次填充规则挖出来的 |
| `clip`(v1.1) | `overflow: hidden` | UI Toolkit 的 `overflow` 本来就跟随 `border-radius`,所以圆角裁剪在这里不花额外力气就是精确的(Godot 得靠 `clip_children` 才到得了同一步) |
| `borderAlign`(v1.2) | 垫在下面、四边各外扩 N 且圆角 +N 的兄弟盒子 | USS 没有 `box-shadow`,但描边往外那半**本来就是**"同形状、大 N 圈的另一个盒子" —— 所以是画出来的,不是丢掉的。与下面的硬阴影同一套机制 |

## 文字(text 子对象 → Label)

| IR | USS | 说明 |
|---|---|---|
| `content` | UXML `text` 属性 | `\n` → `&#10;` |
| `color` / `size` | `color` / `font-size` | — |
| `weight` | `-unity-font-style: bold`(≥600)/ `normal` | 数值字重丢失;非 400/700 记 known-loss |
| `alignV` + `textAlign` | `-unity-text-align: <upper\|middle\|lower>-<left\|center\|right>` | flex-start→upper、center→middle、flex-end→lower;水平取 textAlign(多行也对) |
| `ls` | `letter-spacing: <n>px` | — |
| `lh` | **丢弃** | USS 无 line-height;记 known-loss |
| `family` | `-unity-font-definition: url("fonts/FigCJK-<Regular\|Bold>.ttf")` | 转换器只写引用,**两个 .ttf 由集成方放到 .uss 同级**(`subset_font.py` 从可变字体实例化 + 子集化)。两个坑都不吭声:文件**缺失**会在导入期报错、看得见;而文件在、**子集却盖不住这屏用到的字**,Unity 只是**悄悄退回另一张字体**,版面还挺像样。这件事按定义在「文字外」那半量不出来 —— 会动的是「文字内」那半。第二个坑:真 Bold 加载之后必须**停发 `-unity-font-style: bold`**,否则 Unity 会在它上面再合成一层粗 |
| `stroke` | `-unity-text-outline-width` / `-color`,**封顶 1px** | USS 其实有这两条(原先写"USS 无字形描边"是错的),但 TextCore 的 outline 是**往里吃字身**的,CSS 的是往外长。底栏页签实测(描边墨量÷字身墨量 / 字身白像素,HTML 参照 1.90 / 1653):1px→0.41/1250、2px→1.17/913、3px→2.75/651、6px→9.00/~180 —— 描边越粗字身越少,没有哪个宽度能还原。封顶 1px:暗边在、字形还在,差额如实记降级 |
| 换行策略 | 含 `\n` → `white-space: normal`;单行 → `nowrap` | 同 render.js:防字体回退偏宽被迫折行 |
| — | Label 额外 `margin:0; padding:0` | 压平 `.unity-label` 内建 padding,保 IR 几何 |

## known-loss 汇总(诚实降级——全部会写进生成的 .uss 文件头注释)

| 项 | 处理 | 备注 |
|---|---|---|
| `shadow` | 跳过 | 需要阴影可在 Unity 里加 9-slice 阴影图 |
| `blur` | 跳过 | 无 filter |
| 解析不了的渐变 | 第一停靠色纯色回退 | 只有径向 / 非 `<角度>deg` 的写法会落到这里;线性渐变已经烘图 |
| 超过 1px 的 `text.stroke` | 封顶 | TextCore 的 outline 往里吃字身,详见文字那张表 |
| `text.lh`(行高) | 跳过 | USS 无 line-height |
| `text.family` | 不映射 | 需手配 FontAsset(见上表) |
| 数值字重(500/800 等) | 近似 normal/bold | USS 只有两档 |
| `border` 非 solid | 降级实线 | USS 边框恒实线 |
| `z` | 文档序替代 | 同父按 z 排序,跨父极端交叉遮挡无法表达 |
| `flow.events[].transition` | 烘成 `motion.json` 采样曲线,**但没人播** | 见下面「转场缓动」 |

## 转场缓动(motion.json)

`python3 ui_to_unity.py <cap.ui.json> <outdir> <flow.json>` 会多产一个 `motion.json`:
每条带转场的事件一份 **17 点等距采样曲线**(x/y 都是 0..1 进度)。

**为什么是采样点,不是 USS 的 easing 关键字。** figma 给的是一条具体曲线
(`cubic-bezier(.32,.72,0,1)` 或弹簧三参);USS 的 `ease-out` 之流是**另一条同名不同形**的曲线。
各后端各挑"最像的" = 同一份 IR 在六个引擎里六种手感,而每家测试都绿。
量级参考:easeOutCubic 与 `cubic-bezier(.23,1,.32,1)` 最大差 **19.8 个百分点**,且差在起步段。
`tools/conformance` 会拿这些点跟 godot **逐点对账**。

用法:`new AnimationCurve(points.Select(p => new Keyframe(p[0], p[1])).ToArray())`,
再自己 tween;**别**图省事换成 `transition-timing-function` 的关键字。

**接线**:把 `motion.json` 拖成 `FlowBinder` 的 `motionJson`(TextAsset)。不配 = 全部瞬时显隐,
是**声明在案的降级**,不是静默丢失。配了则自动生效:

| 机制 | 行为 | 曲线来源 |
|---|---|---|
| 弹窗入场 / **出场** | `events[].transition`,含 `SCALE_IN/OUT`、`MOVE_IN/OUT`、`SLIDE_IN/OUT`、`DISSOLVE` | figma 声明的,或预设补的 |
| 按压反馈 | 每个绑了事件的元素 `PointerDown` → 缩到 `motion.press.scale` | 预设(figma 无此概念) |
| 列表逐项入场 | `RenderRows` 每行按 `motion.stagger.step` 错开 | 预设 |
| guard 拒绝 | 抖一下(`motion.guardFail`) | 预设 |

**2026-07-29 于 Unity 6000.4.8f1 batchmode 实机核验**:`FlowBinder` 把 `motion.json` 读成 6 条
`AnimationCurve`(各 17 关键帧),`Evaluate(0.25)` 与 python 求解器**逐条一致到小数点后 6 位**
(`DISSOLVE 0.378138` / `MOVE_IN 0.779131` / `SCALE_OUT 0.775382` / `press` / `stagger`),
编译零错零警告。**动画的视觉播放未在 Play Mode 点验**(需要真跑场景)。

| 处置 | 说明 |
|---|---|
| **known-loss:具名弹簧预设** | `GENTLE/QUICK/BOUNCY/SLOW`、`*_BACK` figma 没公开控制点 → 标 `unresolved` 不采样,**不编数** |
| **approx:弹簧被 duration 截断** | 弹簧没有固定时长,窗口短于收敛时间就切一截,生成时打 `truncated:` |
| **known-loss:`SMART_ANIMATE`** | 同名图层自动配对插值,跨引擎无对应物;曲线照采,配对逻辑不实现 |
| **known-loss:弹簧曲线** | 采样点照采,但 CSS/USS 都没有原生弹簧;按采样关键帧插值 = 形状对、可打断性没有 |

⚠️ 用 `style.scale` / `style.translate`,**不用** `transform.scale` / `transform.position` ——
后者在 Unity 6 起全部 `[Obsolete]`,会打破本后端"编译零警告"的声明。

## 坐标与缩放(Unity 侧摆放)

- 生成的 UXML 是**固定 px 画布**(帧尺寸 = `cap.w × cap.h`,如 1080×1920),不做响应式。
- **PanelSettings**:Scale Mode = `Scale With Screen Size`,Reference Resolution = `cap.w × cap.h`,
  Screen Match Mode 按产品取向(竖屏游戏常用 Match = 1/Height 或 Expand)。
  这等价于 render.js 的 `mountStage` 视口等比缩放。
- `FlowBinder` 会建一个 `flow.stage.w × flow.stage.h` 的 stage 容器,底屏与弹窗层都铺满它。

## 纹理导入设置(别用 Unity 的默认值)

Unity 的默认导入器是给 3D 表面调的,那套默认值对 UI **条条都不对**。
`runtime/Editor/FigkitTextureImport.cs` 是个 `AssetPostprocessor`,把 `Assets/Resources/UI/` 下的
资源改成 UI 该有的样子。其中三条是拿实机像素比出来的(2026-08-05,示例里那个白色对勾):

- **`mipmapEnabled`** —— UI 是 1:1 贴的,采样却可能落到更低一级 mip,边缘于是**向外渗**。
  白勾比 HTML 每边胖 1px、底部那行被硬切平;同一格里的金色小星反而**向内缩** 1px ——
  亮的外扩、暗的内缩,是同一件事。
- **`textureCompression`** —— DXT/BC 块压缩,伪影恰好出在 UI 最多的高对比边缘上,颜色也偏。
- **`alphaIsTransparency`** —— 关着时全透明像素保留原有 RGB,半透明边缘会渗出黑边。

另外钉死 `wrapMode = Clamp`(UI 不平铺,Repeat 会采到对侧像素)和 `npotScale = None`。
设好之后,对勾与 HTML **逐行相同**(下缘白像素 24/22/20/…/5/0,一个不差)。
资源放在别处就改 `Root` 常量,改完对那个目录 Reimport 一次。

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
