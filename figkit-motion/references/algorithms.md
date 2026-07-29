# 算法工具箱 — 跨效果共用的那点数学

> **什么时候需要本档**:你要**自己插值**的时候 —— 引擎侧 tween、canvas、shader、或者任何没有
> CSS 帮你算的地方。用 CSS / WAAPI 的话浏览器已经算完了,直接看 `catalog.md` 的配方。
>
> **figkit 自己用了其中两条**:§1 贝塞尔求解器与 §2 弹簧解析解就是
> `figma2html/scripts/motion.py` 里的 `bezier_solver` / `spring_solver`(六个后端各带一份
> **逐字节镜像**)。它把曲线解成 17 个采样点烘进 `motion.json`,引擎侧只做线性插值 ——
> **所以用 figkit 的转场时,这两条你不用自己实现**。其余四条(动量投射 / 橡皮筋 / 速度采样 /
> FLIP)figkit 不管,要用就照这儿写。

| # | 算法 | 谁在用 | figkit 是否已实现 |
|---|---|---|---|
| 1 | cubic-bezier 求解器 | 一切自定义曲线 | ✅ `motion.py bezier_solver` |
| 2 | 弹簧(解析解) | 拖拽 / 吸附 / 滑动关闭 / 橡皮筋回弹 | ✅ `motion.py spring_solver` |
| 3 | 动量投射 | 松手后的惯性 | ❌ |
| 4 | 橡皮筋 | 越界阻力 | ❌ |
| 5 | 速度采样 | 一切「松手要交接速度」的手势 | ❌ |
| 6 | FLIP | 共享元素转场 / 布局动画 / 拖拽排序 | ❌ |

---

## §1 · cubic-bezier 求解器

`cubic-bezier(x1,y1,x2,y2)` 是三次贝塞尔:P₀=(0,0) 与 P₃=(1,1) 固定,你填中间两个控制点。
**横轴 = 时间进度,纵轴 = 动画进度。**

```text
x(t) = 3(1-t)²t·x1 + 3(1-t)t²·x2 + t³
y(t) = 3(1-t)²t·y1 + 3(1-t)t²·y2 + t³
```

> ⚠️ **`t` 不是时间,是曲线参数。** 不能把时间代进 `y()` —— 必须先由时间进度 `x` **反解**出
> `t`,再算 `y`。这一步**没有闭式解**,只能数值求解。

**方法**

```text
预计算多项式系数(x 与 y 各一组):
  cx = 3·x1        bx = 3(x2−x1) − cx        ax = 1 − cx − bx
  cy = 3·y1        by = 3(y2−y1) − cy        ay = 1 − cy − by
  sampleX(t) = ((ax·t + bx)·t + cx)·t
  sampleY(t) = ((ay·t + by)·t + cy)·t
  slopeX(t)  = (3ax·t + 2bx)·t + cx

f(x):                                  // x = 时间进度 0..1 → 动画进度
  x ≤ 0 → 0 ; x ≥ 1 → 1
  t = x
  重复 N 次:                            // 牛顿迭代
    d = slopeX(t)
    d 太小 → 转二分兜底(48 次对分)
    t = clamp(t − (sampleX(t) − x)/d, 0, 1)
  返回 sampleY(t)
```

**约束**

- ❌ **别拿「差不多的近似式」凑合。** `1−(1−t)³`(easeOutCubic)与 `ease-out` 令牌
  **最大差 19.8 个百分点,出现在 x=0.23** —— 恰好是起步、玩家盯得最紧的那段。
  同名两条曲线 = 这个引擎一种手感、那个引擎另一种。**要么用求解器,要么别叫它 ease-out。**
- ❌ **引擎内置的缓动枚举不等于令牌曲线。** `Tween.EASE_OUT` / `Ease.OutQuad` / USS `ease-out` /
  `EEasingFunc` 全是同名不同形。要么喂自定义曲线,要么用本求解器采样成曲线资源。
- 📌 **迭代步数写死,别提前退出。** 「误差够小就 break」会让步数依赖 libm 的最后一位,
  跨平台各走各的步数 —— 想做逐字节可复现的 golden 就断在这儿。(figkit 取 12 步。)

<details>
<summary>web 参考实现(figma2html 用的就是这条,但它在 python 侧;此处是等价 JS)</summary>

