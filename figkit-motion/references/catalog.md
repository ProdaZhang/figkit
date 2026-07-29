# 效果目录 · 59 条

> **怎么用**:先过 [`routing.md`](routing.md) 的闸门(该不该动),再查表(该用哪个),最后到这儿看
> **方法**。每条给的是**引擎无关的方法 + 参数名**,不是某个引擎的实现 —— 参数值一律在
> [`../tokens.json`](../tokens.json),**本档一个裸数字都没有**。
>
> **`web 参考实现` 折叠块** = figma2html 后端的做法,可直接抄;其余五个后端照 **方法** 段自己实现。
>
> **标记**:`✅ figkit 已内置` = `motion.py` + 各后端 binder 已经在播,你不用重做,改值去
> `tokens.json` / `flow.json`(见 [`../SKILL.md`](../SKILL.md))。`⚠️ web 专属` = 只有 figma2html 用得上。

| 类 | 意思 | 规则 |
|---|---|---|
| ① 功能 UI | 控件的状态变化 | 过四关;时长 < `{motion.dur-cap}` |
| ② 循环 | 常驻、无限播放 | 不过频率关;弱 + 同屏 ≤ 3 处 |
| ③ 反馈 | 一次性、即时 | 不过频率关;越快越好 |
| ④ 演出 | 罕见、高价值的兑现 | **不受任何一关约束** |

---

## 通则 · 重放一个过渡效果前,必须先真正复位

**凡是用「过渡」(而非关键帧)的效果都吃这一刀** —— 缩放入场 / 弹入 / 逐项入场 / 按压…

元素身上挂着过渡时,**把它设回起点不会瞬间跳回去** —— 它会**平滑地退回去**,用的还是同一条时长。
下一帧再设终点,它才退了百分之几,于是从 `0.94` 过渡到 `1`,**肉眼完全看不出来**:效果像是没播。

**方法**:关掉过渡 → 设回起点 → **强制这一步立刻生效**(web 是读一次布局属性;引擎侧通常是先提交
一帧)→ 恢复过渡 → **再强制一次**(否则下一步又被合并)→ 设终点。

> 📌 **这是「可打断性」的代价,不是 bug。** 过渡之所以能被中途改道、从当前值接管(见拖拽),
> 正是因为它**永不瞬间跳变**。想要瞬间复位,就得暂时把它摘掉。
> 📌 **关键帧动画没有这个问题** —— 移除即回 0%。所以**一次性播完即弃**的效果(飘字)用关键帧,
> **可能被快速重复触发**的效果(页切 / 按压)用过渡。**两者不是风格之争,是能力之别。**

<details>
<summary>web 参考实现</summary>

```js
// ❌ 错的（看起来很对，但点了没反应）
el.classList.remove('in');
void el.offsetWidth;                 // 以为强制重排就能复位
requestAnimationFrame(()=> el.classList.add('in'));

// ✅ 对的
function resetTo(el, ...cls){
  el.style.transition = 'none';        // ① 关掉
  el.classList.remove(...cls);         // ② 复位
  void el.offsetWidth;                 // ③ 让复位【立刻】生效
  el.style.transition = '';            // ④ 还回去
  void el.offsetWidth;                 // ⑤ 让还回去也生效，否则下一步又被合并
}
```
</details>

---

## 缩放入场 Scale in ✅ figkit 已内置

**别名**:"淡淡地放大出来" / "弹窗正常弹出来那个" / "默认的出现方式" / scale-in / grow in
**类**:① 功能 UI

**默认入场。** 从略小 + 全透明,长到原大 + 不透明。**没有过冲** —— 它要的是「稳」,不是「俏」。

**用**:弹窗、卡片、气泡、下拉、绝大多数需要「出现」的东西。
**别用**:高频反复触发的东西;要「俏」的场合用**弹入**。

**方法**

```text
起:  scale = {motion.enter}, alpha = 0
终:  scale = 1,              alpha = 1
时长 {motion.dur-popup} · 曲线 {motion.ease-out}
出场同路反向,时长换 {motion.dur-exit}(**比入场快 · 非对称**)
```

**约束**

- ❌ **永不 `scale(0)`。** 现实里没有东西从虚无里长出来。起点 `.95`(`.9`–`.97` 都行)。
- ❌ **永不 `ease-in`。** 它延迟最初的位移,而那正是玩家盯得最紧的瞬间。
- 📌 **有入场必有出场。** 只写入场 = 消失时硬闪。
- 📌 **气泡 / 下拉从触发器长出**(见**原点感知**),别从自己中心长。**居中弹窗例外**。

**令牌**:`{motion.enter}` `{motion.dur-popup}` `{motion.dur-exit}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.scale-in{ opacity:0; transform:scale(.95);
  transition:opacity var(--dur-popup) var(--ease-out), transform var(--dur-popup) var(--ease-out) }
.scale-in.in{ opacity:1; transform:scale(1) }
.scale-in.out{ opacity:0; transform:scale(.95);
  transition-duration:var(--dur-exit) }        /* 出场更快 —— 非对称 */
```

不想写 JS 加 `.in` 的话用 `@starting-style`(纯 CSS 给「刚插入 DOM」的元素一个起始态):

```css
.popover{ opacity:1; transform:scale(1);
  transition:opacity var(--dur-popup) var(--ease-out), transform var(--dur-popup) var(--ease-out) }
@starting-style{ .popover{ opacity:0; transform:scale(.95) } }
```
</details>

---

## 弹入 Pop in

**别名**:"Q弹的" / "弹一下就位" / "有点回弹" / "像果冻" / bouncy / overshoot / easeOutBack
**类**:① 功能 UI

**缩放入场的「俏」版**:冲过终点一点点再落回来。多那一下回弹,读作「活的」。

**用**:罕见 / 首次 / 值得高兴的出现 —— 解锁、上榜、点赞、加入收藏。
**别用**:**高频 UI**(每天见几十次的东西弹来弹去 = 廉价且拖沓)。默认仍是**缩放入场**。

**方法**

```text
同缩放入场,但:
  起始 scale 换 {motion.pop-from}(比默认低得多 —— 见约束)
  scale 走 {motion.ease-pop}(y1 > 1 的过冲曲线)
  alpha 仍走 {motion.ease-out} —— **两条属性用不同曲线**
```

**约束**

- ⚠️ **别用默认的 `.95` 起步 —— 弹不出来。** 过冲是**行程的比例**,不是绝对值。
  实测 `{motion.ease-pop}` 进度峰值超出终点 **9.78%**:

  | 起步 scale | 行程 | scale 峰值 | 视觉过冲 | |
  |---|---|---|---|---|
  | `.95`(默认入场) | .05 | 1.0049 | **0.49%** | 看不见 |
  | `.90` | .10 | 1.0098 | 0.98% | 看不见 |
  | `.80` | .20 | 1.0196 | **1.96%** | 弹得出来 |
  | `.70` | .30 | 1.0293 | 2.93% | 明显 |

  **想弹就得给足行程。**
- ❌ **不透明度别跟着用过冲曲线** —— 冲过 1 没有意义(会被钳掉),白算一遍。
- 📌 过冲曲线的合法性:`y` 可以超出 `[0,1]`(**这就是过冲的来源**),但 **`x` 必须在 `[0,1]` 内**。

**令牌**:`{motion.ease-pop}` `{motion.pop-from}` `{motion.dur-popup}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.pop-in{ opacity:0; transform:scale(var(--pop-from));
  transition:opacity var(--dur-popup) var(--ease-out),
             transform var(--dur-popup) var(--ease-pop) }   /* ← 两条属性用不同曲线 */
.pop-in.in{ opacity:1; transform:scale(1) }
```
</details>

---

## 逐项入场 Stagger ✅ figkit 已内置

**别名**:"一个接一个出来" / "瀑布一样" / "错开一点点" / cascade / 列表动画
**类**:① 功能 UI

一组元素**依次**入场,每个之间差一个很小的延迟。它把「一堆东西唰地全出现」变成「有顺序地铺开」。

**用**:列表、网格、卡片组的**首次**出现。
**别用**:元素多到延迟累积超过 `{motion.dur-cap}` 的地方(最后一个还没出来,玩家已经在等了)。

**方法**

```text
第 k 项延迟 = k × {motion.stagger},其余同缩放入场(或淡入 + 小位移滑入)
```

**约束**

- 📌 **stagger 是装饰,永远不能挡交互。** 第 8 项还在飞,玩家点它必须立刻响应。
- 📌 **总时长设上限**:最后一项延迟 + 时长 ≤ 约 `{motion.dur-cap}` 的两三倍。超了就**砍延迟**或
  **分批**,别让玩家等一场瀑布。
- 📌 只在**首次**铺开时用。翻页 / 筛选后重排还 stagger = 每次操作都罚你看一遍。

**令牌**:`{motion.stagger}` `{motion.dur-tab}` `{motion.ease-out}` `{motion.dur-cap}`

<details>
<summary>web 参考实现</summary>

```js
// 令牌从 CSS 读 —— 别在 JS 抄一份数字
const CSSVAR = n => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(n));
const STAGGER = CSSVAR('--stagger');
items.forEach((el, k) => { el.style.transitionDelay = (k * STAGGER) + 'ms'; });
```
</details>

---

## 按压反馈 Press ✅ figkit 已内置

**别名**:"按下去有反应" / "点了会陷一下" / "按着有手感" / tap feedback / active state
**类**:① 功能 UI

按下时元素**微微缩一下**。**这是整个界面里最高频的动效**,所以必须最短、最轻。

**用**:**一切可点的东西**。没有例外。
**别用**:—— 没有「别用」。**缺按压反馈是缺陷,不是风格**。

**方法**

```text
按下 → scale 到目标,抬手 / 取消 → 回 1
时长 {motion.dur-press} · 曲线 {motion.ease-out}

两态:
  扁平元素(格子 / 页签 / 图标钮 / 列表行) → 只缩,{motion.press-flat}
  立体元素(厚下描边的主 CTA)            → 下沉 + 缩,投影同时收缩,{motion.press-3d}
```

**约束**

- ❌ **别只写按下态、不写过渡** —— 松手会硬跳回去。
- ❌ 幅度别过头。`.95`–`.98` 之间;再狠就滑稽。
- 📌 **缩放会把子元素一起缩** —— 文字、图标、内边距全按比例跟着走。**这是特性不是 bug**:
  整个按钮作为一个实体被按下去才是对的。(改宽高做不出这个效果 —— 也是按压必须用缩放的原因。)
- 📌 **按下的「终态长什么样」归界面规范**(下沉多少、投影收多少),**「怎么过去」归本档**。
- 📌 **缩放的枢轴要在中心。** 锚点在角上的引擎(如 Cocos 的左上锚)必须补位置偏移,
  否则按钮往一个角坍缩 —— figkit 的 cocos 后端在 `scaleAboutCenter()` 里踩过。

**令牌**:`{motion.press-flat}` `{motion.press-3d}` `{motion.dur-press}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.pressable{ transition:transform var(--dur-press) var(--ease-out) }
.pressable:active{ transform:scale(.96) }                       /* 扁平 */
.btn-3d:active{ transform:translateY(2px) scale(.98);
                box-shadow:0 2px 0 var(--edge) }                /* 立体：投影跟着收 */
```
</details>

---

## 抖动 Wiggle ✅ figkit 已内置

**别名**:"错了会抖" / "晃一下" / "拒绝的那个动画" / "密码错了那种" / jiggle
**类**:③ 反馈

快速左右**几个来回**,说「不行 / 错了 / 拒绝」。它是**否定**的通用身体语言 —— 不用读字就懂。

**用**:输入错误、条件不满足、资源不够、拒绝的操作。
**别用**:成功、警告、提示。抖动**只表示否定**;拿它做别的会教坏玩家。

> ⚠️ **别跟震屏共用令牌。** 抖动是**一个元素**说「错了」;震屏是**整个世界**说「这一下很重」。
> 抖动 = `{motion.wiggle}` / `{motion.wiggle-amp}`,震屏 = `{motion.shake}` / `{motion.shake-amp}`。
> **共用过一次,调一个必然坏另一个。**

**方法**

```text
x 偏移 = sin(2π·p) × {motion.wiggle-amp} × (1 − p)      p = 已播比例 0..1
总时长 {motion.wiggle};播完归零
```

**约束**

- 📌 **振幅要衰减**,别等幅来回。等幅读作「机器故障」,衰减才读作「人在摇头」。
- 📌 减弱动效下**必须有非动效替身**(红框 / 红字)。否定信息**不能只靠动效传达** ——
  关了动效就等于没告诉玩家。
- ⚠️ **两个令牌均未实测**(`calibration: untested`),接入时再定。

**令牌**:`{motion.wiggle}` `{motion.wiggle-amp}` `{motion.ease-out}`

<details>
<summary>web 参考实现(关键帧版,衰减写死在百分比里)</summary>

