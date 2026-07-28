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
**这是 figma 这条路的 Events 落点**:figma 没有交互逻辑,Events 在此**手写**、按 **figma node id** 引用、抗重抓(重导像素不动它)。语法对齐 aigd 界面 DSL 的 `## Events`(`<触发> <元素> [守卫] -> 结果`)。

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
- **list**:声明哪个 modal 的哪个容器是数据列表;`onRowClick` 指向 app action。app 用 `app.renderRows(modal, container, items, rowFn)`(register(app) 的形参,即全局 `FigApp`)注入带 `data-row` 的行,引擎委托行点击。
- **bindings.checkbox**:勾选框 2 态由引擎通用处理(白底+勾 / 半透+空)。其余域内字段(已选服回填、列表行配色、公告填充)由 app 的 `syncBindings(base)` / action 管。

## app hook(域内专属,不进引擎)

`app.js` 导出 `window.APPHOOK = { register(app), init(app, net) }`:
- `register`:`app.registerActions({ send, selectServer, onPush, syncBindings, onReady, onGuardFail })`
- `init`:后置初始化(如 `applyBoot`:拉服务器列表 → `app.renderRows(...)`、默认选第一个、填公告)

引擎管**结构与机制**(底屏/弹窗/事件/守卫/勾选/列表克隆);app 管**域内语义**(服务器数据→行、选服回填、状态色)。