```js
function cubicBezier(x1, y1, x2, y2){
  const cx = 3*x1, bx = 3*(x2-x1) - cx, ax = 1 - cx - bx;
  const cy = 3*y1, by = 3*(y2-y1) - cy, ay = 1 - cy - by;
  const sampleX = t => ((ax*t + bx)*t + cx)*t;
  const sampleY = t => ((ay*t + by)*t + cy)*t;
  const slopeX  = t => (3*ax*t + 2*bx)*t + cx;
  return function(x){
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 12; i++){                 // 固定步数
      const d = slopeX(t);
      if (Math.abs(d) < 1e-9){                    // 斜率塌了 → 二分兜底
        let lo = 0, hi = 1; t = x;
        for (let j = 0; j < 48; j++){
          if (sampleX(t) > x) hi = t; else lo = t;
          t = (lo + hi) / 2;
        }
        break;
      }
      t = Math.min(1, Math.max(0, t - (sampleX(t) - x) / d));
    }
    return sampleY(t);
  };
}
```
</details>

---

## §2 · 弹簧(解析解)

**用在哪**:拖拽 / 甩动 / 可被中途反转的手势。**非手势的预定动效仍用 transition / tween。**

两个设计师友好的参数:**阻尼比 damping** 控制过不过冲、**response** 控制多快到达(秒)。

> **为什么不用 mass / stiffness / damping 三元组** —— 别的库大量用它,但那三个**互相纠缠**:
> 调大刚度会同时变快又变弹,想只改一样得同时动两个。damping / response 是**解耦**的。
> 换算得出来(见下),但**别在设计层用三元组思考**。
>
> ⚠️ **`response` 不是 duration** —— 弹簧没有固定时长,settle 时刻由参数涌现。
> **感知时长**:弹簧在玩家觉得它停了之后,底下还在做察觉不到的微调。所以「什么时候结束」
> 要用 `settled` 阈值判,别用固定计时器 —— 用计时器要么截断弹跳、要么白等。

**方法**

```text
参数换算(figma / 别的库给三元组时):
  ω₀ = √(stiffness / mass)
  ζ  = damping / (2·√(stiffness·mass))
  response = 2π / ω₀

以 u₀ = x₀ − target(初始偏移)、v₀(初始速度)解:
  s = ζ·ω₀
  ζ ≈ 1  临界阻尼:  x = target + e^(−ω₀t)·(u₀ + (v₀ + ω₀u₀)·t)
  ζ < 1  欠阻尼:    ω_d = ω₀√(1−ζ²)
                    x = target + e^(−st)·(u₀·cos(ω_d t) + ((v₀+s·u₀)/ω_d)·sin(ω_d t))
  ζ > 1  过阻尼:    r = ω₀√(ζ²−1),两个实根 a₁=−s+r、a₂=−s−r,两项指数叠加

收敛判据(别用固定计时器):
  settled = |x − target| < ε_pos 且 |v| < ε_vel
收敛时刻的解析上界(要判「duration 够不够」时用):
  settle_time = −ln(ε) / (ζ·ω₀)          // ζω₀ = 包络衰减率;ζ=0 → 永不停止
```

**约束**

- ❌ **别用半隐式欧拉。** 实测:在 ω₀·dt ≈ 0.35 量级(response 0.3 / 60fps),它的数值阻尼会把
  damping 0.8 该有的 **1.52% 过冲全部吃掉,还原度 0%** —— 「手势带动量才给弹跳」这条规则会
  **形同虚设,而且你从产物上看不出来**。必须用解析解。
- 📌 **2D 要两条弹簧,不是一条。** 一条弹簧只能管一个标量;拿它管「到目标的直线距离」等于强迫
  X 和 Y 共用一个进度。斜着甩出去时两轴速度不同,轨迹会**拧着走**,先到的那轴被后到的拖住。
  **X 一条、Y 一条,各自 step(dt),两条都 settled 才算停。**
- 📌 **反转手势时别停掉旧弹簧再建新的。** 用「重定向」:以当前 x、**当前 v** 为新初始条件、
  时间归零。速度归零重建 = **砖墙**,玩家正甩着却感觉撞了一下。**这也是弹簧比关键帧强的根本
  原因** —— 关键帧无论如何都从 0% 重启。
- 📌 **step(dt) 要夹掉长帧**(如上限 1/30 秒),否则一次卡顿会让弹簧跳过半个周期。

<details>
<summary>web 参考实现(带重定向与 settled)</summary>