```css
@keyframes wiggle{
  0%,100%{ transform:translateX(0) }
  20%    { transform:translateX(calc(var(--wiggle-amp) * -1)) }
  40%    { transform:translateX(var(--wiggle-amp)) }
  60%    { transform:translateX(calc(var(--wiggle-amp) * -.6)) }  /* 衰减 —— 别等幅 */
  80%    { transform:translateX(calc(var(--wiggle-amp) * .3)) }
}
.wiggle{ animation:wiggle var(--wiggle) var(--ease-out) }
@media (prefers-reduced-motion:reduce){ .wiggle{ animation:none } }   /* 改红框/红字 */
```
</details>

---

## 呼吸 Breathe / Pulse

**别名**:"一闪一闪的" / "轻轻亮" / "喘气那个" / "红点在动" / pulse / glow
**类**:② 循环 · **常驻,不按频率表判**

一个**极轻的、无限往复的不透明度脉动**,说「这儿可以动手」。必须**弱到不抢注意力** ——
玩家该在需要时「发现」它,而不是被它戳。

**用**:空槽位提示可放置、可领取的红点、新解锁入口。
**别用**:已经很显眼的主 CTA(大金按钮本身就在喊了,再呼吸就是噪音)。

**方法**

```text
只动 alpha,在 {motion.breathe-low} 与 1(或 0 与 breathe-low)之间往复
周期 {motion.loop-breathe} · 曲线 {motion.loop-ease} · 无限循环
```

**约束**

- ❌ **别用阴影 / 辉光属性做呼吸** —— 每帧重算,掉帧。**叠一层只动不透明度**。
- 📌 **同屏循环 ≤ 3 处。** 第 4 个开始,整屏读作「到处在闪」,每一个都失去意义。
- 📌 减弱动效下**关掉**,改静态弱显示。

**令牌**:`{motion.breathe-low}` `{motion.loop-breathe}` `{motion.loop-ease}`

<details>
<summary>web 参考实现</summary>

```css
.breathe::before{
  content:""; position:absolute; inset:-6px; border-radius:50%;
  border:2px solid var(--accent);            /* 颜色引界面规范，不归本档 */
  opacity:0; pointer-events:none;
  animation:breathe var(--loop-breathe) var(--loop-ease) infinite;
}
@keyframes breathe{ 0%,100%{ opacity:0 } 50%{ opacity:var(--breathe-low) } }
@media (prefers-reduced-motion:reduce){ .breathe::before{ animation:none; opacity:.28 } }
```
</details>

---

## 漂浮 Float / Idle

**别名**:"上下飘" / "浮着的" / "待机小动作" / "活的感觉" / bob / idle
**类**:② 循环

极缓慢的上下漂移,让静止的东西**不像贴图**。跟呼吸的区别:**呼吸是提示(要你动手),
漂浮是氛围(不要求你做任何事)**。

**用**:立绘 / 萌宠 / 装饰物 / 空状态插图。
**别用**:**功能控件**。按钮在飘 = 你得瞄准一个移动靶。

**方法**

```text
y 偏移在 0 与 {motion.bob-rise} 之间往复
周期 {motion.loop-bob} · 曲线 {motion.loop-ease} · 无限循环
```

**约束**

- 📌 **同屏 ≤ 3 处**(与呼吸**共享**这个预算 —— 都是 ② 循环)。五个格子一起飘 = 整屏在晃。
- 📌 **错开相位**(各给不同起始延迟),否则一排东西**齐步走**,立刻露馅成「这是个动画」。
- 📌 别叠在可点区上:飘动 + 手指点击 = 打不中。

**令牌**:`{motion.bob-rise}` `{motion.loop-bob}` `{motion.loop-ease}`

<details>
<summary>web 参考实现</summary>

```css
@keyframes bob{ 0%,100%{ transform:translateY(0) } 50%{ transform:translateY(var(--bob-rise)) } }
.float{ animation:bob var(--loop-bob) var(--loop-ease) infinite }
```
</details>

---

## 飘字 Float-up text

**别名**:"跳伤害数字" / "飘上去那个 +1" / "冒出来的数字" / damage number / floating text
**类**:③ 反馈 · **游戏独有**

一个数字 / 短词从元素上**冒出来、往上飘、边飘边淡**。它是游戏里最高效的「发生了什么」——
**不占常驻 UI 一寸空间**,却把增减说清楚了。

**用**:伤害、治疗、获得(`+128`)、消耗(`-20`)、加成生效。
**别用**:需要玩家**读完**的信息。它一闪就没,**不是通知**。

**方法**

```text
y: 0 → {motion.fp-rise}   同时  alpha: 1 → 0
时长 {motion.fp-dur} · 曲线 {motion.ease-out} · **播完销毁节点**
```

**约束**

- 📌 **必须不吃点击**,否则飘字会挡住底下的按钮。
- 📌 **播完必须销毁。** 高频触发下不删 = 节点无限堆积,是内存泄漏。
- 📌 **多个同时冒要错开**(位置或延迟),否则叠在一起糊成一团、一个都读不出。
- 📌 用关键帧而非过渡 —— 这是**一次性、播完即弃**的元素,不存在被打断重定向的问题。

**令牌**:`{motion.fp-dur}` `{motion.fp-rise}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
@keyframes fp{
  0%  { transform:translateY(0);              opacity:1 }
  100%{ transform:translateY(var(--fp-rise)); opacity:0 }
}
.fp{ position:absolute; pointer-events:none;     /* ← 别挡住底下的点击 */
     animation:fp var(--fp-dur) var(--ease-out) forwards }
```
```js
function floatUp(host, text){
  const el = document.createElement('span');
  el.className = 'fp'; el.textContent = text;
  host.appendChild(el);
  el.addEventListener('animationend', () => el.remove());   // 必须 remove，否则堆积
}
```
</details>

---

## 数字滚动 Number ticker

**别名**:"数字自己涨上去" / "跳数" / "钱数会滚" / counter / count-up
**类**:③ 反馈 / tween

数值从旧值**滚**到新值,而不是瞬间跳变。它让「我赚到了」这件事**有过程** ——
瞬间跳变你根本不知道涨了还是跌了。

**用**:货币、战力、经验、任何玩家在意其**变化量**的数。
**别用**:不重要的数、或者一屏几十个数一起滚(那是灾难)。

> ❗ **依赖 [`algorithms.md §1`](algorithms.md) 贝塞尔求解器。直接用,别自己实现。**
> 自己编的后果有人付过账:用 `1-(1-t)³` 凑合,**与令牌曲线差 19.8 个百分点**。

**方法**

```text
显示值 = round(from + (to − from) · ease({motion.ease-out}, p))
p = 已播比例 · 时长 {motion.tween-num}
```

**约束**

- 📌 **必须用等宽数字。** 否则每帧字宽不同,数字**左右乱抖**,整行跟着跳。
- 📌 **时间戳别混轴。** 起点时刻必须取自和每帧回调**同一个时钟**,混用会让差值变负 →
  缓动出负值 → **数字朝反方向跑**(真踩过:一个递减的 tween 显示出了比起点更大的数)。
- 📌 **扣血要快、加血可缓**(非对称)。失去要干脆,获得可以享受。
- 📌 重复触发要能**接管**:新 tween 从**当前显示值**起步,别从旧值重来。

**令牌**:`{motion.tween-num}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
const CSSVAR = n => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(n));
const TWEEN_NUM = CSSVAR('--tween-num');
const _b = getComputedStyle(document.documentElement).getPropertyValue('--ease-out').match(/-?[\d.]+/g).map(Number);
const EASE_OUT = cubicBezier(_b[0], _b[1], _b[2], _b[3]);      // ← algorithms.md §1

function tweenNum(el, from, to){
  if (from === to){ el.textContent = fmt(to); return; }
  el.textContent = fmt(from);
  let t0 = null;
  // t0 必须取自 rAF 自己的时间戳：performance.now() 与 rAF 时间戳可能不同轴，
  // 混用会让 (now - t0) 变负 → 缓动出负值 → 数字朝反方向跑。
  requestAnimationFrame(function step(now){
    if (t0 === null) t0 = now;
    const p = Math.max(0, Math.min(1, (now - t0) / TWEEN_NUM));
    el.textContent = fmt(Math.round(from + (to - from) * EASE_OUT(p)));
    if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(to);
  });
}
```
</details>

---

## 编排 Orchestration

**别名**:"一整套动作" / "好几个一起来" / "弹出来那一下" / choreography
**类**:① 功能 UI · **它不是一个效果,是把若干效果对齐到同一拍**

玩家眼里的「一个动作」,实现上通常是**三四个效果同时跑**。编排就是**让它们读起来像一件事**。

**判据**:玩家能不能用**一句话**说出刚才发生了什么。能 = 编排成立;要是他说「遮罩暗了、然后
面板上来了、然后格子一个个亮了」—— 那就是散的。

**用**:玩家眼里是「一个动作」、实现上却是三四个效果同时跑的时刻。
**别用**:一个效果就说清楚的时刻。为了「有编排」硬凑成套 = 纯拖沓。

**例:底部列表弹出**(玩家感觉是「列表弹出来了」,实际是 4 个效果对齐)

| 部分 | 用什么 | 参数 |
|---|---|---|
| 抽屉本体 | **滑入**(抽屉形态) | 整块位移 + `{motion.ease-drawer}`;入场 `{motion.dur-popup}` / **出场 `{motion.dur-exit}`** |
| 背后遮罩 | **淡入** | alpha 0 → 1,**与抽屉同拍** |
| 列表里每一格 | **逐项入场** | 延迟 = k × `{motion.stagger}`,每格自身 = 淡入 + 小位移滑入 |
| 格子按下 | **按压反馈** | `{motion.press-flat}` |

**更多例子**(都是「玩家以为的一个动作」)

| 编排 | 拆开是什么 | 那一拍的要点 |
|---|---|---|
| **战斗命中** | **顿帧** + **震屏** + **飘字** + **血条填充** | **三件套必须错开触发**,同时上会糊成一坨。顺序:命中帧顿住 → 松开的同时震 → 飘字冒出 → 血条**滞后**扣 |
| **十连出货** | **淡入**(压暗) + **弹入**×10 + **逐项入场** + **高亮闪**(稀有那张) | 稀有那张要**单独给一拍**:前 9 张匀速逐张,到它**停半拍**再出。**节奏的重音就是卖点** |
| **升星仪式** | 六段(见**仪式**) | **别让铺垫比亮相长。** 玩家等的是主体亮相那一下 |
| **弹窗打开** | **淡入**(遮罩) + **缩放入场**(窗体) + **逐项入场**(内容) | 内容的 stagger **要等窗体到位**;窗还在缩、字就开始飞 = 两个位移叠一起,糊 |
| **场景切换** | **淡入**(遮罩) + 加载 + **淡出** | 加载必须**藏在遮罩后面并行**,不是「转场完了再加载」 |
| **下拉刷新** | **橡皮筋** + **慢旋** + 弹回 | 转圈要在**橡皮筋拉到阈值时**才出现 —— 它是「松手就会刷新」的预告,不是装饰 |

**约束**

- 📌 **一个主角,其余是伴奏。** 伴奏跑得比主角显眼 = 编排失败。
- 📌 **同拍 ≠ 同时长。** 遮罩和抽屉**同时开始**但可以不同时长;stagger 则**在抽屉到位后才有意义**。
- 📌 **出场要一起收,而且更快。** 常见错误是入场编排得很好,出场只写了抽屉滑下去、遮罩「啪」地消失。
- 📌 **总时长仍受 `{motion.dur-cap}` 管。** 编排不是加时长的借口 —— 它是把同样的时间**排得更好**。

**令牌**:`{motion.ease-drawer}` `{motion.dur-popup}` `{motion.dur-exit}` `{motion.stagger}` `{motion.press-flat}`

---

## 直接操纵拖拽 Drag

**别名**:"拖来拖去" / "抓着走" / "跟手" / "甩出去" / drag
**类**:① 功能 UI(手势)

> ❗ **依赖 [`algorithms.md`](algorithms.md) §2 弹簧 · §3 动量投射 · §4 橡皮筋 · §5 速度采样。
> 直接用,别自己实现。**(自己实现的后果有人付过账:弹簧写成半隐式欧拉,过冲被吃光、
> 还原度 0%,而且看不出来。)

**总纲**:界面有生命 = 动效从**当前屏幕值**开始、继承玩家的速度、向前投射动量、
**任何瞬间可抓可反转**。

**用**:格子互换、卡片排序、抽屉、可滑动列表。
**别用**:点一下就够的地方。拖拽是**成本最高**的交互,得有「直接操纵」的收益才值。

**方法(八步)**

| 步 | 做法 | 令牌 |
|---|---|---|
| 抓取 | 独占指针 + 记**抓取偏移**(别让元素跳到指尖)+ 开始记位置 / 时间历史 | — |
| 判向 | 位移超过阈值才认定拖拽(滞后),否则仍算点击 | `{motion.drag-threshold}` |
| 反悔 | 没过阈值就拖开再拖回来 = 仍算点击;拖开后松手 = **取消** | `{motion.drag-threshold}` |
| 跟随 | **1:1 跟手**。源位变暗占位 | — |
| 越界 | 橡皮筋阻力(§4),**永远拉得动一点** | `{motion.rubberband-k}` |
| 松手 | **速度交接** → 动量投射(§3)定落点;**甩出看速度不看距离** | `{motion.flick-velocity}` `{motion.decel-rate}` |
| 归位 | 弹簧(§2)。带动量 → `{motion.spring-momentum}`(允许过冲);否则 `{motion.spring-ui}` | 两条 |
| 打断 | 飞行途中**可再抓起**,从**当前位置 + 当前速度**接管 | — |

