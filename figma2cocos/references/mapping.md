# IR → Cocos Creator 3.x 映射表(figma2cocos)

输入 IR = figma2html 管线的 `.ui.json`(像素)+ `flow.json`(交互),字段语义见
`../../figma2html/references/ui.json-schema.md` 与 `flow-events.md`。本表是 `runtime/*.ts` 的实现契约。

> **交付态声明(2026-07-31 更新):runtime 下的 TS 已过严格类型编译门(tsc `--noEmit` 对官方 `@cocos/creator-types` **3.8.3** engine 声明,零错),但未在 Cocos Creator 内实机运行验证。**这道门现在你也能跑**:`cd tools/cocos-typecheck && npm ci && python3 check.py` —— 此前它只存在于作者本机(仓库里没有 tsconfig/package.json,CI 也不跑),而不可复现的声明与假声明,读者是分不出来的。交付物 = 源码 + 本集成说明,
> 逻辑对齐 figma2html 的 render.js / assemble.js(已实跑验证的参照实现),cc API 用法靠 review + 类型自洽。
> 首次接入请按 §6 集成清单冒烟。**

## 1. 元素映射全表

| IR 字段 | Creator 落点 | 说明 |
|---|---|---|
| `el`(每个) | `Node` + `UITransform` | 节点名取 `el.name \|\| el.id`;原始 IR 挂在 `node.__figEl` 供回查 |
| `x,y,w,h` | `UITransform.contentSize` + `position` | 坐标转换见 §2 |
| `z` | 兄弟顺序 | els 按 z 升序稳定排序后依次 `addChild` → 同父追加顺序即绘制顺序(等效 `setSiblingIndex`) |
| `parent` | 节点树父子 | 空 = 挂层根;`buildSubtree` 抽子树时根的 parent 置空(对齐 `subtreeOf`) |
| `rot` | `node.angle = -rot` | CSS 顺时针为正,Creator 逆时针为正 → 取负;旋转枢轴见 §3 |
| `opacity` | `UIOpacity.opacity = round(opacity×255)` | 仅 `opacity !== 1` 时加组件 |
| `fill`(纯色) | `Graphics.fillColor` + `roundRect` + `fill()` | rgba → `Color(r,g,b,a×255)` |
| `fill`(linear-gradient) | **首色回退**(known-loss) | Graphics 无渐变填充;取首个 stop 纯色 + `console.warn` |
| `radius` | `roundRect(..., r)` | 四角相等 → 直接用;**四角不等 → 统一取 tl**(known-loss,`Graphics.roundRect` 单半径 API,分段贝塞尔可做但命中率低不抵复杂度) |
| `border` | `Graphics.lineWidth/strokeColor` + `stroke()` | CSS 是内描边(border-box)、Graphics 沿路径居中 → **路径内缩 width/2** 逼近 |
| `shadow` | **不渲**(known-loss) | Creator 无逐节点 box-shadow 轻量手段 |
| `blur` | **不渲**(known-loss) | 同上(全屏后处理不适合逐节点) |
| `img` | `Sprite`(`SizeMode.CUSTOM`) | `resources.load(assetRoot + stem(img) + '/spriteFrame', SpriteFrame)`;缺失 → 透明回退 + warn(不平涂占位,对齐 render.js) |
| `imgSize`(cover/contain) | **一律拉伸铺满**(known-loss) | `SizeMode.CUSTOM` 铺满 contentSize;capture 的图多为 1:1 导出,失真有限 |
| `vec: true` 缺图 | 透明回退 | 与 `img` 缺失同语义 |
| `text.content` | `Label.string` | |
| `text.size / color` | `fontSize` / `color` | |
| `text.lh` | `lineHeight`(`lh>0 ? lh : round(size×1.2)`) | render.js 的 `normal` ≈ 1.2 |
| `text.alignH / alignV` | `horizontalAlign / verticalAlign` | flex-start/center/flex-end → LEFT·TOP/CENTER/RIGHT·BOTTOM;`textAlign` 与 `alignH` 冲突时取 alignH(Label 只有一套对齐,known-loss) |
| `text.weight` | `isBold = weight ≥ 600` | 无 500/800 分档(known-loss) |
| `text.family` | 系统默认字体 | 字体族不还原(known-loss);要还原需 TTFFont 资产 + hook 覆盖 |
| `text.stroke` | `LabelOutline`(width + color) | |
| `text.ls`(letterSpacing) | **不渲**(known-loss) | Label 3.x 无字距属性 |
| 文本溢出 | `Overflow.CLAMP` + `enableWrapText=false` | 保住框内对齐、对齐 render.js nowrap;系统字体偏宽可能截字(known-loss);显式 `\n` 仍换行 |
| `cap.stageBg` | `stage-bg` 子节点(Sprite 或 Graphics) | `url(..)` → Sprite;纯色/渐变 → Graphics(渐变取首色);sibling 0 垫底 |