```js
function makeSpring(x0, v0, target, cfg){
  const w0 = 2 * Math.PI / cfg.response;   // 自然频率
  const z  = cfg.damping;                  // 阻尼比：1=临界(不过冲) <1=过冲
  let t = 0, tgt = target, u0 = x0 - target, vv0 = v0, x = x0, v = v0;
  const s = z * w0;
  function at(tt){
    if(Math.abs(z - 1) < 1e-3){                       // 临界阻尼
      const A = u0, B = vv0 + w0*u0, e = Math.exp(-w0*tt);
      x = tgt + e*(A + B*tt);
      v = e*(B - w0*A - w0*B*tt);
    } else if(z < 1){                                 // 欠阻尼 → 会过冲
      const wd = w0*Math.sqrt(1 - z*z), e = Math.exp(-s*tt);
      const A = u0, B = (vv0 + s*u0)/wd;
      const c = Math.cos(wd*tt), n = Math.sin(wd*tt);
      x = tgt + e*(A*c + B*n);
      v = e*((B*wd - s*A)*c - (A*wd + s*B)*n);
    } else {                                          // 过阻尼
      const r = w0*Math.sqrt(z*z - 1), a1 = -s + r, a2 = -s - r;
      const C2 = (vv0 - a1*u0)/(a2 - a1), C1 = u0 - C2;
      const e1 = Math.exp(a1*tt), e2 = Math.exp(a2*tt);
      x = tgt + C1*e1 + C2*e2;
      v = C1*a1*e1 + C2*a2*e2;
    }
  }
  return {
    get x(){ return x; },
    get v(){ return v; },
    // 重定向：以【当前 x, v】为新初始条件、时间归零。
    // vv0 = v 这一行就是「速度混合」：新动画继承旧动画【此刻的速度】。
    // 换成 vv0 = 0 就是硬切 —— 手上读作撞到一堵砖墙。
    set target(nt){ u0 = x - nt; vv0 = v; tgt = nt; t = 0; },
    get target(){ return tgt; },
    step(dt){ t += Math.min(dt, 1/30); at(t); return x; },   // 掉帧保护
    get settled(){ return Math.abs(x - tgt) < 0.35 && Math.abs(v) < 12; }
  };
}
```
</details>

---

## §3 · 动量投射

松手后靠惯性还能滑多远。**用指数衰减式,不是教科书的 `v²/(2a)`**:

```text
projected = v · d / (1 − d)          // v 单位 px/ms,d = decel-rate 令牌
```

`d = 0.998` → 系数 499:甩出阈值 `flick-velocity` = 0.11 px/ms 约投射 55px。

**约束**

- 📌 投射距离是**用来选落点的**(投到哪一格 / 哪一页),不是用来直接播位移的。选完落点,
  位移交给 §2 的弹簧,这样中途还能被抓回。
- 📌 `decel-rate` 越小越跟手:0.99 比 0.998 更「snappy」,滑得更短。

---

## §4 · 橡皮筋

拖出边界时的阻力。位移越大越拉不动,但**永远拉得动一点**:

```text
rubberband(overshoot, dim, k) = (overshoot · dim · k) / (dim + k · |overshoot|)
    overshoot = 越界距离   dim = 容器该轴尺寸   k = rubberband-k 令牌
```

**`k` 到底控制什么** —— 别猜错,实测过:

| | 结论 |
|---|---|
| **小位移时** | 实际位移 ≈ `overshoot × k`。**k = 初始跟手比例**(k=0.55 → 拖 100px 实际动约 48px) |
| **渐近上限** | **恒等于 `dim`,与 k 无关**(拖一百万 px 也只动到 dim)。k 只影响**多快逼近**这个上限 |

所以调 `k` 是在调「**一开始有多黏**」,**不是**在调「最多能拉多远」。

**约束**

- 📌 **必须永远拉得动一点。** 完全拉不动 = 玩家以为卡死了。
- 📌 松手回弹用 `spring-ui`(临界阻尼,**不过冲**)。橡皮筋回弹再来一次过冲 = 果冻,廉价。

---

## §5 · 速度采样

**谁在用**:拖拽 · 吸附 · 滑动关闭 · 橡皮筋 —— 凡是「松手要交接速度」的手势,全靠它。
从指针历史算出松手瞬间的速度(px/ms)。**看着简单,三个坑全在细节里。**