**约束**

- ❌ **别把元素跳到指尖。** 记抓取偏移,玩家抓哪就从哪拿。
- ❌ **甩出别看距离。** 快速短促的一甩位移可能只有几十 px,但**意图很明确** —— 看速度。
- ❌ **归位途中别锁死。** 锁了就不是「活的」;可打断是这类交互最重要的单一原则。
- ❌ **2D 别用一条弹簧。** 一条弹簧管「到目标的直线距离」,X/Y 速度不同时两轴会失同步,
  轨迹拧着走。**X 一条、Y 一条,各自独立。**
- ❌ **多指没保护 = 元素跳变。** 拖到一半另一根手指按下去,新触点会重算抓取偏移,元素**瞬移**。
  「已在拖就无视新触点」一行就挡住了 —— **手游必踩,桌面测不出来**。
- 📌 **拖动中的样子要「指向结局」。** 目标格该**提前亮**、缝隙该**提前让开**,别等松手才揭晓。
  玩家是靠**中间帧**预测结果的;中间帧只做盲插值 = 全程不知道松手会发生什么。
- 📌 **按下就给反馈,别等松手。** 高亮 / 缩放在按下那一刻就要出现 —— 等点击事件才有反应,
  直接感会「掉下悬崖」。

**令牌**:`{motion.drag-threshold}` `{motion.flick-velocity}` `{motion.decel-rate}` `{motion.rubberband-k}` `{motion.spring-ui}` `{motion.spring-momentum}`

<details>
<summary>web 参考实现</summary>

```js
const CSSVAR = n => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(n));
const DRAG_THRESHOLD = CSSVAR('--drag-threshold');
const FLICK_V        = CSSVAR('--flick-velocity');
const DECEL          = CSSVAR('--decel-rate');

let hist = [], grab = null, sx = null, sy = null;   // ← X / Y 各一条弹簧，别合成一条

el.addEventListener('pointerdown', e => {
  if (grab) return;                         // ← 多指保护：已在拖了就无视新触点
  e.preventDefault();                       // 不 preventDefault → 浏览器把拖动当框选文字，
  el.setPointerCapture(e.pointerId);        // 划词工具栏弹出会直接打断手势（真踩过）
  const r = el.getBoundingClientRect();
  grab = { dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false };
  hist = [{ x: e.clientX, y: e.clientY, t: e.timeStamp }];
  sx = sy = null;                           // 飞行中被抓回 —— 从当前值接管，不重置
});

el.addEventListener('pointermove', e => {
  if (!grab) return;
  hist.push({ x: e.clientX, y: e.clientY, t: e.timeStamp });
  if (hist.length > 5) hist.shift();        // 只留最近几帧算速度，否则速度被历史稀释
  if (!grab.moved && Math.hypot(e.clientX - hist[0].x, e.clientY - hist[0].y) < DRAG_THRESHOLD) return;
  grab.moved = true;
  el.style.transform = `translate(${e.clientX - grab.dx}px, ${e.clientY - grab.dy}px)`;
});

el.addEventListener('pointerup', e => {
  if (!grab) return;
  if (!grab.moved) { onTap(); grab = null; return; }   // 没过阈值 = 点击，不是拖拽
  const a = hist[0], b = hist[hist.length - 1];
  const dt = Math.max(1, b.t - a.t);
  const v  = { x: (b.x - a.x) / dt, y: (b.y - a.y) / dt };   // px/ms —— 交接给弹簧的初速
  const curX = b.x - grab.dx, curY = b.y - grab.dy;          // 元素【此刻】的位置 = 弹簧起点
  const flicked = Math.hypot(v.x, v.y) > FLICK_V;            // 甩出看速度，不看距离
  const land = flicked
    ? nearestSlot(b.x + projectPx(v.x, DECEL), b.y + projectPx(v.y, DECEL))
    : nearestSlot(b.x, b.y);
  const cfg = flicked ? SPRING_MOMENTUM : SPRING_UI;
  sx = makeSpring(curX, v.x, land.x, cfg);                   // ← 速度交接：X 轴
  sy = makeSpring(curY, v.y, land.y, cfg);                   //   Y 轴独立一条
  raf();
  grab = null;
});

function raf(){
  let last = performance.now();
  (function tick(now){
    const dt = (now - last) / 1000; last = now;
    el.style.transform = `translate(${sx.step(dt)}px, ${sy.step(dt)}px)`;
    if (!(sx.settled && sy.settled)) requestAnimationFrame(tick);   // 两轴都停了才算停
  })(last);
}
```

web 侧另需:`touch-action:none`(否则移动端跟浏览器滚动抢手势)、按下时 `preventDefault()`、
以及整页禁选中(见 `routing.md §6`)。
</details>

---

## 飞向目标 Fly to target

**别名**:"金币飞进钱包" / "东西飞到背包里" / "领奖那个" / "吸过去" / collect animation
**类**:③ 反馈 · **游戏独有**

奖励从它**出现的地方**飞进**它要去的地方**。它回答了玩家心里唯一的问题:**「这东西进我兜里了吗?」**
—— 一个 Toast 说「获得 128 金币」永远比不上**看见金币真的飞进去、货币数字跟着跳**。

**用**:领奖、开箱出货、任务完成、扫荡结算 —— **任何「资源从 A 到 B」的时刻。开箱like / 放置
品类的核心循环全靠它。**
**别用**:资源**没有明确去处**时(飞到哪?);一次几十个(会糊,见约束)。

**方法(三段)**

| 段 | 做什么 | 曲线 |
|---|---|---|
| **① 爆开** | 从源点向四周散开一点(带随机抖动),给「一堆东西」的量感 | `{motion.ease-out}` |
| **② 停顿** | `{motion.fly-hold}`,**让玩家看清有几个** | — |
| **③ 吸入** | 沿**抛物线**加速冲向目标,弧高 = 起终距离 × `{motion.fly-arc}` | ⚠️ **ease-in**,见下 |

```text
第 i 个飞行体延迟 i × {motion.fly-stagger} 出发
③ 段位置 = lerp(散开点, 目标, p²)  −  弧高 · sin(π·p²)      p = ③ 段进度
到达瞬间:目标弹一下 + 数字滚动;飞行体销毁
```

> ⚠️ **这里是 `ease-in` 的合法场合 —— 唯一的。**
> 「UI 永不用 ease-in」针对的是 **① 功能 UI 的状态变化**(它延迟玩家盯得最紧的最初位移)。
> **飞行体不是状态变化,是一个被吸走的物体** —— 物理上就该**越飞越快**,而且「啪」地砸进钱包
> 那一下正是全部的爽点。**照铁律改成 ease-out,金币会飞得软绵绵、像飘走而不是被吸走。**
> 这条必须写明,否则下一个人一定会「顺手修正」它。

**约束**

- 📌 **飞行体是克隆件,不是原件。** 原件该留在原地(或按自己的节奏消失),别让它「离家出走」。
- 📌 **必须走抛物线,别走直线。** 直线读作「传送」,弧线才读作「被抛过去」。
  弧高**随距离缩放**,定值在近距离时会拱得很怪。
- 📌 **数量要压缩**:玩家给多少都行,飞的**最多 8–12 个**。100 金币不是飞 100 个,
  是飞 10 个然后数字跳 100。
- 📌 **`{motion.fly-stagger}` 别为 0。** 全部同时飞 = 一坨东西移动,量感反而没了。
- 📌 **到达要和数字滚动对齐**:第一个到 → 数字开始滚;最后一个到 → 数字刚好滚完。
  **对不齐的话,「飞进去」和「变多了」会读成两件事。**
- 📌 播完必删(同**飘字**)。
- ⚠️ **绝对定位的坐标系要先钉死。** web 上 `position:fixed` 必须配 `left:0; top:0`,
  否则元素停在**静态位置**、`transform` 是从那里再偏移 —— **金币会全飞到页面外,
  而且你完全看不出哪错了**。引擎侧同理:先确认飞行体挂在哪个坐标系下。

**令牌**:`{motion.fly-dur}` `{motion.fly-arc}` `{motion.fly-hold}` `{motion.fly-stagger}` `{motion.tween-num}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
function flyTo(fromEl, toEl, count){
  const a = fromEl.getBoundingClientRect(), b = toEl.getBoundingClientRect();
  const x0 = a.left + a.width/2,  y0 = a.top + a.height/2;
  const x1 = b.left + b.width/2,  y1 = b.top + b.height/2;
  const arc = Math.hypot(x1-x0, y1-y0) * CSSVAR('--fly-arc');   // 弧高随距离走，不是定值
  const DUR = CSSVAR('--fly-dur'), HOLD = CSSVAR('--fly-hold');
  for (let i = 0; i < count; i++){
    const el = mkFlyer();
    document.body.appendChild(el);
    const jx = (Math.random()*2-1) * 22, jy = (Math.random()*2-1) * 22;   // ①爆开的随机散布
    const start = performance.now() + i * CSSVAR('--fly-stagger');
    requestAnimationFrame(function step(now){
      const t = now - start;
      if (t < 0){ requestAnimationFrame(step); return; }
      if (t < HOLD){                                       // ①②：散开后停住，让玩家看清
        const q = Math.min(1, t / HOLD);
        put(el, x0 + jx*q, y0 + jy*q, 1);
        requestAnimationFrame(step); return;
      }
      const p = Math.min(1, (t - HOLD) / DUR);
      const e = p * p;                                     // ③ ease-in：越飞越快（被吸走）
      const x = (x0+jx) + (x1 - (x0+jx)) * e;
      const y = (y0+jy) + (y1 - (y0+jy)) * e - arc * Math.sin(Math.PI * e);  // 抛物线
      put(el, x, y, 1 - p*p*0.4);                          // 快到时略缩，像"被吞进去"
      if (p < 1) requestAnimationFrame(step);
      else { el.remove(); onArrive(); }                    // 播完即删 + 目标弹一下 + 数字滚动
    });
  }
}
```
</details>

---

## 吸附 Snap

**别名**:"自动停到整页" / "不会停在中间" / "自己对齐" / snap / paging
**类**:① 功能 UI(手势)

> ❗ **依赖 [`algorithms.md`](algorithms.md) §3 动量投射(算落点)+ §2 弹簧(落过去)。别自己实现。**

松手后**落到最近的整数位**,而不是停在哪算哪。**有惯性就必须有吸附** ——
否则轮播永远停在两页之间,玩家得手动微调。

**用**:轮播、分页、滚轮选择器、时间选择、卡片列表。
**别用**:自由滚动的长列表(强行吸附会让人觉得「被拽着走」)。

**⚠️ 先分清两种吸附,判法完全不同**

| | 判落点的方式 | 例子 |
|---|---|---|
| **分页吸附** | **甩一下 = 恰好翻一页**(方向由速度定);慢拖 = **看位移过没过半**。**不看投射距离** | 轮播、分页、Tab 滑动 |
| **自由滚动 + 吸附** | 用 §3 **投射**出自由落点 → 吸到最近的点 | 滚轮选择器、时间选择、长列表吸行 |

> **拿「自由滚动」的做法去做「分页」是真犯过的错**:`{motion.decel-rate}` = 0.998 → 投射系数
> **499**。实测一次正常的甩 v = 1.59px/ms → 投射 **793px ≈ 3 页多** → **任何一次甩都冲到边界钳死**,
> 于是「一甩就跳到最后一页,调参数还没反应」。**投射系数对「滚多远」是对的,对「翻几页」是荒谬的。**

**方法(分页)**

```text
松手 → 速度 > {motion.flick-velocity} ?
        是 → 目标页 = 当前页 ± 1(方向由速度符号定)
        否 → 目标页 = round(当前位移 / 页宽)
     → 夹到 [0, 页数−1] → 用弹簧 {motion.spring-ui} 落过去(速度要交接)
```

**约束**

- 📌 **分页:甩一下就是一页,别多别少。** 甩两页远的距离也只翻一页 —— 这是**分页器的共识**。
- 📌 **「甩」的判定只看速度,不看距离。**
- 📌 **无论哪种,选完落点还是弹簧落过去** —— 别直接跳,也别让投射决定最终位置(会先冲过头再拉回来)。
- 📌 弹簧用 `{motion.spring-ui}`(**不过冲**)。翻页过冲 = 露出下一页的边,穿帮。
- 📌 **纯滚动场景优先用平台原生的吸附**(免费、自带惯性与上面这套判法);只有需要自定义手势时才手写。

**令牌**:`{motion.flick-velocity}` `{motion.spring-ui}` · 自由滚动式还要 `{motion.decel-rate}`

<details>
<summary>web 参考实现</summary>

