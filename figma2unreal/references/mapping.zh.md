# IR → UMG 映射全表(figma2unreal)

> **声明:C++ 运行时(runtime/)未在引擎内编译验证** —— 交付态 = 源码 + 本集成说明。
> 目标引擎 **UE 5.3+**;首次集成请按下文步骤编译,若个别 API 因引擎小版本有出入,
> 均为局部修正(集中在 FSlateBrush/FSlateFontInfo 字段与 UMG Setter),不影响架构。
>
> **无引擎门(已有,CI 每次跑)**:装不了引擎也不等于零把关,两道确定性静态门顶着 ——
> `scripts/uespec_contract.py`(python 产出字段 ↔ C++ 读取字段双向对账,§4 的 known-loss
> 逐条对应它的 WAIVERS 声明)与 `scripts/uht_lint.py`(UE 反射规约 R1-R6:generated.h 末位、
> GENERATED_BODY、UINTERFACE 配对、BlueprintNativeEvent 走 Execute_、UObject 成员 GC 可见性、
> include 模块登记 ⊆ §5 的 Build.cs)。**它们查规约与契约,不查 API 真值** ——
> `FSlateFontInfo` 到底有没有 `LetterSpacing` 这类问题,仍然只有真编译能回答。

架构分工(与 figma2html 双层对齐):

| 层 | 产物 | 职责 |
|---|---|---|
| python 预处理器 `scripts/ui_to_uespec.py` | `<屏>.uespec.json` / `flow.uespec.json` | **全部 CSS 字符串解析**成强类型数值/结构 + 引用校验,离线可测(tests 全绿) |
| C++ 解释器 `runtime/FigmaUiWidget` | Widget 树 | **零解析**,按 uespec 用 WidgetTree 建 UI(视觉) |
| C++ 解释器 `runtime/FigmaFlowComponent` | 交互 | assemble.js 语义:底屏+弹窗/守卫/toggleFlag/send/列表克隆/checkbox;域内语义走 `IFigmaAppHook` |

## 1. 元素映射

| IR 字段(.ui.json) | uespec 强类型 | UMG 落点 | 保真度 |
|---|---|---|---|
| `x,y,w,h`(相对帧绝对 px) | `absX/absY` + `localX/localY`(父相对,照 render.js pass2) | `UCanvasPanelSlot::SetPosition(local)/SetSize`;抽子树的根用 abs | 精确 |
| `parent` 嵌套 | 同 | 容器元素 → `UCanvasPanel`(自身视觉铺满作背景),子元素挂进面板 | 精确 |
| `z` | `z`(int) | `UCanvasPanelSlot::SetZOrder`(捕获序即绘制序) | 精确 |
| `rot` | `rot`(度) | `SetRenderTransformAngle` + 中心 pivot(=CSS `transform-origin:center`) | 精确(figma INSTANCE 内部 rot 缺失是上游 API 限制,同 HTML 版) |
| `opacity` | `opacity` | `SetRenderOpacity` | 精确 |
| `fill: rgba(...)` | `{type:"solid",rgba:[r,g,b,a]}` | `UBorder` + `FSlateBrush`(RoundedBox)`TintColor` | 精确(sRGB→线性由 `FromSRGBColor`) |
| `fill: linear-gradient(...)` | `{type:"linear",angleDeg,stops:[{rgba,pos}]}` | **首停靠色纯色回退 + UE_LOG**(known-loss,材质路线见 §4) | 回退 |
| `fill: radial-gradient(...)` | `{type:"radial",stops:[...]}` | 同上回退 | 回退 |
| `paths` + `viewBox`(v1.2) | **没有** | — | known-loss。本后端一贯的立场是 *carry*(python 段只预处理,取舍留给 C++ 运行时),但 `convert_cap` 是逐字段映射的,没列进去的键根本不进 uespec。对这三个字段而言那不是 carry,是丢,如实记在这里 |
| `clip`(v1.1) | **没有** | — | known-loss;子元素会溢出父盒 |
| `borderAlign`(v1.2) | **没有** | — | known-loss;字段没了之后,往外那半描边(`shadow` 头部的 `0 0 0 Npx` 环)与真阴影再也分不开 |
| `radius: "37px"` / 四值 / `50%` | `[tl,tr,br,bl]` px 浮点(`50%`→`min(w,h)/2`) | `FSlateBrush::OutlineSettings.CornerRadii`(UE5 RoundedBox 原生四角) | 精确(椭圆角 50% 为标量近似) |
| `border: "4px solid rgba(..)"` | `{width,rgba}` | `OutlineSettings.Width/Color`(RoundedBox 描边) | 高(CSS border 内收 vs Slate outline 居线的亚像素差) |
| `shadow: "0px 4px 0px rgba(..)"` | `[{dx,dy,blur,rgba}]` | **不渲染 + UE_LOG(Verbose)**(known-loss) | 丢失 |
| `blur: "blur(4px)"` | `{radius}` | **不渲染 + UE_LOG(Verbose)**(known-loss;`UBackgroundBlur` 只糊背板非自身,不等价) | 丢失 |
| `img` / `imgSize` | `{path,mode}`(mode:cover/contain/stretch/tile) | `UImage` + `LoadObject<UTexture2D>`(路径约定见 §3);**缺图回退透明 + UE_LOG(Warning)**,不平涂 | 高(cover≈stretch:figma 导出图长宽比=元素比;contain/tile 拉伸回退) |
| `vec:true`(矢量簇折叠图) | `vec`(仅记录) | 走 `img` 的通用图片路径(capture 已把矢量簇折成 png);缺图即透明占位。**运行时不消费 `vec` 标志本身** | 同 img |
| `stageBg` | `{type:solid/linear/radial/image,...}` | 全帧底 UBorder/UImage,ZOrder −10000(弹窗层不画) | 同 fill/img |