flow.json 映射(`flow-binder.ts`,语义对齐 assemble.js):

| flow 字段 | Creator 落点 |
|---|---|
| `base` | 常驻 `layer-base` 节点,`FigmaUI.buildEls` 全屏构建 |
| `modals[*]` | 每弹窗一个隐藏层:半透明黑 backdrop(Graphics `rgba(0,0,0,0.5)` 全 stage)+ `FigmaUI.buildSubtree(cap, roots)`;`openModal` 互斥显示 |
| `events[].on:"click"` | `Node.EventType.TOUCH_END`;元素级监听 `propagationStopped=true`(对齐 stopPropagation) |
| `events[].el`(id) | 底屏 id→Node 索引(对齐 `baseEl`) |
| `@any:<modal>` | 层节点 TOUCH_END(子元素未拦截的触摸冒泡到层) |
| `@panelOutside:<modal>` | 层 TOUCH_END + `panel.UITransform.getBoundingBoxToWorld().contains(触点)` 反选 |
| `guard` | state 全真才放行(null/undefined/false/0/'' 均为假),失败回调 `onGuardFail` |
| `openModal/closeModal/toggleFlag/send` | 内置;其余 `do` 名 → 查 hook 注册的 action |
| `list` | 容器首行缓存为模板(行距 = 前两行 y 差,单行取行高)→ `instantiate` 克隆、`rowFn` 填充、行绑 TOUCH_END → `onRowClick` |
| `bindings.checkbox` | `paintRect` 重绘双态底色 + `check-mark` 子 Label 显隐 |

## 2. 坐标转换(核心,必须理解再动)

IR:y 向下、原点帧左上、几何是**相对帧的绝对 px**。Creator:y 向上、position 是**子锚点相对父锚点**。

**约定:每节点 `UITransform.setAnchorPoint(0,1)`(左上锚)** → 节点锚点=自己的左上角,于是:

```
child.position = ( childAbsX - parentAbsX,  -(childAbsY - parentAbsY) )
```

通式(支持任意锚,旋转节点要用):设子锚 `(ax,ay)`、父锚 `(pax,pay)`,`dx/dy` 为 IR 绝对坐标差:

```
pos.x = (-pax·pw) + dx + ax·cw          // 父锚点→父左上角 + 左上差 + 子左上角→子锚点
pos.y = ((1-pay)·ph) - dy - (1-ay)·ch
```

锚 (0,1) 代入即退化为约定式。**挂载根(FigmaUI 组件节点 / FlowBinder 的层节点)必须锚 (0,1)**,代码已自动设置。

**手算自证**(夹具 `screen-login.ui.json`):父 `1:10` server-pill 绝对 (260,1280) 560×90;子 `1:12` gem 绝对 (286,1302) 46×46。
dx=286−260=26,dy=1302−1280=22 → `child.position = (26, -22)`:锚在父左上角右 26px、下 22px —— 与 CSS `left:26px; top:22px` 完全对应。✓
根级 `1:10`(parent=''):position = (260, −1280),即根容器左上角右 260、下 1280。✓

- 根容器:`contentSize = (cap.w, cap.h)`、锚 (0,1),**置于屏幕左上**——给组件节点加 `Widget`(Left=0、Top=0 对齐 Canvas),见 §4。

## 3. 旋转(rot)

- 方向:CSS `rotate(θdeg)` 顺时针为正;Creator `node.angle` 逆时针为正 → **`angle = -rot`**。
- 枢轴:CSS `transform-origin: center`;Creator 绕**锚点**转。若旋转节点仍用锚 (0,1) 会绕左上角转、位置漂移。
  实现:**rot≠0 的节点改锚 (0.5,0.5)**,位置按 §2 通式补偿(`+cw/2, -ch/2`),枢轴即与 CSS 一致。
  其子节点用通式换算父锚偏移,几何仍正确。
