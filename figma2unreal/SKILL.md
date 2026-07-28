---
name: figma2unreal
description: 把 figma2html 管线捕获的中间表示(IR:.ui.json 像素快照 + flow.json 交互声明)落到 Unreal UMG —— python 预处理器把全部 CSS 风格串离线解析成强类型 uespec.json(可测),C++ 运行时解释器(UUserWidget + WidgetTree)零解析建 UI 与交互。输入 = figma2html capture 的产物;本 skill 是 Unreal 后端,不含 capture。要在 UE 5.3+ 工程里还原 figma 界面像素与交互(底屏+弹窗/守卫/列表/勾选)时使用。
---

# figma2unreal — figma IR → Unreal UMG

## 架构(两层,谁干什么)

```
figma 帧
  │ figma2html:figma_capture.py(capture 归它,本 skill 不管)
  ▼
<屏>.ui.json ×N + flow.json          ← IR 真源(CSS 风格字符串 + figma node id)
  │ 本 skill:scripts/ui_to_uespec.py     【python 预处理器,离线可测】
  ▼                                      所有 CSS 串 → 数值/结构;引用校验,坏引用退非 0
<屏>.uespec.json ×N + flow.uespec.json ← 强类型规格(rgba 数组/四角圆角/父相对几何/结构化事件)
  │ 拷进 UE 工程 Content/FigmaUi/Spec/
  ▼
runtime/FigmaUiWidget(.h/.cpp)          【C++ 解释器,零解析】WidgetTree 按 uespec 建视觉
runtime/FigmaFlowComponent(.h/.cpp)     assemble.js 语义:底屏+弹窗/守卫/toggleFlag/send/列表/勾选
                                        域内语义(数据→行、回填)走 IFigmaAppHook,不进引擎
```

## 用法管线

1. **capture(前置,figma2html 的活)**:得到 `screen-*.ui.json` 与手写的 `flow.json`。
2. **转 uespec**:

   ```
   python3 scripts/ui_to_uespec.py <cap.ui.json> <outdir>                # 单屏
   python3 scripts/ui_to_uespec.py <cap.ui.json> <flow.json> <outdir>   # 整套:flow.caps 引用的所有屏
                                                                        # 一并转出 + flow.uespec.json
   ```

   校验失败(flow 引用了不存在的 figma node id / cap / modal)→ stderr 报错、exit 2、不产 flow.uespec。
3. **拷进 UE 工程**:uespec → `Content/FigmaUi/Spec/`;素材 png → `Content/FigmaUi/Assets/`;
   `runtime/*.h/.cpp` → `Source/<Game>/FigmaUi/`。依赖模块与放置细节照 `references/mapping.md` §5。
4. **加载**:Actor 挂 `FigmaFlowComponent`、设 `AppHook`、`InitFlow(PC)`;
   单屏预览用 `UFigmaUiWidget::BuildFromSpecFile("FigmaUi/Spec/screen-login.uespec.json")`。

## 硬约束

- **解析只在 python 侧**:C++ 里出现任何字符串样式解析(rgba/px/gradient 正则)= 架构违规;
  新样式字段一律加在 `ui_to_uespec.py` + 测试,C++ 只加"消费强类型"的分支。
- **uespec 输出必须确定性**(UTF-8 无 BOM、`\n`、固定键序):`tests/golden/` 逐字节把关,
  有意变更格式必须重生成金样并说明。
- **改转换器必跑** `python3 scripts/tests/run_all.py`,全绿 exit 0 才算完。
- **改 uespec 字段或 runtime C++ 必过两道无引擎门**(已并入 run_all,CI 也跑):
  `scripts/uespec_contract.py` —— python 新产的字段 C++ 不读、或 C++ 读了没人产,都会红;
  确属 known-loss/元数据则写进它的 `WAIVERS` 并给出理由(与 mapping.md §4 对齐)。
  `scripts/uht_lint.py` —— UE 反射规约 R1-R6(generated.h 末位 / GENERATED_BODY /
  UINTERFACE 配对 / BlueprintNativeEvent 走 `Execute_` / UObject 成员 GC 可见性 /
  include 模块登记)。GC 上确有例外就近写 `// GC-OK: 理由`,不许默默留白。
- **C++ 未在引擎内编译验证**(交付态=源码+集成说明,声明写在每个文件头与 mapping.md);
  上面两道门查的是**规约与契约,不是 API 真值**(`FSlateFontInfo` 有没有某字段只有真编译能答);
  首次集成编译若有小版本 API 出入,属局部修正,不得借机把解析逻辑挪进 C++。
- 引擎(结构与机制)与 app(域内语义)分工对齐 figma2html:选服回填、行文案、协议发送
  只准走 `IFigmaAppHook` 实现,不进 FigmaFlowComponent。
- known-loss(渐变首停靠色回退/阴影/模糊/字体族等)见 `references/mapping.md` §4,
  回退必须 `UE_LOG` 留痕,不许静默丢失;渐变材质方案是**后续路线**,本版不实现。
- 本 skill 项目无关、可移植;文档中文、标识符英文。

## 文件

| 路径 | 作用 |
|---|---|
| `scripts/ui_to_uespec.py` | IR → uespec 预处理器(纯标准库、argv、确定性) |
| `scripts/uespec_contract.py` | 无引擎门①:python 产出字段 ↔ C++ 读取字段双向对账(含 WAIVERS 声明) |
| `scripts/uht_lint.py` | 无引擎门②:UE 反射规约 R1-R6 静态检查 |
| `scripts/tests/run_all.py` | 发现式 runner(全部 test_*.py,失败 exit 1) |
| `scripts/tests/test_ui_to_uespec.py` | 解析器手算断言 + 夹具几何 + flow 校验退非 0 |
| `scripts/tests/test_golden.py` | screen-login/flow 的 uespec 与金样逐字节一致 |
| `scripts/tests/test_contract.py` | 门①的真代码断言 + 故意漂移样本(证明有牙) |
| `scripts/tests/test_uht_lint.py` | 门②的真代码断言 + 每条规则一个故意写错样本 |
| `scripts/tests/fixtures/` | login 三屏 + flow(复制自 figma2html examples/login) |
| `scripts/tests/golden/` | 金样 uespec |
| `runtime/FigmaUiWidget.h/.cpp` | uespec → Widget 树(UE 5.3+,UMG/Slate/SlateCore/Json/JsonUtilities) |
| `runtime/FigmaFlowComponent.h/.cpp` | flow.uespec → 交互(含 IFigmaAppHook、点击代理) |
| `references/mapping.md` | IR→UMG 映射全表、known-loss、集成步骤、DPI 建议 |