## 2. 文字映射

| IR text 字段 | uespec | UMG 落点 | 保真度 |
|---|---|---|---|
| `content` | 同 | `UTextBlock::SetText`(含 `\n` 由 FText 保留) | 精确 |
| `color` | `rgba` 数组(含 `#hex` 回退解析) | `SetColorAndOpacity` | 精确 |
| `size`(px) | `size` | `FSlateFontInfo::Size = round(px×0.75)`(CSS px→Slate pt,96dpi) | 高 |
| `weight` | `weight` | 字面二分:≥600→"Bold",否则 "Regular"(引擎 Roboto 两字面) | 近似 |
| `family` | `family`(仅记录) | **不映射具体字体**,统一 `DefaultFontObject`(未设→引擎 Roboto)→ known-loss;**CJK 必须在蓝图子类指定中文字体资产** | 丢失(族) |
| `lh`(px) | `lh` | `SetLineHeightPercentage(lh/(size×1.2))` 近似 | 近似 |
| `ls`(px) | `ls` | `FSlateFontInfo::LetterSpacing = round(ls/size×1000)`(1/1000 em) | 高 |
| `alignH/alignV`(盒内对齐) | `start/center/end` | 外包 `UBorder` 的 `SetHorizontalAlignment/SetVerticalAlignment`(=render.js flex 对齐) | 精确 |
| `textAlign` | 同 | `SetJustification`(justified→Left) | 精确 |
| `stroke`(-webkit-text-stroke) | `{width,rgba}` | `FSlateFontInfo::OutlineSettings`(FontOutline) | 近似(CSS `paint-order:stroke fill` 是描边垫底,FontOutline 同为外描,视觉接近;粗描边时字重观感略胖) |

## 3. flow / 交互映射(assemble.js 语义 ↔ FigmaFlowComponent)

