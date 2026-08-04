# IR → Godot 4 映射全表(ui_to_tscn.py / flow_binder.gd 的契约)

输入 = figma2html 的中间表示(IR):`.ui.json`(像素快照,schema 见
`../../figma2html/references/ui.json-schema.md`)+ `flow.json`(交互声明,见
`../../figma2html/references/flow-events.md`)。本表是编译后端的唯一映射权威。

## 1. 顶层(cap → 场景)

| IR | Godot | 说明 |
|---|---|---|
| 一个 `<stem>.ui.json` | 一个 `<stem>.tscn`(text scene, `format=3`) | stem = 文件名去 `.ui.json` |
| `w` / `h` | 根 `Control` 的 `offset_right` / `offset_bottom` | 根节点名 = stem(消毒后) |
| `stageBg` 纯色 `rgba(...)` | 子节点 `StageBg`(ColorRect,`mouse_filter = 2`) | 首个子节点,垫底 |
| `stageBg` `url(path) ...` | `StageBg`(TextureRect + ext_resource,cover) | 素材摆放见 §6 |
| `stageBg` `linear-gradient(...)` | `StageBg`(TextureRect + GradientTexture2D) | 真渐变 |
| `stageBg` 径向/其它渐变 | `StageBg`(ColorRect 平均色) | known-loss(§7) |

## 2. 节点命名

tscn 节点名不允许 `. : @ / " %` —— **统一换 `_`**:figma id `1:40` → 节点名 `1_40`。
`flow_binder.gd` 的 `node_name()` 用同一规则,因此 flow.json 里照写原始 figma id 即可。
同级消毒后撞名(极罕见)→ 追加 `_` 兜底。保留名:`StageBg`、`Backdrop`、`CheckMark`、`modal_*`。

## 3. 几何 / 层级(照 render.js pass2)

| IR | Godot | 说明 |
|---|---|---|
| `x,y,w,h`(相对帧绝对 px) | anchors 全 0(左上,默认不落盘)+ `offset_left/top = (x,y) − 父(x,y)`,`offset_right/bottom = left/top + (w,h)` | 与 render.js"绝对几何转父相对"同算法 |
| `parent` | 节点树挂载路径(`parent="."` / `parent="1_10"` / 多级 `a/b`) | 父 id 不在本屏(子树抽取)→ 当根 |
| `z` | **同级树序**(children 按 `(z, 原序)` 排序) | Godot Control 绘制顺序 = 树序;不写 `z_index`(它跨层累加,语义不同)。跨父的全局 z 交叉是 known-loss(§7) |
| `rot`(度) | `rotation`(**弧度**)+ `pivot_offset = Vector2(w/2, h/2)` | Godot 默认绕左上角转,必须补中心 pivot 才对齐 CSS `transform-origin: center` |
| `opacity` | `modulate = Color(1, 1, 1, a)` | modulate 向下传播 = CSS opacity 连带子树;别用 self_modulate |

## 4. 盒子样式(RECTANGLE/FRAME/… → Panel + StyleBoxFlat)

有 `fill`/`border`/`shadow` 任一 → `Panel` + `theme_override_styles/panel = StyleBoxFlat`;
全空的纯容器 → `Control`(空 Panel 会画主题默认灰皮,必须避开)。

| IR(CSS 风格字符串) | StyleBoxFlat | 说明 |
|---|---|---|
| `fill: rgba(r,g,b,a)` | `bg_color` | 0-255 → 0-1,4 位小数 |
| `fill` 为空但有描边/阴影 | `bg_color = Color(0,0,0,0)` + `draw_center = false` | 只画边/影 |
| `radius: "45px"` / `"a b c d"`(CSS 简写 1/2/3/4 值) | `corner_radius_top_left/top_right/bottom_right/bottom_left`(四角独立) | CSS 序 TL TR BR BL |
| `radius: "50%"`(capture 对**每个 ELLIPSE** 都产) | 四角同取 `min(w,h) × 50%` | **正方形精确、非正方形近似**:Godot 的 corner_radius 是标量,画不出椭圆角。实测代价(2026-08-05):邮件面板底部那条弧是个 2143×680 的椭圆,标量口径把它画成胶囊,顶弧**比 HTML 平 38px** —— 面板下沿的黄色带在 y=1176 就断了,而不是 y=1214。**这条已经不能再说"与其它后端同口径"**:Unity 的 UI Toolkit 原生按轴解析百分比,figma2cocos 现在也自己按 CSS 分轴算,两边画的都是真椭圆。对齐对象是 CSS,不是别的后端的将就实现;这里要补齐得改用烘出来的贴图而不是 StyleBoxFlat。此行曾因 `float('50%')` 抛异常而**整个丢掉**(椭圆渲染成方块且无告警),现由 tools/conformance 守着 |
| `border: "2.0px solid rgba(...)"` | `border_width_left/top/right/bottom` + `border_color` | 宽度取整、最小 1;Godot 边框向内画,CSS `box-sizing: border-box` 同语义 |
| `shadow: "ox oy blur [spread] rgba(...)"` | `shadow_color` + `shadow_offset = Vector2(ox, oy)` + `shadow_size` | **Godot 原生支持,别丢**。`shadow_size ≈ blur + spread`、最小 1(size=0 时 Godot 不绘制,CSS 的 0-blur 硬阴影会消失,故兜底 1) |
| `fill: linear-gradient(角度, 色标…)` | 节点改为 `TextureRect` + `GradientTexture2D`(`Gradient` 存 offsets/colors;角度 → `fill_from/fill_to` UV:CSS 0deg=向上、90deg=向右) | 真渐变;色标缺位置按 CSS 规则插值 |
| `fill: radial-/conic-gradient(...)` | `Panel` + 色标**平均色** | known-loss(§7) |

