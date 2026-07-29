# docs-assets — 重录 README 里的两个 GIF

```bash
python3 tools/docs-assets/shoot_gif.py figma2html/examples/login docs/shots/demo.gif
python3 tools/docs-assets/shoot_gif.py figma2html/examples/main  docs/shots/demo-main.gif
```

第三个参数是分镜名(默认取示例目录名),对应 `gif_driver_<名>.js` 与 `shoot_gif.py` 里的 `FRAMES[<名>]`。

需要 **Edge/Chromium**(找不到就设 `EDGE_PATH`)与 **Pillow**。

> ⚠️ 这里是**唯一**不守"纯标准库"那条规矩的地方,所以它放在 `tools/` 而不是任何 skill 里 ——
> 七个 skill 必须能单独安装且零依赖。本目录不参与任何测试,`run_all_tests.py` 不碰它。

## 为什么不是录屏

无头浏览器不能录屏,而 `--virtual-time-budget` 去卡中间帧不可靠:时间被压缩,截图那一刻
动画通常已经跑完 —— 于是"动效演示"里一帧动效都看不见(踩过)。

这里改成**分帧确定性重放**:每帧起一个新页面,`?step=N` 让 driver 演到那一步,
再用 Web Animations API 把**真实动画对象** `pause()` 并把 `currentTime` 定到指定毫秒。
停住的是真动画在那一刻的样子,不是手改样式伪造的中间帧。同一个脚本跑两次得到同一串图。

## ⚠️ 只有声明式动画录得到

**无头这一路一次 `requestAnimationFrame` 都不会触发。** 实测:一个每帧自增的计数器,跑完整个
`--virtual-time-budget` 预算之后仍然是 `0`(而同一页里的 `setTimeout` 正常触发)。

所以:

| 怎么做的动效 | 录得到吗 |
|---|---|
| CSS 过渡 / WAAPI 关键帧 | ✅ 能 `pause()` 钉在任意毫秒 |
| 逐帧 JS 循环(rAF / 定时器里自己算位置) | ❌ 录出来是**静止**的 |

这不只是录制器的怪癖,它**反过来影响了示例该怎么写**:`examples/main` 的金币飞行因此是
"先把整条轨迹采成 24 个关键帧、再交给浏览器播",而不是每帧用 JS 算一个位置 ——
后者不但录不到,在真浏览器里也跑不上合成线程。

**录不到的那部分要如实说**:主界面示例里的数字滚动是逐帧改文本的(catalog 里就该这么做),
GIF 里因此只看得到**滚完之后**的数,看不到滚的过程。示例代码给它加了一条定时器兜底,
保证"到账"这个事实不依赖有没有人在看那一帧。

## 改动它

- 帧序列 = `gif_driver_<名>.js` 的 `STEPS`(做什么 + 停在第几毫秒;`null` = 让它跑完)
- 每帧在 GIF 里停留多久 = `shoot_gif.py` 的 `FRAMES[<名>]`
- **`null` 是陷阱**:一次性效果(guard 抖动)停 `null`,截图时它早已归位,那一帧什么都没有。
  抖动要停在位移峰值附近(`sin(2πp)(1−p)` 在 p≈0.22 最大)。
- 出场比入场难截:`closeModal` 播完会用一个**不受 `pause()` 影响的定时器**把层藏起来,
  得先把时钟停掉再 freeze,否则拍到的是底屏。
- 改完**看一眼联络表**再提交:半尺寸下看不出的效果(比如 `scale(0.96)` 的按压)放进去是浪费帧
- 脚本会硬校验"每一帧都与前一帧不同" —— 这份产物的全部规格就是**它在动**