- figma REST 对组件实例内部子节点常不回 `relativeTransform` → `rot` 回退 0,这是**上游 capture 的已知限制**
  (见 figma2html `references/ui.json-schema.md`),Cocos 侧同样中招;需要角度的节点走 hook 手动覆盖 `node.angle`。

## 4. Canvas / 适配建议

- **designResolution = cap.w × cap.h**(如 1080×1920),Fit 策略:竖屏 UI 建议 **Fit Width**(SHOW_ALL 会两侧留黑,按项目取舍)。
- 场景结构建议:

```
Canvas (cc.Canvas, designResolution = cap.w × cap.h)
└─ FigmaRoot (UITransform 锚(0,1) + Widget: AlignTop=0, AlignLeft=0)
   ├─ FigmaUI 组件(单屏预览)         ← 二选一
   └─ FlowBinder 组件(整流程:底屏+弹窗+事件)
```

- Widget 把根钉在 Canvas 左上;超出 designResolution 的适配裁切/黑边由 Canvas 策略统一处理,IR 内部几何不参与适配(像素定位)。

## 5. known-loss 总表

| 项 | 损失 | 补救 |
|---|---|---|
| `blur` | 不渲 | 需要时用预烘焙贴图或后处理,hook 层做 |
| `shadow` | 不渲 | 同上;或九宫格阴影贴图 |
| 复杂/线性渐变 | 取首个 stop 纯色 | 需要时导出为贴图走 `img` |
| 四角不等圆角 | 统一取 tl | 需要时导出贴图;或改 Graphics 分段路径(未实现) |
| 字体族 / 精确字重 | 系统字体 + `isBold(≥600)` | 挂 TTFFont 资产,hook 覆盖 `label.font` |
| `letterSpacing` | 不渲 | — |
| `textAlign` vs `alignH` 冲突 | 取 alignH | 多行富对齐用 RichText 自行改造 |
| `imgSize` cover/contain | 一律拉伸铺满 | capture 图多为 1:1 导出,通常无感 |
| 文本 CLAMP 截字 | 系统字体偏宽时可能截 | 调小 fontSize 或 hook 放宽 contentSize |
| 实例内部 `rot=0` | 上游 API 限制 | hook 手动 `node.angle` |
| `motion.json` 里 `unresolved` 的曲线 | 该转场瞬时显隐 | figma 没公开 `BOUNCY` / `*_BACK` 的控制点;别编数,见下 |

## 5.5 转场缓动(`flow.events[].transition` + `flow.motion`)

> 历史:本节曾是"整块 known-loss —— 运行时一律无视转场"。2026-07-29 已实现。

### 曲线在 python 侧解算,TS 侧只插值

```
flow.json ──► scripts/bake_motion.py ──► motion.json(每条曲线 17 个采样点)
                    │ (= scripts/motion.py,figma2html 主拷贝的逐字节镜像)
                    ▼
              FlowBinder.motionAsset(JsonAsset)──► 线性插值 ──► 贴到节点上
```

**为什么不让 TS 自己算。** figma 给的是一条具体曲线(`cubic-bezier(.32,.72,0,1)`)或一组弹簧
参数;Creator 的 `easing.quadOut` 之流是**另一套同名不同形**的曲线。让每个引擎各挑"最像的
内置缓动",同一份 IR 在六个引擎里就是六种手感,而每家测试照样绿(实测:easeOutCubic 与
`cubic-bezier(.23,1,.32,1)` 最大差 **19.8 个百分点**,且差在起步段)。所以 cocos 虽然没有
转换器可挂烘焙,也**单独带一个烘焙 CLI**,产出与 godot/unity/unreal 一起进
`tools/conformance` 逐点对账。

⚠️ **帧间必须线性插值**:采样点一致只保证**关键帧上**一致。Godot 的默认切线把每段两头压平、
Unity 的默认平滑切线在段内拱起来 —— 两家都栽过。`sampleCurve()` 因此是显式的线性插值。

### 映射