```js
el.addEventListener('pointerup', e => {
  const v = tracker.velocity();                               // px/ms —— 见 algorithms §5
  const flicked = Math.abs(v) > CSSVAR('--flick-velocity');
  let idx;
  if (flicked) idx = curIdx + (v < 0 ? 1 : -1);               // 甩 = 翻【一】页，不看距离
  else         idx = Math.round(-pos / pageW);                // 慢拖 = 位移过没过半
  idx = Math.max(0, Math.min(pages-1, idx));
  spring = makeSpring(pos, v*1000, -idx*pageW,                // 速度仍要交接给弹簧
    {damping: CSSVAR('--spring-ui-damping'), response: CSSVAR('--spring-ui-response')});
});
```

纯滚动场景直接用 CSS `scroll-snap`。
</details>

---

## 堆叠 Toast Stacked toasts

**别名**:"通知叠起来" / "消息堆一摞" / "悬停展开那个" / stacked notifications
**类**:① 功能 UI

多条通知**叠成一摞**(只露出边),展开时铺开。它解决的是:**通知来得比读得快**时,
不能一条条排下去占满半屏。

**用**:可能连续来多条的通知(战报、获得、系统消息)。
**别用**:一次最多一条的场合(直接**滑入**就够)。

**方法**

```text
最新那条在最前;第 k 条:
    位移  = k × {motion.toast-stack-offset}(往后叠的方向)
    缩放  = {motion.toast-stack-scale} ^ k
    层级  = 越新越前;非最新的略暗
只保留 {motion.toast-max} 条可见,更旧的淡出移除(**计数要留**)
进出用滑入 · 重排用布局动画
```

**约束**

- 📌 **缩放要小**(`.94` 一档)。缩太多,第三条会像「远处的另一个东西」。
- 📌 **越旧越靠后、越小、越暗** —— 三个信号一起给,才读得出「这是一摞」而不是「三个错位的框」。
- 📌 **展开时别 stagger。** 它们**已经存在**,不是入场;逐个铺开会像在放动画。
- 📌 上限之外的**直接移除**,别留着占内存;但**计数要留**(「还有 5 条」)。

**令牌**:`{motion.toast-stack-offset}` `{motion.toast-stack-scale}` `{motion.toast-max}` `{motion.dur-tab}` `{motion.dur-exit}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
function relayout(){
  const OFF = CSSVAR('--toast-stack-offset'), SC = CSSVAR('--toast-stack-scale'), MAX = CSSVAR('--toast-max');
  [...list].reverse().forEach((el, k) => {                  // k=0 是最新的
    if (k >= MAX){ el.classList.add('out'); setTimeout(()=>el.remove(), CSSVAR('--dur-exit')); return; }
    el.style.transform = `translateY(${-k*OFF}px) scale(${Math.pow(SC, k)})`;
    el.style.zIndex = 100 - k;
    el.style.opacity = expanded ? 1 : (k === 0 ? 1 : 0.9);
  });
}
```
</details>

---

## 冷却扫描 Cooldown sweep

**别名**:"技能转圈" / "CD 那个扇形" / "灰掉转一圈" / cooldown / radial timer
**类**:① 功能 UI

技能图标上**扇形**扫过,表示还有多久能用。跟**揭示**的区别:揭示是**直线裁切**,
这是**角度裁切** —— 两回事。

**用**:技能 CD、buff 剩余、限时道具。
**别用**:非圆形的进度(那用**揭示**或**血条填充**)。

**方法**

```text
扇形角度 360° → 0°,**线性**
时长 = 技能配置的 CD,**不是动效令牌**
转完给一次 {motion.flash} = 「可以按了」
```

**约束**

- ⚠️ **`{motion.dur-cap}` 管不着它,频率表也管不着它** —— 它的时长**是玩法数据**
  (技能 CD 3 秒就是 3 秒)。**动效档只规定「怎么画」,不规定「多久」。**
  这是本档里少数几个「时长不归我们」的效果。
- 📌 **必须线性。** 这是**进度**不是动效,加缓动 = 骗人(看着快好了其实没有)。同**长按确认**。
- 📌 **转完要有「可以按了」的信号**,否则玩家得盯着看。
- 📌 别大量同屏 —— 角度裁切通常要每帧重画。

**令牌**:`{motion.flash}`(转完那一下)· **时长不吃令牌,来自技能配置**

<details>
<summary>web 参考实现</summary>

```css
.cd{ position:absolute; inset:0; border-radius:inherit; pointer-events:none;
  background:conic-gradient(rgba(0,0,0,.62) var(--cd-angle), transparent 0) }
```
```js
// ⚠️ 时长来自 skill.cdTime，【不是】动效令牌 —— 它是玩法数据，动效不能改它
function sweep(el, cdMs){
  const t0 = performance.now();
  (function f(now){
    const p = Math.min(1, (now - t0) / cdMs);
    el.style.setProperty('--cd-angle', (360 * (1 - p)) + 'deg');   // linear：进度必须诚实
    if (p < 1) requestAnimationFrame(f);
    else { el.style.setProperty('--cd-angle', '0deg'); flash(el); }
  })(t0);
}
```

角度要被 GPU 平滑插值得用 `@property` 注册;不注册就只能每帧写(如上)。
</details>

---

## 出货演出 Gacha reveal

**别名**:"抽卡那个" / "开箱" / "出金" / "开奖动画" / reveal / celebration
**类**:④ 演出 · **游戏独有**

罕见、高价值时刻的**兑现**。它跟前面所有效果**遵守完全不同的规则**。

> ⚠️ **④ 演出不受 `{motion.dur-cap}` 约束,也不受频率表约束。**
> 功能 UI 的动效是**成本** —— 越常见越该压缩;演出的动效是**商品** —— 玩家就是为这一下来的,
> 看一百遍也要爽。**拿频率表去砍出货演出,是把商品当成本砍。**

**用**:抽卡出货、升星 / 突破 / 进化成功、首次解锁、赛季结算。
**别用**:任何**日常**操作。演出用滥了就不是演出了,只是慢。

**方法**

```text
单张:  起 scale = {motion.pop-from} + alpha 0 → 终 scale 1 + alpha 1
        时长 {motion.reveal-pop} · 曲线 {motion.ease-pop}(这里"俏"是对的)
多张:  第 k 张延迟 k × {motion.reveal-stagger}
        **稀有那张单独给一拍** —— 前面匀速,到它停半拍再出
分段编排见**仪式**:主段 {motion.ceremony-beat} / 子段 {motion.ceremony-sub}
```

**约束**

- 📌 **必须能跳过。** 第 1 次是演出,第 200 次是收费站。**跳过要立刻到终态**,别「快进播放」。
- 📌 **跳过不能跳过结果。** 玩家跳的是过程,不是信息 —— 终态必须完整呈现拿到了什么。
- 📌 **别在演出里塞不可跳的等待。** 演出的爽 ≠ 让玩家等。
- 📌 减弱动效下**大幅简化**(直接给终态 + 一次淡入),但**别取消** —— 它承载的是信息。

**令牌**:`{motion.ceremony-beat}` `{motion.ceremony-sub}` `{motion.reveal-pop}` `{motion.reveal-stagger}` `{motion.ease-pop}` `{motion.pop-from}`

<details>
<summary>web 参考实现</summary>

```css
/* 单张出货：允许过冲（这里"俏"是对的——正是玩家要的那一下） */
.gacha-card{ opacity:0; transform:scale(var(--pop-from));
  animation:pop var(--reveal-pop) var(--ease-pop) forwards }
@keyframes pop{ to{ opacity:1; transform:scale(1) } }
```
```js
cards.forEach((el, k) => el.style.animationDelay = (k * CSSVAR('--reveal-stagger')) + 'ms');
```
</details>

---

## 淡入 / 淡出 Fade ✅ figkit 已内置

**别名**:"慢慢出来" / "淡进淡出" / "透明度变化" / fade in / fade out
**类**:① 功能 UI

只动不透明度。**最便宜、最不会出错的效果** —— 没有方向、没有位移,因此也没有「从哪来」的含义。

**用**:遮罩、背景、tooltip、没有空间关系的东西。
**别用**:需要说清「从哪来 / 到哪去」的场合(那要**滑入**或**原点感知**)。单纯淡入淡出会让玩家丢失方位。

**方法**

```text
alpha 0 ↔ 1 · 时长 {motion.dur-tab} · 曲线 {motion.ease-out};淡出可换 {motion.dur-exit}
```

**约束**

- 📌 **起点必须是 0**,不是 `.4`。从 `.4` 起淡,元素会「突然出现一个半透明的鬼影」再变实。
- 📌 淡出可比淡入快。

**令牌**:`{motion.dur-tab}` `{motion.dur-exit}` `{motion.ease-out}`

---

## 滑入 Slide in ✅ figkit 已内置

**别名**:"从边上推进来" / "滑出来的" / "抽屉那种" / slide / drawer
**类**:① 功能 UI

从某个方向位移进场。**它带方向信息**:从下来的东西,关掉时也该往下走。

**用**:抽屉、底部弹层、侧边栏、Toast、任何**有明确来处**的浮层。
**别用**:居中弹窗(它没有「来处」,用**缩放入场**)。

**方法**

```text
整块滑入(抽屉):  位移 = 元素自身尺寸的 100%(**比例,不是绝对像素**)· 曲线 {motion.ease-drawer}
小位移(Toast):   位移 = {motion.slide-from} + alpha 0 → 1 · 曲线 {motion.ease-out}
时长 {motion.dur-popup}(小位移用 {motion.dur-tab})
```

**约束**

- 📌 **整块滑入用比例不用绝对像素** —— 自适应元素尺寸,换了内容不用改数值。
- 📌 **进出方向必须一致。** 从下来 → 往下走。反向 = 玩家丢失空间感。
- 📌 **曲线也要镜像,不只是方向。** 可逆的转场,回路要用来路曲线的**反控制点**:
  `cubic-bezier(x1,y1,x2,y2)` 的镜像是 `cubic-bezier(1−x2, 1−y2, 1−x1, 1−y1)`。
  只镜像方向、两头都用 `ease-out`,回去那一下和来时**不是同一条路**。
- 📌 抽屉配 `{motion.ease-drawer}`,别用默认 `{motion.ease-out}` —— 前者减速尾巴更长,
  才有「贴着轨道停住」的手感。

**令牌**:`{motion.slide-from}` `{motion.dur-popup}` `{motion.dur-tab}` `{motion.ease-drawer}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.sheet{ transform:translateY(100%);            /* 底部抽屉用 % 不用 px */
  transition:transform var(--dur-popup) var(--ease-drawer) }
.sheet.in{ transform:translateY(0) }

.toast{ transform:translateY(var(--slide-from)); opacity:0;
  transition:transform var(--dur-tab) var(--ease-out), opacity var(--dur-tab) var(--ease-out) }
.toast.in{ transform:translateY(0); opacity:1 }
```
</details>

---

## 揭示 Reveal

**别名**:"擦出来的" / "拉开幕布" / "一点点露出来" / wipe / clip reveal
**类**:① 功能 UI

用**裁切**逐渐露出内容。跟淡入的区别:**内容本身不动、不透明度不变,只是「被挡住的部分变少了」**。

**用**:长按进度、技能冷却、图表生长、进度条、「擦除」式的强调。
**别用**:普通元素出现(那是**缩放入场**的活,裁切更贵)。

**方法**

```text
裁切矩形从「遮住」插到「全开」· 时长视场景 · 曲线 {motion.ease-out}
```

**约束**

- 📌 裁切**能上 GPU**,但比位移 / 不透明度贵。**别拿它做高频 UI**。
- 📌 裁切参数是**往里缩多少**,不是坐标 —— 写错方向是最常见的错。
- 📌 起止两端的裁切**形状必须同型**(都是矩形或都是圆),否则不插值、直接跳变。

**令牌**:`{motion.dur-popup}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.reveal{ clip-path:inset(0 100% 0 0);          /* 右边遮掉 100% */
  transition:clip-path var(--dur-popup) var(--ease-out) }
.reveal.in{ clip-path:inset(0 0 0 0) }         /* 全开 */
```
</details>

---

## 分步动画 Stepped

**别名**:"一格一格跳" / "秒表那种" / "不连续的动" / steps() / 帧动画
**类**:① 功能 UI / ② 循环

**故意不平滑。** 让动画在离散的格子间跳,而不是连续插值。

**用**:倒计时秒表、精灵图帧动画、打字机光标、刻意的「机械感」。
**别用**:任何该顺滑的东西。这是**特意要的粗糙**,不是省事。

**方法**

```text
进度 = floor(p × N) / N        N = 格数
```

**约束**

- 📌 注意「跳完最后一格才到终点」和「首帧立刻跳」是两种取整,选错会差一格。
- 📌 精灵图帧动画要关掉纹理插值(像素素材),否则缩放糊。

**令牌**:—(步数是每次用法的参数,不是全局令牌)

<details>
<summary>web 参考实现</summary>

```css
@keyframes tick{ to{ transform:translateY(-100%) } }
.counter{ animation:tick 10s steps(10) infinite }     /* 10 秒跳 10 格 */

@keyframes blink{ 50%{ opacity:0 } }
.caret{ animation:blink 1s steps(1) infinite }        /* 光标：硬闪，不许渐变 */
```

