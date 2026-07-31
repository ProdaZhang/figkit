> **注:本文是 zh-CN 镜像,不是权威版。** 权威版 = 同目录的英文 `flow-events.md`;
> 改动先落英文,再镜像到这里。`tools/spec_parity.py` 会比对两边**代码块去注释后**的结构,
> 只改一边会红(散文可以有出入,schema 不行)。

> **FigKit IR Spec v1.0 — FROZEN 2026-07-03**
> 本文件是六后端(html/dsl/unity/godot/unreal/cocos)共享 IR 契约的**权威版本**;
> `figma2html/references/` 下的同名文件是随 skill 分发的工作副本(内容同源)。
> 冻结纪律:v1.0 起**只允许 additive**(新增可选字段/枚举值),不改既有字段形状;
> 下一次结构性改动须由某个后端撞出的真实缺口触发,并升 v1.1 记录于本头部变更行。
> 变更史:v1.0(2026-07-03)冻结 —— 经 6 后端互证(html 渲染/dsl 转写/unity 编译+导入/godot 实机渲染/unreal 强类型化/cocos 校验器)。

# flow.json — 流程/事件声明(组装器契约)

`assemble.js` 读 `flow.json` 把"底屏 + 弹窗叠加 + 事件 + 绑定"组装成可跑客户端。
**这是 figma 这条路的 Events 落点。** figma **是有**交互的 —— REST API 给全量 `interactions[]`(触发器、`NAVIGATE`/`OVERLAY`/`BACK`、条件分支、变量),`flow_from_figma.py` 把它们导进下面这个骨架。但那是**原型语义**:跳到哪个 frame、在 figma 播放器里、对着静态帧播。真要交付的客户端还需要的那半 —— 对应用状态的守卫、按真实数据克隆的列表行、引擎机制与业务代码的边界 —— figma 里**根本没有对应表达**,只能在这里手写声明。两者都按 **figma node id** 引用,所以抗重抓(重导像素不动它)。语法对齐 aigd 界面 DSL 的 `## Events`(`<触发> <元素> [守卫] -> 结果`)。

## 结构

```jsonc
{
  "stage": { "w": 1080, "h": 1920 },
  "caps": {                              // 名 → .ui.json 路径(各屏全保真)
    "base": "/screen-15.ui.json",
    "notice": "/screen-16.ui.json",
    "serverlist": "/screen-17.ui.json"
  },
  "base": "base",                        // 底屏(常驻)
  "modals": {                            // 弹窗:从某屏抽面板子树叠加
    "notice":     { "cap": "notice",     "roots": ["45:7040"] },
    "serverlist": { "cap": "serverlist", "roots": ["46:8246","46:8279","46:8280","46:8277","49:7736","46:8263"], "panel": "46:8263" }
  },
  "state":   { "agreed": false, "selected": null },   // 初始状态(flag/值)
  "events": [
    { "on":"click", "el":"45:7002",            "do":"openModal",  "arg":"notice" },
    { "on":"click", "el":["45:6993","45:6997"], "do":"openModal",  "arg":"serverlist" },
    { "on":"click", "el":"45:7006",            "do":"toggleFlag", "arg":"agreed" },
    { "on":"click", "el":"45:6998", "guard":["agreed","selected"], "do":"send", "arg":"Enter" },
    { "on":"click", "el":"@panelOutside:serverlist", "do":"closeModal" },
    { "on":"click", "el":"@any:notice",        "do":"closeModal" }
  ],
  "list": { "modal":"serverlist", "container":"46:8265", "onRowClick":"selectServer" },
  "bindings": {
    "checkbox": { "el":"45:7008", "flag":"agreed", "checkedBg":"rgba(255,255,255,1)",
                  "uncheckedBg":"rgba(255,255,255,0.2)", "mark":"✓", "markColor":"rgba(27,76,87,1)" }
  }
}
```

## 字段

