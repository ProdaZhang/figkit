# main 示例 — 主界面(自足可跑 · 零网络 · 零 figma)

`login` 演的是**管线**(捕获 → IR → 六个后端),界面刻意做到最小。
这一份演另外两件事:

1. **这套 IR 撑不撑得住一个真正的游戏界面** —— 73 个元素、三屏、两种弹窗形态(网格 / 列表)、
   两个被 guard 锁住的页签。
2. **引擎不做、只能由 app hook 做的那半边。** 领奖时金币飞进顶栏、数字滚上去、胶囊闪一下 ——
   **figkit 一条都不实现**,它不知道哪个元素是"钱包"。这三条写在 `app.js` 里,
   方法与参数来自 [`figkit-motion`](../../../figkit-motion/)。

> 界面长什么样是**手写出来的**(`make_fixture.py` 构造 figma 节点树 → 喂给真正的
> `figma_capture.capture()`)。没有 figma 文件、不需要 token、不联网。风格是通用样例,
> 不是任何真项目的美术。

## 跑起来

**双击 `app.html`** 即可 —— `fixtures.js` 把 `flow.json` + 三份 `.ui.json` + 动效令牌内联成
`window.__FIGKIT_FIXTURES`,绕开浏览器在 `file://` 下对本地 XHR 的封锁。

点点看:**Bag**(下滑 + 格子逐项)· **Codex**(淡入 + 行克隆)· **Shop / Friends**(guard 拦下 + 抖动)·
**CLAIM**(飞 → 滚 → 闪)。

## 这份 flow.json 是怎么来的

正是 README「Real Figma input」的第 4、5 步:

```bash
# 4. 导入原稿里连好的线(本例是两条:Bag → 背包弹窗、Codex → 图鉴弹窗)
python3 ../../scripts/flow_from_figma.py nodes.json flow.json \
        main=screen-main.ui.json bag=screen-bag.ui.json codex=screen-codex.ui.json
# 5. 补上 figma 表达不了的那半边:guard、列表绑定、领奖这个自定义 action
#    再跑 make_fixture.py —— 它顺手用 motion.apply_defaults 补默认动效(幂等)
python3 make_fixture.py
python3 ../../scripts/flow_check.py flow.json
```

所以 `flow.json` 里的转场分两种,**看 `source` 字段就能分**:

| | 来源 |
|---|---|
| Bag 的 `MOVE_IN` · Codex 的 `DISSOLVE` | figma 原稿(没有 `source`) |
| 两个 `closeModal` 的 `SCALE_OUT` · press · stagger · guardFail | `"source": "preset:base"` |

**figma 原稿只画了入场,没画出场** —— 出场是预设补的。这在真实设计稿里是常态。

## 三条 hook 侧动效(app.js)

| 效果 | 目录词条 | 参数 |
|---|---|---|
| 飞向目标 | `catalog.md`「飞向目标 Fly to target」 | `fly-dur` `fly-hold` `fly-arc` `fly-stagger` |
| 数字滚动 | 「数字滚动 Number ticker」+ `algorithms.md §1` 贝塞尔求解器 | `tween-num` `ease-out` |
| 高亮闪 | 「高亮闪 Flash」 | `flash` |

**一个动效数字都没硬编**:值从 `fixtures.js` 内联的 `motion-tokens` 取,令牌名就是目录里的名字;
`test_main_example.py` 会检查 app.js 用到的每个令牌都真的存在。

两处值得一读的取舍:

- **金币轨迹先采样成关键帧、再交给浏览器播**,不是每帧用 JS 算位置。除了能上合成线程,
  还因为**无头浏览器一次 rAF 都不触发** —— 逐帧循环的东西录不进 GIF(见 `tools/docs-assets/README.md`)。
- **背包网格没走 `flow.list`。** 行克隆按"前两行的 y 差"定步长,而网格的前两格 y 相同 → 步长 0 →
  全叠在一起。它是一维机制,别硬套二维;逐项入场的顺序(先行后列)因此写在 hook 里。

## 改动它

```bash
python3 make_fixture.py     # 改了几何/文案就重跑;.ui.json / fixtures.js / flow.json 都是生成物
python3 ../../scripts/flow_check.py flow.json
python3 ../../scripts/tests/run_all.py      # 含 test_main_example.py
```