## 5. 文字(TEXT → Label)

| IR `text.*` | Godot Label | 说明 |
|---|---|---|
| `content` | `text = "..."`(转义 `\\` `\"` `\n` `\t`) | 含 `\n` 时另加 `autowrap_mode = 3`(WORD_SMART,对齐 pre-wrap;单行不设 = 对齐 nowrap) |
| `alignH` / `alignV`(flex 值) | `horizontal_alignment` / `vertical_alignment`(`flex-start→0 center→1 flex-end→2`) | alignH 缺省时退回 textAlign |
| `color` | `theme_override_colors/font_color` | |
| `size` | `theme_override_font_sizes/font_size`(int) | |
| `lh`(行高 px) | `theme_override_constants/line_spacing = lh − size` | 仅 lh>0 时写;可为负 |
| `stroke`("wpx rgba(...)") | `theme_override_colors/font_outline_color` + `theme_override_constants/outline_size = round(w/2)` | webkit-text-stroke 骑线 + `paint-order:stroke` → 可见≈外侧一半,故取 w/2(近似) |
| `weight` / `family` / `ls` | **不落盘** | 需要字体资源才有意义,见 §6 字体与 §7 known-loss |

## 6. 图片 / 素材 / 字体

| IR | Godot | 说明 |
|---|---|---|
| `img`(项目相对路径,按 imageRef 命名跨屏复用) | `TextureRect` + `[ext_resource type="Texture2D" path="res://<img>"]` | **素材摆放**:把 figma2html 导出的 `_assets/` 整目录原样拷进 Godot 工程根(路径逐段保留),`res://` + IR 路径即命中;同 imageRef 多处引用共享同一 ext_resource |
| `imgSize: cover`(或空) | `expand_mode = 1` + `stretch_mode = 6`(KEEP_ASPECT_COVERED) | 等比铺满裁切 |
| `imgSize: contain` | `expand_mode = 1` + `stretch_mode = 5`(KEEP_ASPECT_CENTERED) | 等比完整居中 |
| 其它 imgSize 值 | `stretch_mode = 0`(SCALE) | 拉伸兜底 |
| `vec: true` 且无 PNG | 无填充 → `Control`(透明占位) | 对齐 render.js"缺图回退透明,不平涂黑" |
| 字体 | 工程级配置:在 Godot 主题(或 `theme_override_fonts/font`)挂 CJK 字体(如思源黑体),按 `weight` 备 Regular/Medium/Bold 几档 | 转换器不产字体资源;figma2html 的 `subset_font.py` 产的 woff2 Godot 不直接吃,用 ttf/otf |

## 7. Known-loss 表(转换必丢/近似项,接受前先看)