| 声明 | Creator 落点 |
|---|---|
| `events[].transition.type` = `DISSOLVE` / 未知 | 只淡入淡出(层 `UIOpacity`) |
| = `SCALE_IN` / `SCALE_OUT` | 面板 `setScale`,`fromScale`→1(出场反向);**绕中心**,见下 |
| = `MOVE_IN` / `SLIDE_IN` / `MOVE_OUT` / `SLIDE_OUT` | 面板 `setPosition`,按 `direction` 从层的一整边滑入(cocos y 向上 → `BOTTOM` 取负) |
| `duration` | 秒 = ms/1000;`schedule(step, 0)` 逐帧推进,`elapsed/dur` 归一化 |
| `motion.press` | 可点元素 `TOUCH_START` 缩到 `scale`,`TOUCH_END`/`TOUCH_CANCEL` 复位 |
| `motion.stagger` | `renderRows` 每行 `scheduleOnce(index × step)` 后淡入 + 上滑 `from` px |
| `motion.guardFail` | guard 拒绝时抖最后按下的元素(`sin` 相位 × 衰减,一次性不复用转场曲线) |
| 曲线 `unresolved`(无采样点) | 跳过 = 该转场瞬时;不猜控制点 |
| 未配 `motionAsset` | 全部瞬时显隐 —— 声明在案的降级,不是静默丢失 |

**两个 cocos 专属的坑**:

1. **缩放要绕中心补位置**。节点锚是 (0,1)(§2),`node.setScale` 因此以**左上角**为基准,
   直接设 scale 会让面板往右下角坍缩。补偿:`position += (w(1−s)/2, −h(1−s)/2)`
   (`scaleAboutCenter()`)。
2. **位移/缩放只贴面板本体,遮罩只跟着淡**。backdrop 是弹窗层的子节点 —— 把 transform 贴在
   **层**上,遮罩会跟着面板一起滑/缩:顶部不变暗、四边缩进露出底屏。html/godot/unity 三端
   同构同病,**曲线取值一个不差**,是 Godot 实机截图才抓到的。`flow.modals[*].panel` 没声明时
   就只淡,不猜该动谁。

### 验证等级(诚实)

- ✅ 采样点与 godot / unity / unreal **逐点一致**(`tools/conformance`,含贝塞尔与弹簧)。
- ✅ TS 严格类型编译门(tsc `--noEmit` 对官方 `@cocos/creator-types` 3.8.3,零错)。
  可复现:`cd tools/cocos-typecheck && npm ci && python3 check.py`;它跑两条 ——
  零错,**以及**往真源码里种一个必然的类型错误后 tsc 必须报出来(只跑前者证明不了"门有牙":
  配置写歪时它同样是绿的)。`tools/conformance` 另有一条离线守卫,盯着 tsconfig 的 `files`
  覆盖了每个 runtime `.ts`、且文档与配置说的是同一个版本。
- ✅ 源码级守卫(`scripts/tests/test_runtime_source.py`):线性插值在、内置缓动没被导入、
  transform 没贴到层上、缩放补了锚点偏移。
- ❌ **未在 Creator 内实机运行** —— 与本后端其余部分同一等级。曲线的值对了不等于画面对了
  (上面那个遮罩 bug 就是活证据)。

## 6. 集成冒烟清单(首次接入必做)

1. `python3 scripts/ui_check.py flow.json <capDir>` 全绿,按 `assets-manifest.json` 把图放进 `assets/resources/<assetRoot>/`(保持 `_assets/...` 相对路径、Creator 里 stem 同名)。
2. `.ui.json` / `flow.json` 拷进工程(Creator 会把 `screen-login.ui.json` 导成名为 `screen-login.ui` 的 JsonAsset —— FlowBinder 按此 stem 匹配)。
3. 按 §4 建 Canvas + FigmaRoot,先挂 **FigmaUI** 单屏对照 figma 截图核几何(重点:左上对齐、子元素相对位置、z 序)。
4. 再挂 **FlowBinder**,hook 组件在自身 `onLoad` 里 `FlowBinder.registerHook({register, init})`(FlowBinder 在 `start()` 构建,onLoad 注册必然来得及)。
5. 逐事件点验:弹窗开合、guard 拦截、checkbox 双态、列表克隆行点击。