```text
维护一个定长历史环:  push(x, y, t) 后只保留最近约 5 条
velocity() =
    a = 历史最早一条, b = 最新一条
    dt = max(1, b.t − a.t)             // 除零保护
    ((b.x−a.x)/dt, (b.y−a.y)/dt)
```

**三个坑**

- ⚠️ **① 只留最近几帧(约 5)。** 留全程 = **速度被历史稀释** —— 玩家慢慢拖了 3 秒、最后猛地一甩,
  平均速度接近 0,**「甩」永远判不出来**。
- ⚠️ **② `dt` 必须除零保护。** 同一帧内两个 move 事件(高刷设备很常见)→ dt = 0 →
  速度 = ∞ → 投射距离 ∞ → 元素飞出宇宙。
- ⚠️ **③ 用事件自带的时间戳,别用「现在几点」。** 事件时间戳是**事件真正发生的时刻**;
  `now()` 是**你的代码跑到这一行的时刻**。中间隔着排队与主线程阻塞 —— 卡一下速度就算飞了。
  (同一个病也出现在数字滚动:**别混时间轴**。)

<details>
<summary>web 参考实现</summary>

```js
function makeTracker(){
  let hist = [];
  return {
    reset(e){ hist = [{x:e.clientX, y:e.clientY, t:e.timeStamp}]; },
    push(e){
      hist.push({x:e.clientX, y:e.clientY, t:e.timeStamp});
      if (hist.length > 5) hist.shift();          // ① 只留最近几帧
    },
    get origin(){ return hist[0]; },              // 判"过没过拖拽阈值"用的起点
    velocity(){                                   // px/ms
      if (hist.length < 2) return {x:0, y:0};
      const a = hist[0], b = hist[hist.length-1];
      const dt = Math.max(1, b.t - a.t);          // ② 除零保护
      return { x:(b.x-a.x)/dt, y:(b.y-a.y)/dt };
    }
  };
}
```
</details>

---

## §6 · FLIP

**谁在用**:共享元素转场 · 布局动画 · 拖拽排序(让位)。

**用一次位移/缩放演出一个本该由布局完成的变化。** 四个字母 =
**F**irst(量起点)· **L**ast(量终点)· **I**nvert(假装还在起点)· **P**lay(放开)。

```text
first = 量当前包围盒
mutate()                              // 直接改到终态,不加任何动画
last  = 再量一次包围盒
d  = first.topLeft − last.topLeft
s  = first.size / last.size           // 两轴各一个
没动(d=0 且 s=1)→ 直接返回,别放空动画

关掉过渡 → 把元素反向偏移 d、反向缩放 s(**枢轴钉在左上角**)→ 让这一步立刻生效
→ 打开过渡 → 清掉偏移与缩放
```

**为什么非它不可**:直接动尺寸/位置属性**每帧都要重算布局**,必卡。FLIP 把整个过程压成
**一次布局 + 一条 GPU 上的变换**。

**坑**

- ⚠️ **枢轴必须是左上角。** 默认绕中心缩放 → 算出来的位移全对不上,元素会歪到别处。
- ⚠️ **`mutate()` 里只改结构,别加动画** —— 否则量到的 Last 是中间态。
- ⚠️ **Invert 之后必须强制它立刻生效**,否则 Invert 和 Play 会被合并成一次,等于没做。
  (web 上是 `void el.offsetWidth`;引擎侧通常是「设完值先提交一帧」。)
- 📌 **成本随元素数线性涨。** 列表几十上百项时先测再上。

<details>
<summary>web 参考实现</summary>

```js
function flip(el, mutate, dur = 'var(--dur-popup)', ease = 'var(--ease-in-out)'){
  const first = el.getBoundingClientRect();          // F
  mutate();                                          // 直接改到终态（不加动画）
  const last  = el.getBoundingClientRect();          // L
  const dx = first.left - last.left, dy = first.top - last.top;
  const sx = last.width  ? first.width  / last.width  : 1;
  const sy = last.height ? first.height / last.height : 1;
  if (!dx && !dy && sx === 1 && sy === 1) return;     // 没动就别放动画
  el.style.transition = 'none';                       // I
  el.style.transformOrigin = 'top left';              // ← 不设的话缩放会绕中心，位置全歪
  el.style.transform  = `translate(${dx}px,${dy}px) scale(${sx},${sy})`;
  void el.offsetWidth;                                // 让 Invert 立刻生效
  el.style.transition = `transform ${dur} ${ease}`;   // P
  el.style.transform  = '';
}
```
</details>