| IR 特性 | 处理 | 损失说明 |
|---|---|---|
| `blur`(filter 模糊) | **丢弃** | Control 无逐节点 filter;真要 → 引擎内加 BackBufferCopy/shader,属手工后处理 |
| `clip`(v1.1) | 无圆角走 `clip_contents`,**有圆角走 `clip_children`** | 两套机制,选错不是精度问题是 bug。`clip_contents` 是**矩形剪刀**,不认 `corner_radius`;而 figma 的常见写法正是「带圆角的裁剪容器 + 溢出的内容」,照 `clip_contents` 译出来就是方角:道具卡的品质渐变成了红方块,41px 圆角胶囊里 275×170 的纹理在左端漏出一块方形点阵。`clip_children` 拿**本节点画出来的形状**当子节点的模子,所以这类容器改发成一个带圆角 StyleBoxFlat 的 Panel(必须实心 —— 空模子会把子节点裁得一干二净)+ `clip_children = 1`;自身还有填充要画时用 `2`。**`clip_children` 不能嵌套** —— 一条祖先链只能有一个 —— 所以圆角裁剪嵌套时给**最外层**,内层退化成矩形 `clip_contents`(留痕)。顺序不能反:外层裁的是压在背景上的外轮廓(丢了就是 80px 圆角面板的底部两角变方角),内层裁的东西本来就压在一块不透明的同色父容器里,矩形剪刀只多出一点同色方角 |
| `paths` + `viewBox`(v1.2) | 与场景同目录的 `.svg`,按 `Texture2D` 引用 | Godot 没有 SVG path 节点,但**自带 SVG 导入器**(ThorVG),winding rule / 洞 / 多子路径它都已经做了 —— 所以几何是写成真 `.svg`,而不是自己三角化、更不是退回下位图。注意 ThorVG 按 SVG 1.1 解析:`fill="rgba(...)"` 是 CSS Color 4,解不动会**静默变黑**,故填充写成 `#rrggbb` + `fill-opacity` |
| `borderAlign`(v1.2) | `border_width_*` + `expand_margin_*` | Godot 的 border 和 CSS 一样只往内画。往外那半以 `0 0 0 Npx` 环的形式待在 `shadow` 头部,这里把它拆出来换算成等量 `expand_margin`,让 StyleBox 整体外扩,描边落在盒子之外而不是吃掉填充 |
| `radial-/conic-gradient` | 平均色回退 | StyleBoxFlat/GradientTexture2D(本管线用法)不覆盖;GradientTexture2D 其实有 radial fill,但径向中心/半径与 CSS 语义不齐,宁可显式降级 |
| `linear-gradient` + 圆角/描边/阴影同体 | 渐变保真,圆角/描边/阴影**丢** | 节点变 TextureRect 后无 StyleBox;真要 → 手工套 Panel 父 + clip |
| `text.ls`(字距) | 丢弃 | 需 FontVariation `spacing_glyph`,依赖字体资源 |
| `text.weight` / `family` | 不落盘 | 见 §6 字体;不配主题时用引擎默认字体渲染 |
| `text.stroke` 宽度 | `outline_size = round(w/2)` 近似 | 骑线 vs 外描的差,±1px 级 |
| CSS 阴影 `blur=0` 硬阴影 | **在下面垫一层实心副本**,不走 `shadow_size` | `shadow_size` 的语义是「往外扩多少像素」,而 `0px 6px 0px` 的语义是「整个形状按位移复制一份、填成阴影色」。按 `shadow_size` 走会被 `max(1, blur+spread)` 夹成 1,设计稿上那块厚投影只剩一圈 1px 边。改为在本体**之前**发一个同四角圆角的 Panel(排在前面 = 画在下面)。带模糊的阴影仍走原生 `shadow_size` —— 那才是它表达得了的东西 |
| `shadow` 挂在 TEXT/img 元素上 | 丢弃 | box-shadow ≠ 字体阴影;Label 只有 font shadow,语义不同不硬凑 |
| 全局 `z` 跨父交叉 | 同级排序近似 | 兄弟内正确;跨父穿插(罕见)会平化 |
| 列表滚动(overflow-y auto) | `clip_contents = true` 只裁不滚 | 要滚 → 手工把容器包进 ScrollContainer |
| `rot` 在组件实例内部子节点 | 上游已丢(capture 回退 0) | figma REST 限制,见 figma2html「已知限制:旋转」;补救走 hook 覆盖 |
| `flow.events[].transition`(转场) | 烘成 `motion.json` 采样曲线,**但没人播** | 见下面「转场缓动」一节 |

### 转场缓动(motion.json)

给 `ui_to_tscn.py` 传第三个参数 `flow.json`,就会在 outdir 里多产一个 `motion.json`:
每条带转场的事件一份 **17 点等距采样曲线**(x/y 都是 0..1 进度)。

**为什么是采样点,不是 `Tween.EASE_*` 枚举。** figma 给的是一条具体曲线
(`cubic-bezier(.32,.72,0,1)` 或弹簧三参),`Tween.EASE_OUT` 是**另一条同名不同形**的曲线。
挑"最像的枚举"是各后端各挑各的 —— 同一份 IR 在六个引擎里六种手感,而每家测试都绿。
量级参考:easeOutCubic 与 `cubic-bezier(.23,1,.32,1)` 最大差 **19.8 个百分点**,且差在起步段。
采样点没有这个自由度,`tools/conformance` 还会拿它跟 unity **逐点对账**。

用法:`Curve` 资源逐点 `add_point(Vector2(x, y))`,再 `tween_method` 按 `curve.sample(t)` 插值。