`steps(N)` 默认 `end`;要首帧立刻跳用 `steps(N, jump-start)`。
</details>

---

## 3D 翻转 Flip

**别名**:"翻牌" / "转过来" / "背面朝上" / card flip / 3D tilt
**类**:① 功能 UI / ④ 演出

绕轴旋转,露出背面。**给平面界面加进深**,是「卡牌」这个隐喻最直接的兑现。

**用**:翻卡(抽卡揭晓)、正反面切换、图鉴翻页。
**别用**:高频操作。3D 翻转**贵且晕**,一天翻几十次会难受。

**方法**

```text
父节点给透视距离 {motion.perspective}(⚠️ 在**父**上,不是被转的元素上)
子节点绕 Y 轴 0° → 180°,正反两面各自背面剔除
时长 {motion.dur-popup} · 曲线 {motion.ease-in-out}(屏内 A→B 的形变,两头都该缓)
```

**约束**

- 📌 **透视写在父节点上。** 写自己身上 → 每个元素各有各的灭点 → 一排卡片转起来各转各的。
- 📌 **子节点必须保留 3D 空间**,否则被拍扁回 2D、背面永远不出现。
- 📌 用 `{motion.ease-in-out}` 而非 `ease-out`。

**令牌**:`{motion.perspective}` `{motion.dur-popup}` `{motion.ease-in-out}`

<details>
<summary>web 参考实现</summary>

```css
.flip-scene{ perspective:var(--perspective) }        /* 透视在【父】上 —— 常见错误是写在自己身上 */
.flip{ position:relative; transform-style:preserve-3d;
  transition:transform var(--dur-popup) var(--ease-in-out) }
.flip.on{ transform:rotateY(180deg) }
.flip .face{ position:absolute; inset:0; backface-visibility:hidden }
.flip .back{ transform:rotateY(180deg) }
```
</details>

---

## 原点感知 Origin-aware

**别名**:"从按钮里长出来" / "从点的地方冒出来" / transform-origin / 气泡定位
**类**:① 功能 UI

弹层**从触发它的那个东西长出来**,而不是从自己中心。它把「这个面板属于那个按钮」这件事
**用动作说清楚**,不用连线、不用箭头。

**用**:气泡、下拉、右键菜单、tooltip —— **一切由某个具体控件唤起的浮层**。
**别用**:**居中弹窗**。它本来就在屏幕中央,没有「来处」,从中心长是对的。

**方法**

```text
同缩放入场,但缩放枢轴 = 触发器中心相对弹层自身的比例:
    枢轴X = (触发器中心X − 弹层左) / 弹层宽
    枢轴Y = (触发器中心Y − 弹层上) / 弹层高
**必须在弹层已有尺寸之后再算**,否则量到全 0
```

**约束**

- 📌 触发器在屏幕边缘时弹层会翻转方向,**枢轴要跟着翻**,否则会从错误的角长出来。
- 📌 组件库通常已经算好了,直接用它给的值,别自己重算。
- 📌 **提示气泡要延迟 `{motion.tip-delay}` 再出现**(防划过就弹),**但已经有一个气泡开着时,
  相邻气泡必须零延迟、零动效直接出**。
  > **这是「感知性能」的典型**:延迟一个都没少(第一个照样等),但**整条工具栏会显得快得多**。
  > 玩家的心理模型是「提示系统已经醒了」,这时候还让他等,读作卡顿。

**令牌**:`{motion.enter}` `{motion.dur-tab}` `{motion.tip-delay}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
function openPopover(pop, trigger){
  const t = trigger.getBoundingClientRect();
  const p = pop.getBoundingClientRect();
  // 触发器中心相对弹层自身的百分比 —— 弹层就从这个点长出来
  pop.style.setProperty('--origin',
    ((t.left + t.width/2  - p.left) / p.width  * 100) + '% ' +
    ((t.top  + t.height/2 - p.top ) / p.height * 100) + '%');
  pop.classList.add('in');
}
```
```css
.popover{ transform-origin:var(--origin, center) }
.tip{ transition:transform var(--dur-tip) var(--ease-out), opacity var(--dur-tip) var(--ease-out) }
.tip[data-instant]{ transition-duration:0ms }   /* 已有气泡开着 → 后续的直接出 */
```
</details>

---

## 交叉淡化 Crossfade

**别名**:"一个变另一个" / "叠着换" / "溶解" / dissolve
**类**:① 功能 UI

旧的淡出、新的淡入,**在同一位置重叠**。

**用**:同位置换图、换状态、加载完成替换占位。
**别用**:两个东西有空间关系时(该用**共享元素转场**)。

**方法**

```text
两层重叠,alpha 反向插值 · 时长 {motion.dur-tab} · 曲线 {motion.ease-out}
中途双曝光用 {motion.blur-mask} 糊一下
```

**约束**

- 📌 **交叉淡化天生会双曝光**(中间时刻两层都是半透明,能同时看见)。差异大的两张图会很脏 ——
  **用 `{motion.blur-mask}` 糊一下**,这是最便宜的遮丑。
- ⚠️ 模糊很贵,别大面积用、别超过硬上限。

**令牌**:`{motion.dur-tab}` `{motion.ease-out}` `{motion.blur-mask}`

<details>
<summary>web 参考实现</summary>

```css
.xfade{ position:relative }
.xfade > *{ position:absolute; inset:0; opacity:0;
  transition:opacity var(--dur-tab) var(--ease-out), filter var(--dur-tab) var(--ease-out) }
.xfade > .on{ opacity:1 }
.xfade.busy > *{ filter:blur(var(--blur-mask)) }   /* 换的过程里糊一下，盖住双曝光 */
```
</details>

---

## 连续性转场 Continuity

**别名**:"接得上" / "不跳" / "跟得住" / continuity
**类**:① 功能 UI · **这更像原则,但它有具体做法**

变化时**保持玩家的方位感** —— 让前后两个状态在视觉上连得起来,而不是「啪」地换了一屏。
最简单的形态:**同一个矩形变大变小**,而不是消失再出现一个新的。

**用**:列表 → 详情、小卡 → 大卡、折叠 → 展开。
**别用**:前后确实无关的两个界面(硬连反而更怪)。

**方法**

```text
**别把 A 删掉再建 B。** 让同一个节点改尺寸 / 位置,或用共享元素转场(FLIP)
时长 {motion.dur-popup} · 曲线 {motion.ease-in-out}
```

**约束**

- ⚠️ **直接动尺寸会触发布局重算**,只在**低频、小范围**用。高频 / 大面积必须换成缩放或 FLIP。
- 📌 判据:**玩家能不能一眼说出「刚才那个东西现在在哪」**。能 = 连续性成立。

**令牌**:`{motion.dur-popup}` `{motion.ease-in-out}`

---

## 形变 Morph

**别名**:"变形" / "长成另一个" / "灵动岛那个" / morph
**类**:① 功能 UI / ④ 演出

一个形状**平滑变成**另一个形状 —— 不是换掉,是**同一个东西改变了自己**。

**用**:按钮 → 加载圈 → 对勾、胶囊展开成面板、图标间的状态切换。
**别用**:两个形状差太远时。变形的说服力来自「看得出是同一个东西」。

**方法**

```text
插值圆角 / 尺寸 / 裁切形状 · 时长 {motion.dur-popup} · 曲线 {motion.ease-in-out}
```

**约束**

- 📌 **内容要跟着处理。** 盒子变小了,里面的字得先淡出,否则会挤成一团再被裁 ——
  这是形变最容易穿帮的地方。
- ⚠️ 动尺寸触发布局重算。**能用缩放就用**;真需要改形状(圆角 / 裁切)才认这个成本。
- 📌 裁切形变要求**两端形状同型**,否则不插值。

**令牌**:`{motion.dur-popup}` `{motion.ease-in-out}`

<details>
<summary>web 参考实现</summary>

```css
.morph{ width:120px; height:44px; border-radius:22px;
  transition:width var(--dur-popup) var(--ease-in-out),
             height var(--dur-popup) var(--ease-in-out),
             border-radius var(--dur-popup) var(--ease-in-out) }
.morph.loading{ width:44px; border-radius:50% }      /* 胶囊 → 圆 */
```
</details>

---

## 共享元素转场 Shared element

**别名**:"缩略图变成大图" / "点进去那个跟着飞过去" / hero animation / FLIP
**类**:① 功能 UI

一个元素**从 A 位置飞到 B 位置并变形**,跨越两个界面。它是**连续性**最强的形态:
玩家的眼睛全程没丢过它。

**用**:列表卡 → 详情页、头像 → 资料页、缩略图 → 全屏图。
**别用**:低性能设备上的长列表(每次都要量两次布局)。

**方法**

> ❗ **就是 [`algorithms.md §6`](algorithms.md) 的 FLIP。别自己实现。**

```text
F 量起点 → 改到终态(不加动画)→ L 量终点 → I 反向偏移假装还在起点 → P 放开
时长 {motion.dur-popup} · 曲线 {motion.ease-in-out}
```

**约束**

- 📌 **FLIP 的全部意义是:用一次变换演出一个本该由布局完成的变化。**
- 📌 改结构那一步**别加动画**,否则量到的终点是中间态。
- 📌 反向偏移之后**必须强制它立刻生效**,否则和 Play 合并成一次 = 等于没做。

**令牌**:`{motion.dur-popup}` `{motion.ease-in-out}`

---

## 布局动画 Layout animation

**别名**:"位置变了会自己动过去" / "不瞬移" / "自动补间" / auto-animate
**类**:① 功能 UI

元素的位置 / 尺寸变了,**它自己动过去**,而不是瞬移。跟共享元素的区别:**不跨界面**,就在原地重排。

**用**:列表增删、筛选重排、拖拽排序时其它项让位。
**别用**:一次动几十上百个元素(全量 FLIP 会卡)。

**方法**:同 FLIP([`algorithms.md §6`](algorithms.md)),对每个受影响的元素都做一遍。

**约束**

- 📌 **让位要快。** 它是**背景信息**,不是主角 —— 用 `{motion.dur-tab}` 甚至更短;
  慢了会显得整个列表在晃。
- 📌 **别 stagger。** 重排不是入场,逐个让位会像多米诺骨牌倒。
- ⚠️ 元素多时先测再上。**FLIP 的成本随元素数线性涨。**

**令牌**:`{motion.dur-tab}` `{motion.ease-out}`

---

## 折叠 / 展开 Accordion

**别名**:"收起来展开" / "抽屉列表" / "点一下露出下面" / collapse / expand
**类**:① 功能 UI

高度从 0 长到内容高度。**手游里最常见、也最容易写错的效果。**

**用**:FAQ、设置分组、可展开的说明。
**别用**:内容极长时(展开后玩家已经不知道自己在哪了)。

**方法**

```text
把「容器高度」当成 0 → 内容高度 的插值,内层裁掉溢出
⚠️ 关键是**不要求你事先知道内容高度** —— 用引擎里能表达「按内容撑开」的那个量去插值
时长 {motion.dur-tab} · 曲线 {motion.ease-out}
```

**约束**

- ❌ **别对「自动高度」直接做插值** —— 它通常不可插值,会直接跳变。这是这个效果的头号坑。
- ❌ **别用「最大高度设个大数」硬凑** —— 内容比它短时,动画会有一段**空转**,时长完全对不上。
- 📌 裁切溢出要在**内层**,不是外层。

**令牌**:`{motion.dur-tab}` `{motion.ease-out}`

<details>
<summary>web 参考实现(现代做法:0fr → 1fr,不需要知道内容高度)</summary>

```css
.acc{ display:grid; grid-template-rows:0fr;
  transition:grid-template-rows var(--dur-tab) var(--ease-out) }
.acc.open{ grid-template-rows:1fr }
.acc > div{ overflow:hidden }        /* 必需：否则内容不被裁，展不出效果 */
```
</details>

---

## 方向感知转场 Direction-aware

**别名**:"前进往左后退往右" / "有方向的翻页" / directional
**类**:① 功能 UI

前进时内容往一个方向滑,后退时往反方向 —— **导航因此有了「里外」的空间感**。

**用**:多级菜单、页签左右切、向导流程、图鉴翻页。
**别用**:平级且无序的切换(那没有「前进 / 后退」可言)。

**方法**

```text
dir = +1 前进 / −1 后退
新页从 dir × 100% 处进,旧页往 −dir × 100% 处出(**比例,不是绝对像素**)
时长 {motion.dur-tab} · 曲线 {motion.ease-out}
```

**约束**

- 📌 **方向必须跟真实层级一致。** 往深处走 = 内容从一侧进;返回必须**反着来**,
  否则玩家会以为又进了一层。
- 📌 用比例不用绝对像素,自适应屏宽。

**令牌**:`{motion.dur-tab}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
function goto(page, dir){          // dir: +1 前进 / -1 后退
  const from = dir > 0 ? '100%' : '-100%';
  const to   = dir > 0 ? '-100%' : '100%';
  next.style.transform = `translateX(${from})`;
  void next.offsetWidth;
  cur.style.transform  = `translateX(${to})`;      // 旧的往反方向走
  next.style.transform = 'translateX(0)';
}
```
</details>