| flow.uespec | UE 实现 |
|---|---|
| `base` | `UFigmaUiWidget` `AddToViewport(0)` 常驻 |
| `modals[*].roots` | `BuildFromSpec(cap, roots)` 抽子树(根用 absX/absY,= render.js `subtreeOf`),`AddToViewport(50+i)`,初始 `Collapsed`;backdrop = 全帧 `UBorder rgba(0,0,0,0.5)` ZOrder −20000 |
| `events[].targets` `kind:node` | 底屏上按元素几何叠**全透明 UButton**(视觉 Widget 全部 HitTestInvisible,按钮独占命中;选它而非 `OnMouseButtonDown` 的理由:不动视觉树、不自管命中测试,见 `AddClickOverlay` 注释) |
| `kind:in`(v1.1) | 同样的叠加按钮,但建在该弹窗的 widget 里,ZOrder 40000 —— **必须**压过 `kind:any` 的全帧层(30000),否则弹窗里的 ✗ 被盖住、点不到 |
| `kind:any` | 该 modal 层全帧透明按钮(ZOrder 30000,最顶) |
| `kind:panelOutside` | 全帧透明按钮(ZOrder 9000)+ **面板盾**(panel 几何上的吞点击按钮,ZOrder≈10000+z)→ 只有面板外点击触发 |
| `guard` | `IsTruthy`:null/false/0/"" 为假(= assemble.js `guardOk`);失败回调 `OnGuardFail` |
| `do: openModal/closeModal/toggleFlag` | 组件内置;`send`→`IFigmaAppHook::OnSend`;其余→`OnCustomAction` |
| `list` | `PopulateList(Count)`:容器首子为模板行、第二行 top 差为步长,克隆 N 行(行内元素 id=`"<原id>#<行号>"`),行点击→`OnListRowClicked(i)`;行文案由 hook 用 `GetModalWidget(...)->SetElementText("3:23#0", ...)` 回填 |
| `bindings.checkbox` | 双态:`SetElementBrushColor`(checked/unchecked rgba)+ 懒建居中勾号 `UTextBlock`(24px Bold,= assemble.js) |
| `state` | `TMap<FString, FJsonValue>` 原样;`SetStateString/ToggleFlag` 变更后自动 `SyncBindings` + `OnStateChanged` |

## 4. known-loss 汇总

| 项 | 现状 | 后续路线(未实现,勿在本版做) |
|---|---|---|
| 线性/径向渐变 | 首停靠色纯色回退 + `UE_LOG(Warning)` | 通用渐变材质(`M_FigmaGradient`:2-8 stop 参数化 `UMaterialInstanceDynamic`),`UImage::SetBrushFromMaterial`;angleDeg/stops uespec 里已备齐 |
| box-shadow | 不渲染 + `UE_LOG(Verbose)` | 9-slice 阴影贴图或 RetainerBox 后处理 |
| layer blur | 不渲染 + `UE_LOG(Verbose)` | `UBackgroundBlur`(语义是糊背板,仅部分场景可代) |
| 字体族 | 统一 DefaultFontObject/Roboto;weight 只分 Regular/Bold | 项目字体表:family→UFont 资产映射 |
| 文字描边 | FontOutline 近似(非 paint-order 语义) | — |
| imgSize contain/tile | 拉伸回退 + `UE_LOG(Verbose)`(cover≈stretch,figma 导出图与元素同比) | Brush Tiling / 自定义 UV |
| 椭圆角 `50%` | `min(w,h)/2` 标量近似(正圆精确,非正方形椭圆略差) | — |
| `flow.events[].transition` | 烘成 `motion.json` 采样曲线,**FigmaFlowComponent 未接线 = 不播** | 见下面「转场缓动」 |

### 转场缓动(motion.json)

给了 `flow.json` 时,`ui_to_uespec.py` 会在 outdir 里多产一个 `motion.json`:
每条带转场的事件一份 **17 点等距采样曲线**(x/y 都是 0..1 进度)。

**为什么是采样点,不是 `EEasingFunc`。** figma 给的是一条具体曲线
(`cubic-bezier(.32,.72,0,1)` 或弹簧三参),`EEasingFunc::EaseOut` 是**另一条同名不同形**的曲线。
各后端各挑"最像的" = 同一份 IR 在六个引擎里六种手感,而每家测试都绿。
量级参考:easeOutCubic 与 `cubic-bezier(.23,1,.32,1)` 最大差 **19.8 个百分点**,且差在起步段。
`tools/conformance` 会拿这些点跟 godot/unity **逐点对账**。

