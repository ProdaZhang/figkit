# docs-assets — 重录 README 里的 demo.gif

```bash
python3 tools/docs-assets/shoot_gif.py figma2html/examples/login docs/shots/demo.gif
```

需要 **Edge/Chromium**(找不到就设 `EDGE_PATH`)与 **Pillow**。

> ⚠️ 这里是**唯一**不守"纯标准库"那条规矩的地方,所以它放在 `tools/` 而不是任何 skill 里 ——
> 六个 `figma2*/` 必须能单独安装且零依赖。本目录不参与任何测试,`run_all_tests.py` 不碰它。

## 为什么不是录屏

无头浏览器不能录屏,而 `--virtual-time-budget` 去卡中间帧不可靠:时间被压缩,截图那一刻
动画通常已经跑完 —— 于是"动效演示"里一帧动效都看不见(踩过)。

这里改成**分帧确定性重放**:每帧起一个新页面,`?step=N` 让 `gif_driver.js` 演到那一步,
再用 Web Animations API 把**真实动画对象** `pause()` 并把 `currentTime` 定到指定毫秒。
停住的是真动画在那一刻的样子,不是手改样式伪造的中间帧。同一个脚本跑两次得到同一串图。

## 改动它

- 帧序列 = `gif_driver.js` 的 `STEPS`(做什么 + 停在第几毫秒;`null` = 让它跑完)
- 每帧在 GIF 里停留多久 = `shoot_gif.py` 的 `FRAMES`
- 改完**看一眼联络表**再提交:半尺寸下看不出的效果(比如 `scale(0.96)` 的按压)放进去是浪费帧