---

## 滚动揭示 Scroll reveal ⚠️ web 常用,手游竖版 UI 少见

**别名**:"滑到哪出现哪" / "往下滚才冒出来" / on-scroll / AOS
**类**:① 功能 UI

元素进入视口时才入场。

**用**:长页面(官网 / 活动页 / 图鉴长列表)。
**别用**:**首屏**(玩家已经在看了,还让他等入场 = 纯延迟);短页面。

**方法**

```text
监听「进入视口」→ 触发缩放入场;按进入顺序给 {motion.stagger}
**只放一次**,放完取消监听
```

**约束**

- 📌 **只放一次。** 来回滚一次播一遍,是这个效果最招人烦的用法。
- 📌 **别用滚动事件手写**,用平台提供的可见性回调 —— 它不占主线程。
- 📌 减弱动效下**全部直接显示**。

**令牌**:`{motion.enter}` `{motion.dur-popup}` `{motion.stagger}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
const io = new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return;
  e.target.classList.add('in');
  io.unobserve(e.target);          // 只放一次 —— 上下滚反复播是折磨
}), { threshold: .15 });
document.querySelectorAll('.reveal-on-scroll').forEach(el => io.observe(el));
```
</details>

---

## 滚动驱动 Scroll-driven ⚠️ web 专属

**别名**:"跟着滚动条走" / "滚多少动多少" / scrubbing
**类**:① 功能 UI

动画进度**直接绑滚动位置** —— 没有时长,玩家滚多少它走多少,**倒滚就倒放**。

**用**:阅读进度条、顶栏收缩、长图叙事。
**别用**:核心 UI。它把控制权完全交给滚动,**不可打断也不可跳过**。

**方法**

```text
进度 = 滚动位置 / 可滚动总量,**必须线性**
```

**约束**

- 📌 **必须线性。** 滚动本身就是玩家给的「时间轴」,再叠缓动 = 手感发飘、对不上手指。
- ⚠️ 原生的滚动时间线在部分内核(含小游戏内核)支持度未验证,落地前实测并准备降级。

**令牌**:—(进度由滚动给,不吃时长令牌)

<details>
<summary>web 参考实现</summary>

```css
@keyframes grow{ from{ transform:scaleX(0) } to{ transform:scaleX(1) } }
.progress{ transform-origin:left;
  animation:grow linear;
  animation-timeline:scroll(root block);   /* 进度 = 滚动位置，不是时间 */
}
```
</details>

---

## 视差 Parallax

**别名**:"远近层次" / "背景走得慢" / "有纵深" / parallax
**类**:① 功能 UI / ② 循环

前后景**以不同速度移动**,造出纵深。

**用**:主城背景、登录页、长图叙事、地图拖动。
**别用**:密集信息区(会晕),以及需要精确对位的地方。

**方法**

```text
每层位移 = 主位移 × 该层 depth      depth 越小 = 越远
基准 {motion.parallax-depth};0 = 无穷远不动,1 = 贴脸同速
```

**约束**

- 📌 **只动位移**,别动「背景贴图的偏移」(每帧重绘)。
- 📌 **层数 ≤ 3。** 再多既看不出来,也白烧。
- 📌 减弱动效下**关掉**。视差是**前庭不适的头号来源**,比任何其它效果都容易让人晕。

**令牌**:`{motion.parallax-depth}`

---

## 页面转场 Page transition

**别名**:"换界面那个" / "跳转动画" / route transition
**类**:① 功能 UI

从一个界面到另一个界面。

**用**:主城 ↔ 战斗 ↔ 背包等**大界面切换**。
**别用**:同屏页签切换(那是**方向感知转场**,更轻)。

**方法**

```text
{motion.scene} 时长 + **淡入淡出为主**;有明确层级关系时叠方向感知
```

**约束**

- 📌 **别炫。** 这是玩家一天要看几百次的东西 —— 频率表最该管的地方。**淡入淡出足够。**
- 📌 转场**必须能盖住加载**,而且是**并行**不是串行。

**令牌**:`{motion.scene}` `{motion.ease-out}`

---

## 浏览器视图转场 View Transition ⚠️ web 专属

**别名**:"原生跨页动画" / startViewTransition / VT API
**类**:① 功能 UI

浏览器**自己**在新旧两个 DOM 状态间做转场,并自动连接同名的共享元素。**等于免费的 FLIP。**

**用**:web 项目的路由切换、列表 → 详情。
**别用**:**游戏引擎里 —— 没有这个 API**,该用共享元素转场(FLIP)。

**约束**

- 📌 **共享元素的名字必须全局唯一**,同一时刻两个元素同名 = 整个转场静默失败。
- 📌 **必须写降级分支**,否则不支持的内核直接不更新界面。
- ⚠️ 小游戏内核支持度**未验证**。

**令牌**:`{motion.dur-popup}`

<details>
<summary>web 参考实现</summary>

```js
if (!document.startViewTransition) { mutate(); return; }   // 不支持就直接改
document.startViewTransition(() => mutate());
```
```css
.card[data-id="42"]{ view-transition-name:card-42 }   /* 新旧同名 → 浏览器自动飞过去 */
::view-transition-old(root){ animation:none }         /* 想自定义就覆盖这两个伪元素 */
```
</details>

---

## hover 效果 Hover ⚠️ 指针设备专属

**别名**:"鼠标放上去" / "指上去变色" / hover
**类**:① 功能 UI

**用**:PC 端可点元素的「这能点」暗示。
**别用**:**手游**。触屏上 hover 态会在点击后**粘住**(手指抬起了但状态还在),看着像卡了。

**方法**

```text
只动颜色 / 不透明度 · 时长 {motion.dur-tip}
**必须门控在「真有指针设备」的条件下** —— 不门控 = 触屏点完粘住
```

**约束**

- 📌 **hover 不能承载信息。** 触屏玩家永远看不到它 —— 任何只在 hover 里出现的内容都等于不存在。
- 📌 频率极高,**要么很轻,要么不做**。曲线用内置的就够,不值得动用令牌曲线。

**令牌**:`{motion.dur-tip}`

<details>
<summary>web 参考实现</summary>

```css
@media (hover:hover) and (pointer:fine){     /* ← 关键：只在真有指针的设备上启用 */
  .btn:hover{ background:var(--hi); transition:background var(--dur-tip) ease }
}
```
</details>

---

## 开关滑动 Toggle

**别名**:"设置里那个开关" / "拨一下" / toggle / switch
**类**:① 功能 UI

拨子从一头**滑**到另一头,轨道同时**变色**。表达一个**二元状态**的翻转。

**用**:设置项(音效 / 推送 / 画质)、任何非此即彼的选项。
**别用**:多于两个选项;**高频主玩法开关**(过频率关 —— 一天拨几百次就别加动效)。

**方法**

```text
拨子位移 0 → (轨道宽 − 拨子宽) · 轨道颜色交叉淡化
**同一个** {motion.dur-tab} + {motion.ease-out} —— 不需要新令牌,它是「滑入 + 交叉淡化」的组合
```

**约束**

- ❌ **拨子和轨道必须同时长同步。** 不同步 = 看到「拨子已经到了,颜色还没变」的半截状态。
- ❌ **别从缩放入场。** 它是**滑动**不是**出现** —— 拨子一直都在,只是换了个位置。
- ❌ **别加明显回弹。** 二元控件要**干脆**;一点点微弹是极限,再多就像玩具,也会让人误以为「没拨到位」。
- 📌 **状态不能只靠动效。** 拨子**位置**和轨道**颜色**两样都要变 —— 关了动效靠这两个静态差异
  照样读得懂开还是关。

**令牌**:`{motion.dur-tab}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.toggle{ transition:background var(--dur-tab) var(--ease-out) }      /* 轨道变色 */
.toggle .knob{ transition:transform var(--dur-tab) var(--ease-out) } /* 拨子滑动 —— 同时长同曲线 */
.toggle.on{ background:var(--on) }                                   /* 颜色引界面规范 */
.toggle.on .knob{ transform:translateX(var(--travel)) }              /* travel = 轨道宽 − 拨子宽 */
```
</details>

---

## 长按确认 Hold to confirm

**别名**:"按住不放那个" / "长按删除" / "按着读条" / press and hold
**类**:① 功能 UI

按住时进度条**填满**才生效。**它用「你得付出 N 秒」来防误触**,比二次弹窗轻,但同样慎重。

**用**:删除、解散、放弃 —— **不可逆且低频**的破坏性操作。
**别用**:常规操作。让玩家按住两秒去做日常事 = 惩罚。

**方法**

```text
按住:填充走**揭示**,时长 {motion.hold-dur},曲线 **线性**(进度必须诚实)
松手:快速弹回,时长 {motion.dur-tab},曲线 {motion.ease-out}
```

**约束**

- 📌 **填充必须线性。** 这是**进度**不是**动效** —— 加缓动等于骗人(看着快到了其实没到)。
- 📌 **松手要快。** 慢吞吞退回 = 玩家以为还在读条。**这是非对称缓动的典型场合。**
- 📌 **完成瞬间必须有非视觉反馈**(震动 / 音效),否则玩家不确定到底成没成。

**令牌**:`{motion.hold-dur}` `{motion.dur-tab}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.hold::after{ content:""; position:absolute; inset:0; background:var(--danger);
  clip-path:inset(0 100% 0 0);
  transition:clip-path var(--dur-tab) var(--ease-out) }     /* 松手：快速弹回 */
.hold:active::after{ clip-path:inset(0 0 0 0);
  transition:clip-path var(--hold-dur) linear }             /* 按住：匀速前进 */
```
</details>

---

## 拖拽排序 Drag to reorder

**别名**:"拖着换顺序" / "长按排序" / sortable
**类**:① 功能 UI(手势)

> ❗ **依赖**:手势部分见**直接操纵拖拽**;其它项让位见**布局动画**(FLIP)。**别自己实现。**

拖动一项,**其它项主动让开**,松手落位。

**用**:队伍编成、背包整理、快捷栏。
**别用**:顺序无意义的列表。

**方法**:拖起项跟手(见**拖拽**)→ 其余项 FLIP 让位(见**布局动画**)→ 松手弹簧落位。

**约束**

- 📌 **让位动画要比拖拽本身快**(`{motion.dur-tab}`)。它是背景,不是主角。
- 📌 **让位别 stagger**(会像多米诺)。
- 📌 **移动端必须先长按再拖**,否则跟页面滚动抢手势。PC 可直接拖。
- 📌 **占位符要留。** 让原位置塌陷,玩家会不知道「放回去」是放哪。

**令牌**:`{motion.drag-threshold}` `{motion.spring-ui}` `{motion.dur-tab}`

---

## 滑动关闭 Swipe to dismiss

**别名**:"划走" / "往下一甩就关了" / swipe away
**类**:① 功能 UI(手势)

> ❗ **依赖 [`algorithms.md`](algorithms.md) §2 弹簧 · §3 动量投射。别自己实现。**

拖出去就关掉。**关键在:它必须在拖到一半时能反悔。**

**用**:抽屉、Toast、可关闭的浮层。
**别用**:重要确认。**滑动太容易误触** —— 「确定要删除吗」不能靠划。

**方法**

```text
1:1 跟手 → 松手判定:
    位移 / 尺寸 > {motion.swipe-ratio}  **或**  速度 > {motion.flick-velocity}   → 关
    否则 → 弹簧 {motion.spring-ui} 归位
反方向拖要有橡皮筋({motion.rubberband-k})
```

**约束**

- 📌 **位移和速度是「或」不是「与」。** 快速小幅一甩,意图非常明确,不该因为位移不够而弹回。
- 📌 **只认单方向。** 抽屉从下来 → 只能往下划走。四面八方都能划 = 误触地狱。
- 📌 **反向要有橡皮筋。** 往上拖抽屉应该拉不动,但**得有一点点动**,否则像卡死了。

**令牌**:`{motion.swipe-ratio}` `{motion.flick-velocity}` `{motion.spring-ui}` `{motion.rubberband-k}`

---

## 橡皮筋 Rubber-banding

**别名**:"拉到头还能拽一点" / "回弹" / "iOS 那个" / overscroll
**类**:① 功能 UI(手势)

> ❗ **依赖 [`algorithms.md`](algorithms.md) §4 橡皮筋公式 + §2 弹簧。别自己实现。**

拖过边界时**阻力递增**,松手弹回。它是「到头了」这件事最好的表达 —— **比硬停住高明得多**:
硬停住的第一反应是「卡了 / 坏了」。

**用**:列表滚动到头、拖拽出界、缩放到极限。
**别用**:—— 只要有边界且能拖,就该有。

**方法**

```text
越界位移过 §4 衰减,k = {motion.rubberband-k};越界量**叠在**滚动量上
松手用 {motion.spring-ui} 弹回
```

**约束**

- 📌 **`k` 调的是「一开始有多黏」,不是「最多能拉多远」** —— 渐近上限恒等于容器尺寸,与 k 无关。
- 📌 **必须永远拉得动一点。** 完全拉不动 = 玩家以为卡死。
- 📌 弹回用 `{motion.spring-ui}`(临界阻尼,**不过冲**)。橡皮筋回弹再来一次过冲 = 果冻,廉价。