这也与本后端的**职责边界**一致:python 段做完全部数值解算,C++ 侧零解析 ——
`FRichCurve::AddKey(x, y)` 逐点填进去即可,不需要在 C++ 里实现贝塞尔反解或弹簧微分方程。

| 处置 | 说明 |
|---|---|
| **known-loss:不播** | `FigmaFlowComponent` **尚未接线**;生成时打 `[known-loss]`,不是静默丢失 |
| **known-loss:具名弹簧预设** | `GENTLE/QUICK/BOUNCY/SLOW`、`*_BACK` figma 没公开控制点 → 标 `unresolved` 不采样,**不编数** |
| **approx:弹簧被 duration 截断** | 弹簧没有固定时长,窗口短于收敛时间就切一截,生成时打 `truncated:` |
| **known-loss:`SMART_ANIMATE`** | 同名图层自动配对插值,跨引擎无对应物;曲线照采,配对逻辑不实现 |

⚠️ `motion.json` **不进 `flow.uespec.json`**,是并列的独立产物 —— 免得动到
`uespec_contract.py` 守着的 python↔C++ 字段契约(那张表的每一项都要有 C++ 侧读取方)。

## 5. 集成步骤

1. **模块依赖**:项目 `Source/<Game>/<Game>.Build.cs`:

   ```csharp
   PublicDependencyModuleNames.AddRange(new string[] {
       "Core", "CoreUObject", "Engine", "InputCore",
       "UMG", "Slate", "SlateCore", "Json", "JsonUtilities"
   });
   ```

2. **拷源码**:`runtime/FigmaUiWidget.h/.cpp`、`runtime/FigmaFlowComponent.h/.cpp` →
   `Source/<Game>/FigmaUi/` 下,重新生成工程并编译(首次编译即本代码的验证时点)。

3. **uespec 放置**:`ui_to_uespec.py` 的产物(整套 `<屏>.uespec.json` + `flow.uespec.json`)
   拷到 `Content/FigmaUi/Spec/`(**原始 json 文件**,不导入为 uasset;打包时把该目录加进
   Project Settings → Packaging → *Additional Non-Asset Directories to Copy*)。
   `FigmaFlowComponent.SpecDirectory` 默认即 `FigmaUi/Spec`。

4. **素材放置**:capture 的 `_assets/**.png` 导入到 `Content/FigmaUi/Assets/`(保持子目录),
   贴图约定:`_assets/s17/bg.png` → 资产 `/Game/FigmaUi/Assets/s17/bg`(LoadObject 路径
   `"/Game/FigmaUi/Assets/s17/bg.bg"`,即导入后**包名=文件名去扩展**,不要改名)。
   建议贴图组 UI、关 mip、关 sRGB 勿动(保持默认 sRGB 开)。

5. **启动**:任意 Actor(常见 HUD/PlayerController 持有的管理 Actor)挂 `FigmaFlowComponent`,
   设 `AppHook`(蓝图或 C++ 实现 `IFigmaAppHook`),BeginPlay 里 `InitFlow(PlayerController)`。
   单屏预览可直接 `CreateWidget<UFigmaUiWidget>` + `BuildFromSpecFile("FigmaUi/Spec/screen-login.uespec.json")`。

6. **DPI 缩放**:uespec 几何是 `cap.w × cap.h`(如 1080×1920)的**像素真值**,Widget 树按 1:1 px 建。
   Project Settings → User Interface → DPI Scaling:DPI Curve 用 **Shortest Side** 规则,
   在设计短边(如 1080)处 Scale=1.0,让引擎对不同分辨率整体等比缩放(等价 render.js `mountStage`
   的 `scale = min(vw/fw, vh/fh)`)。别在 Widget 里自己再乘缩放。

7. **CJK 字体**:给 `UFigmaUiWidget` 建蓝图子类设 `DefaultFontObject` 为含中文字形的字体资产,
   或在 C++ 里赋值;不设会回退引擎 Roboto → 中文豆腐块。