**接线**:`flow_binder.gd` 的 `motion_path`(缺省 `res://motion.json`)。文件不存在 = 全部瞬时显隐,
是**声明在案的降级**,不是静默丢失。存在则自动生效:弹窗入场/**出场** · 按压 · 列表逐项 · guard 抖动。

**2026-07-29 于 Godot 4.3-stable 实机核验**:6 条曲线读成 `Curve`(各 17 点),
`sample(0.3)` 与 python 求解器、以及 Unity 侧**三方一致到小数点后 6 位**;
转场真播(MOVE_IN 中途 `alpha=0.509 / offsetY=942.5` → 终态 `1.000 / 0.0`,出场后 `visible=false`)。

⚠️ **位移/缩放只贴 `modals[*].panel`,遮罩只跟着淡。** 早先把 transform 贴在弹窗**层**上,
而 Backdrop 是层的子节点 —— 遮罩跟着面板一起滑/缩:顶部不变暗、四边缩进露出底屏。
**曲线取值一个不差,是实机截图才抓到的**;html / unity 同构同病,已一并修。
没声明 `panel` 的弹窗只做淡入淡出 —— 不猜该动哪个节点。

⚠️ **必须用 `sample()` 且把切线设成 `TANGENT_LINEAR`。** `sample_baked()` 量化到
`bake_resolution`(默认 100),会与别家差 ~1.4e-3;默认切线(0)会让每段两头压平。
采样点一致**只保证关键帧上一致**,帧间插值模式不对齐照样各算各的 ——
`tools/conformance` 有源码层守卫。

| 处置 | 说明 |
|---|---|
| **known-loss:具名弹簧预设** | figma 的 `GENTLE/QUICK/BOUNCY/SLOW` 与 `*_BACK` 没公开控制点 → 标 `unresolved` 不采样,**不编数**(编"差不多"的数 = 产物看着正常而手感是错的) |
| **approx:弹簧被 duration 截断** | figma 的弹簧带 duration,而弹簧没有固定时长;窗口短于收敛时间就切一截,生成时打 `truncated:` |
| **known-loss:`SMART_ANIMATE`** | 自动匹配同名图层插值,跨引擎无对应物;曲线照采,**配对逻辑不实现** |

## 8. 坐标系 / 缩放建议

- 生成场景是**固定像素舞台**(根 Control = `w×h`,如 1080×1920),内部全部绝对定位,
  **不参与** Godot 布局容器(HBox 等)的重排 —— 语义与 render.js 的 absolute DOM 一致。
- 整场景适配窗口:项目设置 `display/window/size/viewport_width/height = 帧尺寸`,
  `stretch/mode = canvas_items`、`stretch/aspect = keep` —— 等价 figma2html `mountStage`
  的等比缩放。嵌进别的场景当子界面时,包一层 `SubViewport` 或对根 Control 设 `scale`。
- pivot:所有旋转节点已带 `pivot_offset = size/2`(中心),缩放动画想绕中心也直接可用。
- `flow_binder.gd` 作为舞台根:`binder.size = flow.stage`,底屏场景与弹窗层都挂它下面。

## 9. flow.json → 运行时(flow_binder.gd,语义对齐 assemble.js)

| flow 字段 | Godot 行为 |
|---|---|
| `caps` | `.ui.json` 路径 → 同 stem 的 `.tscn`(`scene_dir` 里 load) |
| `base` | 底屏场景整实例常驻(含自身 StageBg) |
| `modals[*].roots/panel` | 该屏场景实例化后**按 roots 剪枝**(顶层只留 roots 子树,StageBg 等释放)+ `Backdrop`(半透明 ColorRect)叠加;`panel` 用于 `@panelOutside` 的 `get_global_rect` 判定。选"整场景实例+剪枝"而非"显隐":顶层子几何本就是帧绝对 px,剪完即对位,且 SubResource 引用保持完整 |
| `events[]` | `gui_input` 按节点名绑(绑定元素设 `MOUSE_FILTER_STOP` + `accept_event()`≈stopPropagation);`@any:`/`@panelOutside:` 绑在弹窗层上,弹窗内容全部 `MOUSE_FILTER_PASS` 冒泡(仿 DOM bubbling);`guard` → state truthy 全过才放行(失败回调 `onGuardFail`) |
| `@in:<modal>:<nodeId>`(v1.1) | 在弹窗层里 `find_el`;该节点从 `_pass_through` 的 `MOUSE_FILTER_PASS` 改回 `STOP` 收下点击,`accept_event()` 挡住冒泡 |
| `list` | `render_rows()`:容器首行 `duplicate()` 当模板,按第二行 offset 差算步长,逐项回调填充 + `set_meta("item")`,行点击派给 `onRowClick` action |
| `bindings.checkbox` | 引擎通用双态:改 Panel 的 StyleBoxFlat `bg_color` + 动态 `CheckMark` Label 填 `mark` 字符 |
| 其余 `do` 名 / 域内回填 | app hook 注册的 action 字典(`app_hook.example.gd`),引擎不写死 |