- **caps / base / modals**:屏=完整 figma 帧的 .ui.json;`base` 常驻;`modals[*].roots` 是要抽出来叠加的顶层节点 id(弹窗常由"外框+页签+列表"多个顶层兄弟组成,故是数组);`panel` 用于"点面板外关闭"判定。
- **events[]**:`on`(目前 click)+ `el`(figma node id;数组=多个触发同一动作;特殊 `@any:<modal>` / `@panelOutside:<modal>`)+ 可选 `guard`(state 里这些都为真才放行)+ `do`(动作)+ `arg`。
- **内置 do**:`openModal(arg)` / `closeModal` / `toggleFlag(arg)` / `send(arg)`(转给 app 的 send action)。其余 `do` 名 → 查 app 注册的 action。
- **events[].transition**(可选,additive):设计师在 figma 里给这条连线挂的转场,原样带过来 —— `{ "type", "duration", "direction"?, "matchLayers"?, "easing": { "type", "bezier"?, "spring"? } }`。`type` 取 figma 的 `DISSOLVE / SMART_ANIMATE / SCROLL_ANIMATE / MOVE_IN / MOVE_OUT / PUSH / SLIDE_IN / SLIDE_OUT`;`spring` 保留 figma 的 `{mass, stiffness, damping}` 三元组。**IR 只记"设计说了什么",不记"某个后端怎么解"** —— 换算成解耦的(阻尼比, response)两参、以及把曲线采样成引擎原生关键帧,都在后端侧做(`motion.py` / `motion.ts`)。做不了动画的后端必须在自己的 known-loss 表里登记。带方向的那几种,`direction` 是面板**从哪条边**过来,而它走的距离是**舞台的**、不是面板自己的框:1080×1920 的舞台上,一块 860×1160 的面板起点在静止位置下方 1920px 处,不是 1160。v1.0 没把这句写出来,于是后端分成了两派 —— 同一条曲线、同一个毫秒,一边已经有 380px 面板在屏内,另一边还完全在屏外。**光比曲线取值永远抓不到这种事**,所以 `tools/conformance` 直接把基准钉住了。
- **motion**(可选,additive):**引擎自己拥有的机制**的默认动效 —— `press`(每个绑了事件的元素的按下态)、`stagger`(列表行逐项入场)、`guardFail`(元素说「错了」)。figma 里这三样都没有对应概念,所以这块的东西都是 `flow_from_figma.py --motion-defaults` 按具名预设**代笔写进来的**,每条带 `"source": "preset:<名>"`。**写进文件,不在运行时注入** —— 看得见是谁加的、能改能删。优先级恒为 **figma > 项目覆盖 > 预设**:导入器绝不碰 figma 声明过的转场,重跑也不会多加。
- **预设转场类型**:除 figma 那八种外,`events[].transition.type` 还可以是 `SCALE_IN` / `SCALE_OUT`(`fromScale` / `toScale`,默认 `0.95`)—— 默认的入场与出场,figma 的词汇表里没有名字。❌ 永不 `scale(0)`:现实里没有东西从虚无里长出来。出场**故意比入场短**,对称的开合读起来比实际慢。
- **list**:声明哪个 modal 的哪个容器是数据列表;`onRowClick` 指向 app action。app 用 `app.renderRows(modal, container, items, rowFn)`(register(app) 的形参,即全局 `FigApp`)注入带 `data-row` 的行,引擎委托行点击。
- **bindings.checkbox**:勾选框 2 态由引擎通用处理(白底+勾 / 半透+空)。其余域内字段(已选服回填、列表行配色、公告填充)由 app 的 `syncBindings(base)` / action 管。

> **已知缺口(v1.0)**:`events[].el` 只能指 **base 屏**的节点 —— 各后端的 binder 都是拿 id 去 base 图层解析。于是真实 figma 文件里最常见的那条连线,**弹窗里的 ✗ 按钮**,在 v1.0 里没有表达;现有写法 `@any:<modal>` / `@panelOutside:<modal>` 是"点哪都关 / 点面板外关",不是"点这个按钮"。`flow_from_figma.py` 遇到就逐条报告,不猜。这正是 CONTRIBUTING 要求的"由后端撞出的真实缺口",先记在这里,**不**顺手补 —— 补它要升 v1.1。

## app hook(域内专属,不进引擎)

`app.js` 导出 `window.APPHOOK = { register(app), init(app, net) }`:
- `register`:`app.registerActions({ send, selectServer, onPush, syncBindings, onReady, onGuardFail })`
- `init`:后置初始化(如 `applyBoot`:拉服务器列表 → `app.renderRows(...)`、默认选第一个、填公告)

引擎管**结构与机制**(底屏/弹窗/事件/守卫/勾选/列表克隆);app 管**域内语义**(服务器数据→行、选服回填、状态色)。