**令牌**:`{motion.rubberband-k}` `{motion.spring-ui}`

<details>
<summary>web 参考实现</summary>

```js
// 越界时不再 1:1 跟手，改走 algorithms §4 衰减
box.addEventListener('pointermove', e => {
  if (!grab) return;
  let next = grab.s - (e.clientY - grab.y);
  over = 0;
  if (next < 0){                                                   // 拖过顶
    over = rubberband(-next, box.clientHeight, CSSVAR('--rubberband-k'));
    next = 0;
  } else if (next > maxScroll()){                                  // 拖过底
    over = -rubberband(next - maxScroll(), box.clientHeight, CSSVAR('--rubberband-k'));
    next = maxScroll();
  }
  scroll = next;
  inner.style.transform = `translateY(${-scroll + over}px)`;       // 越界量叠在滚动量上
});
box.addEventListener('pointerup', () => {
  if (!over) return;
  sp = makeSpring(over, 0, 0, {damping: CSSVAR('--spring-ui-damping'),
                               response: CSSVAR('--spring-ui-response')});
  raf();                                                           // 每帧 over = sp.step(dt)
});
```
</details>

---

## 涟漪 Ripple

**别名**:"水波纹" / "安卓那个点击效果" / "从手指扩散" / material ripple
**类**:③ 反馈

从**触点**扩散出一个圆。它比按压反馈多说了一件事:**你点的是这里**。

**用**:大面积可点区(列表行 / 卡片)—— 光靠缩放看不出点在哪。
**别用**:小按钮(**按压反馈**足够);**卡通厚描边风格**里慎用 —— 涟漪是 Material 的语汇,风格不搭。

**方法**

```text
在触点生成一个圆,直径 ≥ 对角线 × 2(要盖住最远的角)
scale 0 → 1 · alpha 一定值 → 0 · 时长 {motion.ripple-dur} · 曲线 {motion.ease-out}
播完销毁;宿主要裁掉溢出
```

**约束**

- 📌 **`scale(0)` 在这里是允许的** —— 涟漪**不是一个物体**,它是扩散的波。
  「永不 scale(0)」针对的是**实体元素的入场**。
- 📌 播完必删(同**飘字**)。

**令牌**:`{motion.ripple-dur}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
host.addEventListener('pointerdown', e => {
  const r = host.getBoundingClientRect();
  const d = Math.hypot(r.width, r.height) * 2;          // 直径要够盖住最远的角
  const el = document.createElement('span');
  el.className = 'ripple';
  el.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX-r.left-d/2}px;top:${e.clientY-r.top-d/2}px`;
  host.appendChild(el);
  el.addEventListener('animationend', () => el.remove());   // 播完必删
});
```
```css
.ripple{ position:absolute; border-radius:50%; background:currentColor; opacity:.18;
  pointer-events:none; transform:scale(0);
  animation:ripple var(--ripple-dur) var(--ease-out) forwards }
@keyframes ripple{ to{ transform:scale(1); opacity:0 } }
```
宿主需 `overflow:hidden` + `position:relative`。
</details>

---

## 跑马灯 Marquee

**别名**:"滚动播报" / "公告在跑" / "字太长自己走" / ticker
**类**:② 循环

内容持续横向循环。

**用**:公告条、排行播报、**放不下的长名字**。
**别用**:玩家需要**从容读完**的东西 —— 会跑的字读起来累,而且他得等它绕回来。

**方法**

```text
内容复制两份首尾相接,整条向左移动自身的 50%,周期 {motion.loop-marquee},**线性**,无限循环
```

**约束**

- 📌 **必须线性。** 缓动会让它一顿一顿,像坏了。
- 📌 **内容复制两份**才能无缝;「移动 50%」与「两份」是绑定的,改一个必须改另一个。
- 📌 **指上去 / 摸上去要暂停**,给玩家读完的机会。
- 📌 内容**放得下就别跑**。

**令牌**:`{motion.loop-marquee}`

<details>
<summary>web 参考实现</summary>

```css
.marquee{ overflow:hidden; white-space:nowrap }
.marquee > .track{ display:inline-flex; animation:mq var(--loop-marquee) linear infinite }
@keyframes mq{ to{ transform:translateX(-50%) } }   /* -50% 因为内容复制了两份 */
```
</details>

---

## 环绕 Orbit

**别名**:"绕着转" / "卫星" / "光点在飞" / orbit
**类**:② 循环

一个元素绕着另一个转。

**用**:装饰光点、加载指示、稀有度光效。
**别用**:功能元素(绕着转的按钮点不中)。

**方法**

```text
父容器整体旋转 0° → 360°,周期 {motion.loop-spin},**线性**,无限循环
子元素偏移到半径上;要保持子元素正立就反向再转一次
```

**约束**

- 📌 **必须线性**,否则会「一顿一顿地绕」。
- 📌 算 ② 循环的预算(同屏 ≤ 3)。

**令牌**:`{motion.loop-spin}`

---

## 慢旋 Spin

**别名**:"一直转" / "光环" / "转圈加载" / rotate loop
**类**:② 循环

原地持续旋转。**装饰光环慢转 vs 加载圈快转,是同一个效果的两端。**

**用**:稀有光环(慢)、加载指示(快)。
**别用**:带文字的东西(转起来读不了)。

**方法**:`rotate 0° → 360°`,周期 `{motion.loop-spin}`,**线性**,无限循环。

**约束**

- 📌 **必须线性。**
- 📌 **加载圈转快点感觉加载更快** —— 同样的等待时间,主观更短。
  这是少数「加动画反而更快」的场合。
- 📌 装饰光环要**慢到几乎察觉不到**,否则变成噪音。

**令牌**:`{motion.loop-spin}`

---

## 流光边框 Animated border

**别名**:"边框流光" / "会转的边" / "霓虹描边" / glowing border
**类**:② 循环

一束光沿着元素**边缘绕圈**跑。它是**装饰性氛围**,不承载任何信息。

**用**:稀有 / 高价值元素的边框(限定卡、传说品质框)。**罕见才用,同屏 ≤ 3。**
**别用**:普通列表项、高频按钮 —— 满屏流光 = 廉价 + 噪音。

**方法**

```text
一个带角向渐变的图层垫在内容底下,**整体旋转**它(上 GPU)
内容盖在不透明内层上,只露出一圈边框宽度
周期 {motion.border-flow} · **线性** · 无限循环
```

**约束**

- ❌ **转图层,别每帧重画渐变的角度。** 后者每帧重画(paint),脱离 GPU;转一个图层是免费的。
- 📌 **必须线性**,否则绕一圈有快有慢,读作「卡了一下」。
- 📌 ② 循环规则照旧:弱、同屏 ≤ 3、减弱动效下**直接关掉**(纯装饰,关了不丢信息)。

**令牌**:`{motion.border-flow}`

<details>
<summary>web 参考实现</summary>

```css
.glow{ position:relative; border-radius:16px; overflow:hidden }     /* 半径/边宽引界面规范 */
.glow::before{ content:""; position:absolute; inset:-50%;           /* 盖满、留余量给旋转 */
  background:conic-gradient(from 0deg, transparent 0 70%, var(--accent) 85%, transparent 100%);
  animation:borderflow var(--border-flow) linear infinite }
.glow > *{ position:relative; margin:2px; border-radius:14px;
  background:var(--surface) }                                       /* 内层不透明，只露 2px 边 */
@keyframes borderflow{ to{ transform:rotate(360deg) } }
```
</details>

---

## 流动渐变 Animated gradient

**别名**:"渐变在动" / "背景流动" / "文字扫光" / animated gradient
**类**:② 循环

一块渐变背景**缓慢平移**,颜色像水一样流。也可裁到文字上做**文字流光**。

**用**:氛围底板(顶栏、活动 banner)、高价值按钮、标题文字扫光。**慢,宁静勿闹。**
**别用**:信息密集区(玩家要读的东西在动 = 添乱);高频元素。

**方法**

```text
一块**超尺寸**渐变持续平移一轮,周期 {motion.gradient-flow},**线性**,无限循环
```

**约束**

- ⚠️ **平移「贴图偏移」是每帧重画,不上 GPU。** 小按钮无所谓;**大面积**会掉帧 ——
  那就改成**平移一个超尺寸图层**,把重画换成合成。
- 📌 **必须线性**且**慢**(见令牌值域),否则从氛围变成噪音。
- 📌 减弱动效下**冻结在某一帧**(保留渐变、去掉流动)。

**令牌**:`{motion.gradient-flow}`

<details>
<summary>web 参考实现</summary>

```css
.flow{ background:linear-gradient(120deg, var(--c1), var(--c2), var(--c1));
  background-size:200% 100%;
  animation:gflow var(--gradient-flow) linear infinite }
