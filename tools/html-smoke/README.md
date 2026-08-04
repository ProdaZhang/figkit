# html-smoke — figma2html 运行时的行为冒烟(真浏览器)

```bash
python3 tools/html-smoke/check.py     # 需要 Edge/Chromium;找不到就设 EDGE_PATH
```

```text
PASS modal_overlays_at_ir_coordinates_with_rows_cloned
PASS move_in_starts_a_full_stage_away_and_the_backdrop_stays_put
PASS guard_blocks_and_says_so
PASS checkbox_binding_toggles_both_ways
```

## 它补的是哪个洞

`assemble.js` / `render.js` 是各后端里**唯一实跑过**的参照实现,其余几家的 binder 都照着它写。
而它自己**一条自动化测试都没有** —— figma2html 那 70 条全在 python 侧(capture / flow_check /
flow_from_figma / motion / 夹具新鲜度),README 状态矩阵里它那一栏写的是"Edge headless
screenshot",也就是**人眼看过**。

代价是有账可查的:转场位移基准跟三个引擎漂了(html 按面板自身百分比、别家按舞台)、
guardFail 的抖动波形与三个引擎不同形 —— 两件都在这个洞里活着,直到有人把四份 binder
并排读了一遍。

## 断言的是数,不是像素

driver 在页面里量完把 JSON 写进 `<title>`,`check.py` 用 `--dump-dom` 读回来。
好处:数字能进 `assert`,截图只能靠人眼;而且纯标准库,连 Pillow 都不用。

**关键手法是"停在 0ms"。** 转场停在 0ms 时进度必然是 0,位移必然等于**基准本身** ——
舞台基准 1920 / 面板基准 1160,差 760px,断言里完全不必掺进缓动曲线。
(与 `tools/docs-assets` 的 GIF driver 同一套 `pause()` + `currentTime` 办法。)

## 写新用例时注意

- **量静止态前先 `settle()`**(把动画 `finish()` 掉)。第一次跑就踩了:面板 y 量出 2300 =
  380 + 1920,正好是入场起点,看着像"坐标全错了",其实是量在了转场半路上。
- **断言必须能红**。`rowsHaveText`(每行非空)那条写完就是废的:行是克隆首行来的、模板
  自带文字,`rowFn` 根本没被调用时它照样绿。改成"四行文字互不相同"才有牙。
  新加断言请照样做一次变异验证:把它该抓的缺陷种回 `assemble.js`,看它是不是真的红。

## 为什么在 `tools/` 而不在 skill 里

和 `docs-assets`、`cocos-typecheck` 一样:它要一个浏览器。
**七个 skill 必须能单独安装且零依赖**,`tools/run_all_tests.py`(纯标准库、离线)因此不碰它,
由 CI 单开一个 windows job 跑 —— windows runner 自带 Edge。