@keyframes gflow{ to{ background-position:200% 0 } }
```
</details>

---

## 模糊遮掩 Blur mask

**别名**:"糊一下" / "虚化过渡" / "遮丑" / blur transition
**类**:① 功能 UI · **这是一条技法,不是一个独立效果**

在过渡途中**轻微模糊**,盖住不完美的中间帧。

**用**:**交叉淡化**的双曝光、内容差异大的替换、缩略图 → 高清图。
**别用**:大面积、长时间。

**方法**:过渡期间模糊半径 = `{motion.blur-mask}`,两端为 0。

**约束**

- ⚠️ **模糊很贵。** 硬上限见令牌值域,且**别大面积**。
- 📌 值要**小**。它是「遮掩瑕疵」,不是「虚化效果」—— 看得出在糊就过了。
- 📌 它是**创可贴**:先想想过渡本身能不能不难看。

**令牌**:`{motion.blur-mask}`

---

## 遮罩 Mask

**别名**:"软边裁切" / "渐隐边缘" / "羽化" / mask
**类**:① 功能 UI · 技法

像裁切,但**边缘可以是渐变的软边**。

**用**:长列表上下缘渐隐、**跑马灯两头淡出**、聚光灯、扫光。
**别用**:硬边裁切(那用普通裁切,更便宜)。

**方法**:用一张渐变遮罩乘到元素的 alpha 上;动画就动遮罩的位置或它的渐变端点。

**约束**

- 📌 遮罩会**让元素独立成层**,大面积有内存代价。
- 📌 硬边裁切能满足就别上遮罩 —— 软边不是免费的。

**令牌**:—

<details>
<summary>web 参考实现</summary>

```css
.fade-edges{                                    /* 上下缘渐隐 —— 列表滚动的标配 */
  mask-image:linear-gradient(to bottom, transparent 0, #000 24px, #000 calc(100% - 24px), transparent 100%);
}
```
部分内核仍要 `-webkit-mask-image` 前缀。
</details>

---

## 对比滑块 Before / after slider ⚠️ web 常用

**别名**:"拖着看前后对比" / "左右对比" / before-after
**类**:① 功能 UI(手势)

拖动分隔线,擦出下层图。

**用**:强化前后、皮肤对比、优化对比。
**别用**:手游核心 UI(用得着的场合很少)。

**方法**:上层裁切比例 = 指针位置 / 容器宽,**1:1 跟手,不加任何过渡**。

**约束**

- 📌 **跟手期间绝不能有过渡** —— 有了就是「手指走了它才慢慢跟上」,手感立刻废掉。
  **这是所有 1:1 手势的通则。**
- 📌 分隔线要有**明显把手**,否则玩家不知道能拖。

**令牌**:—(纯跟手,不吃时长)

<details>
<summary>web 参考实现</summary>

```js
el.addEventListener('pointermove', e => {
  if(!down) return;
  const r = el.getBoundingClientRect();
  const p = Math.max(0, Math.min(100, (e.clientX - r.left) / r.width * 100));
  top.style.clipPath = `inset(0 ${100 - p}% 0 0)`;       // 直接跟手，别 transition
});
```
</details>

---

## 线条自绘 Line drawing

**别名**:"自己画出来" / "笔在描" / "对勾划出来" / stroke animation
**类**:③ 反馈 / ④ 演出

矢量路径像被一支看不见的笔**画出来**。

**用**:成功对勾、图标点睛、加载完成、签名感。
**别用**:高频。这是**仪式感**,一天看几十次就烦。

**方法**

```text
虚线段长 = 路径总长(**必须实测,不能手填**)
虚线偏移从总长插到 0 · 时长 {motion.draw-dur} · 曲线 {motion.ease-out}
```

**约束**

- 📌 **路径长度必须实测** —— 换个图标就错。
- 📌 只对**描边**有效,填充的形状画不出来。
- 📌 **反向即「擦除」**,可复用同一套。

**令牌**:`{motion.draw-dur}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```js
const len = path.getTotalLength();                    // 必须实测，别手填
path.style.strokeDasharray  = len;
path.style.strokeDashoffset = len;
void path.getBoundingClientRect();                    // 让起点生效
path.style.transition = `stroke-dashoffset var(--draw-dur) var(--ease-out)`;
path.style.strokeDashoffset = 0;
```
</details>

---

## 文字形变 Text morph

**别名**:"字一个个变" / "数字翻牌" / "文字切换" / text scramble
**类**:③ 反馈

文字变化时**逐字**动,把「这里变了」点出来。

**用**:状态文案切换、称号变化、排名变动。
**别用**:长句子(逐字动的长句读不了);高频变化的数(那是**数字滚动**)。

**方法**:旧字逐个出场 → 新字逐个入场,间隔 `{motion.stagger}`。

**约束**

- 📌 **必须等宽或定宽容器**,否则整行随字宽跳动。
- 📌 字数多时**总时长会爆**(见 stagger 的 `{motion.dur-cap}` 约束)。超过 6–8 字就别逐字了。

**令牌**:`{motion.stagger}` `{motion.dur-tab}` `{motion.ease-out}`

---

## 骨架屏 / 流光 Skeleton / Shimmer

**别名**:"加载占位" / "灰条条" / "扫光" / placeholder / shimmer
**类**:② 循环

内容没到时,先摆一个**形状差不多的灰块**,上面一道光扫过说「在加载,没死」。

**用**:**已知布局**的内容加载(列表 / 卡片 / 头像)。
**别用**:极快的加载(< 300ms)—— 骨架屏一闪而过比转圈更烦;布局未知的内容(骨架和真内容对不上,更糟)。

**方法**:灰块 + 斜向高光沿元素内部循环平移,周期 `{motion.shimmer}`,**线性**,无限循环。

**约束**

- ⚠️ 这是本档少数**允许非「变换 / 不透明度」动画**的例外 —— 高光必须在元素内部走。
  **代价是每帧重绘,所以别大面积、别常驻。**
- 📌 骨架的**形状要贴近真内容**。对不上的话,内容到位时会「跳一下」,比转圈更糟。
- 📌 **加载完必须移除**,别留着当装饰。

**令牌**:`{motion.shimmer}`

<details>
<summary>web 参考实现</summary>

```css
.skeleton{ background:linear-gradient(100deg,#eee 30%,#f6f6f6 50%,#eee 70%);
  background-size:200% 100%;
  animation:shimmer var(--shimmer) linear infinite }
@keyframes shimmer{ to{ background-position:-200% 0 } }
```
</details>

---

## 打字机 Typewriter

**别名**:"一个字一个字出来" / "对话逐字" / typing
**类**:④ 演出 · **游戏里主要是剧情对话**

文字逐字出现。

**用**:剧情对话、开场旁白、新手引导。
**别用**:功能文案。**玩家要读的信息不该被人为拖慢。**

**方法**:每 `{motion.type-speed}` 露出一个字;光标用**分步动画**硬闪。

**约束**

- 📌 **必须能一点跳到全文。** 这是**铁律**:玩家第二遍看剧情时,逐字就是酷刑。
- 📌 **容器要预留全文高度**,否则打到换行时整个界面往下顶。
- 📌 别按「原始富文本」逐字切(会把标签切碎)。要带样式就逐节点处理。

**令牌**:`{motion.type-speed}`

<details>
<summary>web 参考实现</summary>

```js
let i = 0;
const timer = setInterval(() => {
  el.textContent = text.slice(0, ++i);
  if (i >= text.length) clearInterval(timer);
}, CSSVAR('--type-speed'));
el.addEventListener('click', () => { clearInterval(timer); el.textContent = text; });  // ← 必须能跳过
```
</details>

---

## 顿帧 Hitstop

**别名**:"打击感那个卡一下" / "命中定格" / hit stop / freeze frame
**类**:③ 反馈 · **游戏独有**

命中瞬间**整个画面冻结几十毫秒**。它是打击感的**最大来源** —— 比任何粒子、任何音效都管用,
而且**几乎免费**。

**用**:近战命中、暴击、格挡、必杀技起手。
**别用**:远程小伤害、持续伤害、高频普攻(每下都顿 = 整场都在卡)。

**方法**:命中帧把**时间缩放置 0**,`{motion.hitstop}` 后恢复。**越重的攻击顿越久**,
但都在几十毫秒量级。

**约束**

- ⚠️ **草案,未实测。** 接入战斗时必须实机调。
- 📌 **只顿受击方和攻击方,别顿 UI。** 血条、计时器继续走,否则像掉帧。
- 📌 **顿帧 + 震屏 + 飘字三件套要错开触发**,同时上会糊成一坨。
- 📌 顿太久(> 100ms)会从「有力」变成「卡顿」。**这条线很细,只能实测。**

**令牌**:`{motion.hitstop}`

---

## 震屏 Screen shake

**别名**:"屏幕在抖" / "地震" / "炸了那个" / camera shake
**类**:③ 反馈 · **游戏独有**

**整个画面**短促位移。跟**抖动**的区别:抖动是**一个元素**说「错了」,震屏是**整个世界**说
「这一下很重」。

> ⚠️ **别跟抖动共用令牌。** 抖动 = `{motion.wiggle}` / `{motion.wiggle-amp}`,
> 震屏 = `{motion.shake}` / `{motion.shake-amp}`。**真混过一次。**

**用**:大招落地、Boss 出场、暴击、爆炸。
**别用**:普通命中。**震屏是感叹号,不是句号。**

**方法**

```text
根容器每帧随机方向偏移,振幅 = {motion.shake-amp} × (1 − p)
总时长 {motion.shake};结束归零
```

**约束**

- ⚠️ **草案,两个令牌都未实测。**
- 📌 **必须衰减。** 等幅震 = 故障感。
- 📌 **UI 层别跟着震**(尤其虚拟摇杆和技能键)—— 会打不中。**只震游戏世界层。**
- 📌 减弱动效下**必须关掉**。**震屏是前庭不适的头号来源。**
- 📌 **别叠加**:两次震屏同时触发要**取最大**,不是相加,否则会飞出屏幕。

**令牌**:`{motion.shake}` `{motion.shake-amp}`

<details>
<summary>web 参考实现</summary>

```js
function screenShake(){
  const t0 = performance.now(), D = CSSVAR('--shake'), A = CSSVAR('--shake-amp');
  (function f(now){
    const p = (now - t0) / D;
    if (p >= 1){ root.style.transform = ''; return; }
    const a = A * (1 - p);                              // 线性衰减 —— 必须衰减
    root.style.transform = `translate(${(Math.random()*2-1)*a}px, ${(Math.random()*2-1)*a}px)`;
    requestAnimationFrame(f);
  })(t0);
}
```
</details>

---

## 高亮闪 Flash

**别名**:"闪一下" / "白光扫过" / "亮了一下" / flash / glint
**类**:③ 反馈 · **游戏独有**

短促的**一次性**提亮,说「这里刚变好了」。

**用**:升级、达成、解锁、刚获得的物品。
**别用**:常驻提示(那是**呼吸**);错误(那是**抖动**)。

**方法**

```text
叠一层白 / 亮色,alpha 一次性起落(**起得快、落得慢** —— 约 25% 处到峰值)
时长 {motion.flash} · 曲线 {motion.ease-out} · 播完移除
```

**约束**

- 📌 **叠层动不透明度,别动亮度滤镜**(每帧重绘)。同**呼吸**的理由。
- 📌 **一次性,不循环。** 要常驻请用**呼吸**。

**令牌**:`{motion.flash}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.flash::after{ content:""; position:absolute; inset:0; border-radius:inherit;
  background:#fff; opacity:0; pointer-events:none;
  animation:flash var(--flash) var(--ease-out) forwards }
@keyframes flash{ 0%{opacity:0} 25%{opacity:.75} 100%{opacity:0} }
```
</details>

---

## 仪式 Ceremony

**别名**:"升星那个" / "突破动画" / "进化演出" / celebration sequence
**类**:④ 演出 · **游戏独有** · **不受 `{motion.dur-cap}` 与频率表约束**

多段编排的**高价值兑现**。它不是一个动画,是**一串动画的剧本**。

**用**:升星 / 突破 / 进化 / 觉醒 —— 玩家投入了资源,**这是回报的兑付现场**。
**别用**:日常操作。

**方法(六段范本)**:主段 `{motion.ceremony-beat}` / 子段 `{motion.ceremony-sub}`

| 段 | 干什么 | 节拍 |
|---|---|---|
| veil | 压暗背景,把注意力收拢 | `{motion.ceremony-sub}` |
| burst | 爆发,能量汇聚 | `{motion.ceremony-beat}` |
| ring | 光环扩散 | `{motion.ceremony-sub}` |
| spark | 星火 / 粒子 | `{motion.ceremony-sub}` |
| subject | **主体亮相(这是玩家等的那一下)** | `{motion.ceremony-beat}` |
| cap | 收束,回到界面 | `{motion.ceremony-sub}` |

**约束**

- 📌 **结构通用,段名与节拍是项目取值。** 换项目改段、别改结构。
- 📌 **必须能跳过,且跳过直达终态**(不是快进)。
- 📌 **跳过不能跳过结果** —— 玩家跳的是过程,不是信息。
- 📌 **主体亮相那一段最重要**,前面全是铺垫。**别让铺垫比亮相长。**
- 📌 减弱动效下**大幅简化但别取消**(它承载「你得到了什么」)。

**令牌**:`{motion.ceremony-beat}` `{motion.ceremony-sub}`

---

## 血条填充 Bar fill

**别名**:"血条在动" / "经验条涨" / "读条" / bar tween
**类**:③ 反馈 / tween · **游戏独有**

条状进度平滑变化。

**用**:血条、经验条、进度、充能。
**别用**:需要**精确读数**的场合(动着的条读不准,配数字)。

**方法**

```text
用**横向缩放**(枢轴钉在起始边),**不是改宽度**
直接给终值,让过渡负责插值 · 时长 {motion.tween-bar} · 曲线 {motion.ease-out}
```

**约束**

- ❌ **别改宽度** —— 每帧触发布局重算。缩放上 GPU。
- 📌 **代价**:缩放会把条内的**纹理 / 文字一起拉伸**。有纹理就得把纹理放在**不被缩放的兄弟层**上。
- 📌 **扣血要快、加血可缓**(非对称)。失去要干脆,获得可以享受。
- 📌 **扣血的「残影条」**(白色滞后条)是两条 bar 不同延迟,不是一条 —— 便宜且有效。

**令牌**:`{motion.tween-bar}` `{motion.ease-out}`

<details>
<summary>web 参考实现</summary>

```css
.bar{ transform-origin:left; transform:scaleX(0);
  transition:transform var(--tween-bar) var(--ease-out) }
```
```js
bar.style.transform = `scaleX(${hp / hpMax})`;      // 直接给终值，transition 负责过渡
```
</details>

---

## 场景转场 Scene transition

**别名**:"切场景" / "进战斗那个黑屏" / "过场" / scene fade
**类**:① 功能 UI · **游戏独有(比 web 的页面转场更重)**

大场景之间的切换,**通常要盖住加载**。

**用**:主城 ↔ 战斗 ↔ 副本。
**别用**:同场景内的界面切换(那是**页面转场**或**方向感知**)。

**方法**

```text
{motion.scene} 淡入淡出为主
**正确顺序**:遮罩淡入 → **遮罩后面加载** → 加载完遮罩淡出
**错误顺序**:转场 → 加载(白屏)→ 淡入
```

**约束**

- 📌 **别把转场时长和加载时长串起来。** 要**并行**。
- 📌 加载超过约 1s 就得给**进度或提示**,光一个黑屏会让玩家以为死机。
- 📌 **别炫。** 玩家一天看几百次。

**令牌**:`{motion.scene}` `{motion.ease-out}`

---

> **59 条到此。** 覆盖工具型 web UI 词表的全部 41 个效果(含 web 专属的滚动 / 视差 / 打字机 /
> 骨架屏)+ **10 个游戏独有效果**(飘字 / 顿帧 / 震屏 / 高亮闪 / 仪式 / 出货 / 血条 / 飞向目标 /
> 场景转场 / 冷却扫描)+ 消费向装饰若干。
>
> **已知边界(如实记)**
>
> - **绝大多数令牌仍是 `inherited`** —— 抄来的,没针对游戏 UI 校准过。这是最大的一块空白。
> - **`hitstop` / `shake` / `shake-amp` / `wiggle` / `wiggle-amp` 五个是纯草案**,一次都没实测过。
> - **目录补不完,这是结构性的,不是「还差几条」。** 词表只有两个来源:工具型 web UI 的词表,
>   和真做过的那些屏。盲区 = **游戏里常见,但既不是 web UI、又还没做过那个屏**。已知落在这个
>   交集里、**暂不补**的:**镜头推拉 / 跟随**(属战斗镜头语言,已越过「界面动效」的边界 ——
>   真要做该另起一档,别让本档膨胀成「游戏里所有会动的东西」)、**拖尾 / 残影**、**轮播**
>   (吸附已覆盖其手势内核)。**补的机制**:做新屏时撞出来就加 ——
>   **照着真东西铺会撞出洞,凭空想想不出来。**
> - **`Tween` / `Momentum` 未独立成条** —— 它俩**是机制不是效果**,已含在数字滚动 / 血条填充 /
>   拖拽里。判为**不需要补**。
