// main.app.js — 主界面示例的 app 专属 hook(域内语义),挂 window.APPHOOK。
//
// **这个文件是这个示例的重点。** 引擎(assemble.js)管的是结构与机制:弹窗开合、按压、
// 列表克隆、guard。而下面这三条,figkit **一条都不实现** —— 它不知道哪个元素是"钱包":
//
//   ① 飞向目标 Fly to target   金币从领奖按钮飞进顶栏
//   ② 数字滚动 Number ticker   到账后货币数滚上去
//   ③ 高亮闪   Flash          最后一枚落袋时胶囊闪一下
//
// 方法与参数来自 figkit-motion(references/catalog.md 三条同名词条 + algorithms.md §1)。
// **一个动效数字都没硬编**:值从 fixtures.js 内联的 motion-tokens 取,令牌名就是目录里的名字。
// 这就是那个 skill 的用法 —— 目录给方法和参数,挂在哪个元素上由做界面的人决定。
(function () {
  const FIX = window.__FIGKIT_FIXTURES || {};
  const TOK = FIX['motion-tokens'] || {};
  const STAGE_W = 1080;

  // 元素 id(figma node id)。改稿后只需要动这一处。
  const EL = {
    claimBtn: '1:30',
    coinPill: '1:11', coinNum: '1:112',
    bagCells: Array.from({ length: 12 }, (_, k) => '4:' + (30 + k)),
    bagDots:  Array.from({ length: 12 }, (_, k) => '4:' + (50 + k)),
    codexList: '5:20',
  };

  // ── algorithms.md §1:cubic-bezier 求解器 ──────────────────────────────────
  // ❌ 别拿 easeOutCubic 之类的近似式凑合 —— 与 ease-out 令牌最大差 19.8 个百分点,
  //    而且差在起步段。CSS 那半边用的是真曲线,JS 这半边用近似式 = 同一个界面两种手感。
  function cubicBezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const sx = t => ((ax * t + bx) * t + cx) * t;
    const sy = t => ((ay * t + by) * t + cy) * t;
    const dx = t => (3 * ax * t + 2 * bx) * t + cx;
    return function (x) {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 12; i++) {          // 固定步数,不提前退出
        const d = dx(t);
        if (Math.abs(d) < 1e-9) break;
        t = Math.min(1, Math.max(0, t - (sx(t) - x) / d));
      }
      return sy(t);
    };
  }
  const EASE_OUT = cubicBezier.apply(null, TOK['ease-out'] || [0.23, 1, 0.32, 1]);

  // 确定性伪随机:①爆开那段要随机散布,但 GIF 录制是**逐帧重放**(每帧一个新页面),
  // 真随机会让金币在相邻两帧之间瞬移。种子固定 → 每次重放同一串位置。
  function rng(seed) {
    return function () {
      seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function $(layer, id) { return layer ? layer.querySelector('[data-id="' + id + '"]') : null; }
  function msg(text, err) {
    const el = document.getElementById('boot-err');
    if (el) {
      el.textContent = text; el.style.color = err ? '#f99' : '#7fd';
      clearTimeout(el._t); el._t = setTimeout(() => el.textContent = '', 3000);
    } else console.log('[msg]', text);
  }
  const fmt = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  // 舞台被缩放到视口大小,所以屏幕坐标要换回舞台坐标(飞行体挂在舞台里,跟着一起缩)。
  function stageBox() {
    const stage = document.getElementById('stage');
    const r = stage.getBoundingClientRect();
    return { stage: stage, r: r, scale: r.width / STAGE_W };
  }
  function centerOf(el, S) {
    const r = el.getBoundingClientRect();
    return { x: (r.left + r.width / 2 - S.r.left) / S.scale,
             y: (r.top + r.height / 2 - S.r.top) / S.scale };
  }

  // ── ① 飞向目标(catalog.md「飞向目标 Fly to target」)────────────────────────
  // 三段:爆开(散开一点,给"一堆东西"的量感)→ 停顿(让玩家看清有几个)→ 吸入(抛物线加速)。
  // ⚠️ 吸入段用的是 **ease-in** —— 这是本目录里 ease-in 唯一合法的场合:飞行体不是状态变化,
  //    是一个被吸走的物体,物理上就该越飞越快。改成 ease-out 会飞得像飘走。
  // 路径**先算好、再交给浏览器播**:把三段轨迹采成 KEYS 个关键帧,缓动写成 linear
  // (曲线已经烘进采样点里)。这跟 figkit 对转场曲线的处理是同一个思路 ——
  // 与其每帧用 JS 算一个位置,不如把整条轨迹交出去,让它跑在合成线程上。
  //
  // 还有一个很实际的理由:**逐帧 JS 循环在无头浏览器里根本不跑**(rAF 一次都不触发),
  // 而 tools/docs-assets 的 GIF 录制正是靠无头 + 暂停动画对象来抓中间帧的。
  // 声明式动画能被 pause() 钉在任意毫秒,JS 循环不能 —— 录出来就是一动不动。
  const KEYS = 24;

  function flyTo(fromEl, toEl, count, onFirst, onLast) {
    const S = stageBox();
    const a = centerOf(fromEl, S), b = centerOf(toEl, S);
    const arc = Math.hypot(b.x - a.x, b.y - a.y) * (TOK['fly-arc'] || 0.35);
    const DUR = TOK['fly-dur'] || 600, HOLD = TOK['fly-hold'] || 180;
    const STEP = TOK['fly-stagger'] || 60;
    const TOTAL = HOLD + DUR;
    const rand = rng(20260729);

    for (let i = 0; i < count; i++) {
      const el = document.createElement('div');
      el.className = 'flyer';
      S.stage.appendChild(el);
      const jx = (rand() * 2 - 1) * 64, jy = (rand() * 2 - 1) * 64;   // ① 爆开的散布

      const frames = [];
      for (let k = 0; k < KEYS; k++) {
        const off = k / (KEYS - 1), t = TOTAL * off;
        let x, y, s = 1;
        if (t < HOLD) {                                   // ①② 散开后停住,让玩家看清有几个
          const q = t / HOLD;
          x = a.x + jx * q; y = a.y + jy * q;
        } else {
          const p = (t - HOLD) / DUR, e = p * p;          // ③ ease-in:越飞越快(被吸走)
          x = (a.x + jx) + (b.x - a.x - jx) * e;
          y = (a.y + jy) + (b.y - a.y - jy) * e - arc * Math.sin(Math.PI * e);
          s = 1 - p * p * 0.4;                            // 快到时略缩,像被吞进去
        }
        frames.push({ offset: off,
                      transform: 'translate(' + (x - 22) + 'px,' + (y - 22) + 'px) scale(' + s + ')' });
      }
      el.animate(frames, { duration: TOTAL, delay: i * STEP, easing: 'linear', fill: 'both' });
      // 收尾走定时器,不挂 onfinish:动画事件要有帧才派发,而"播完了要删掉"这件事
      // 不能取决于有没有人在看这一帧(高频领奖不删 = 节点无限堆积)。
      setTimeout(() => el.remove(), i * STEP + TOTAL + 40);
    }
    // 编排:第一个到 → 数字开始滚;最后一个到 → 闪一下。
    // **对不齐的话,「飞进去」和「变多了」会读成两件事**(catalog「飞向目标」)。
    if (onFirst) setTimeout(onFirst, TOTAL);
    if (onLast) setTimeout(onLast, (count - 1) * STEP + TOTAL);
  }
  // ── ② 数字滚动(catalog.md「数字滚动 Number ticker」)─────────────────────────
  function tweenNum(el, from, to) {
    if (from === to) { el.textContent = fmt(to); return; }
    const D = TOK['tween-num'] || 600;
    let t0 = null, landed = false;
    const land = () => { if (!landed) { landed = true; el.textContent = fmt(to); } };
    // t0 取自 rAF 自己的时间戳 —— 与 performance.now() 可能不同轴,混用会让数字倒着跑。
    requestAnimationFrame(function step(now) {
      if (landed) return;
      if (t0 === null) t0 = now;
      const p = Math.max(0, Math.min(1, (now - t0) / D));
      el.textContent = fmt(Math.round(from + (to - from) * EASE_OUT(p)));
      if (p < 1) requestAnimationFrame(step); else land();
    });
    // 兜底:**数字必须到账,不能取决于有没有人在看。** 标签页在后台、或者无头浏览器里,
    // rAF 可能被节流甚至一次都不触发 —— 滚动是装饰,到账是事实,两者不能绑死。
    setTimeout(land, D + 60);
  }

  // ── ③ 高亮闪(catalog.md「高亮闪 Flash」)────────────────────────────────────
  // 叠一层动不透明度,别动亮度滤镜(每帧重绘)。起得快落得慢:25% 处到峰值。
  function flash(host) {
    const el = document.createElement('div');
    el.className = 'flash';
    host.appendChild(el);
    const D = TOK['flash'] || 900;
    el.animate([{ opacity: 0 }, { opacity: 0.75, offset: 0.25 }, { opacity: 0 }],
               { duration: D, easing: 'linear' });
    setTimeout(() => el.remove(), D + 40);       // 同上:清理不挂 onfinish
  }

  // ── 背包网格:逐项入场由**我们自己**做 ────────────────────────────────────
  // flow.list 的行克隆按"前两行的 y 差"定步长,而网格的前两格 y 相同 → 步长 0 → 全叠。
  // 它是一维机制,别硬套二维。所以格子在 fixture 里就画满,顺序(先行后列)在这儿定。
  function fillBag(app, items) {
    const L = app.layers.bag;
    const STEP = TOK['stagger'] || 45, D = TOK['dur-popup'] || 260, FROM = TOK['slide-from'] || 24;
    const bz = TOK['ease-out'] || [0.23, 1, 0.32, 1];
    const ease = 'cubic-bezier(' + bz.join(',') + ')';
    EL.bagCells.forEach((cid, k) => {
      const cell = $(L, cid), dot = $(L, EL.bagDots[k]);
      if (!cell) return;
      const item = items[k];
      if (dot) dot.style.background = item ? item.tint : 'rgba(0,0,0,0.06)';
      cell.style.transition = 'none';
      cell.style.opacity = '0';
      cell.style.transform = 'translateY(' + FROM + 'px)';
      void cell.offsetWidth;                       // 复位要先生效,否则下一步被合并(见 catalog 通则)
      cell.style.transition = 'opacity ' + D + 'ms ' + ease + ' ' + (k * STEP) + 'ms, ' +
                              'transform ' + D + 'ms ' + ease + ' ' + (k * STEP) + 'ms';
      cell.style.opacity = '1';
      cell.style.transform = '';
    });
  }

  function renderCodex(app, entries) {
    app.renderRows('codex', EL.codexList, entries, (row, e) => {
      const t = row.querySelector('[data-name="row-name"]');
      const d = row.querySelector('[data-name="dot"]');
      if (t) t.textContent = e.name;
      if (d) d.style.background = e.tint;
      row.dataset.entryId = e.id;
    });
  }

  window.APPHOOK = {
    register(app) {
      app.registerActions({
        // 领奖 = 一次编排:飞 → 滚 → 闪。三条都在 app 这一侧,引擎只负责把 click 送过来。
        claim: async () => {
          const r = await app.net.send({ type: 'claim' });
          if (r.err !== 0) { msg('Claim failed, err=' + r.err, true); return; }
          const base = app.layers.base;
          const btn = $(base, EL.claimBtn), pill = $(base, EL.coinPill), num = $(base, EL.coinNum);
          const from = app._coin, to = from + r.coin;
          app._coin = to;
          flyTo(btn, pill, (window.MOCK && MOCK.claim.count) || 8,
                () => tweenNum(num, from, to),        // 第一个到 → 开始滚
                () => flash(pill));                   // 最后一个到 → 闪一下
          msg('+' + fmt(r.coin), false);
        },
        selectEntry: (row) => msg('Codex entry #' + row.dataset.entryId, false),
        send: async (type) => {
          if (type === 'OpenLocked') msg('Unlocked at Lv.15', true);
        },
        onGuardFail: () => msg('Reach Lv.15 to unlock this tab', true),
      });
    },
    init(app) {
      const M = (typeof MOCK !== 'undefined') ? MOCK : { purse: { coin: 0 }, bag: [], codex: [] };
      app._coin = M.purse.coin;
      renderCodex(app, M.codex || []);

      // 弹窗开合归引擎;"背包打开时格子要逐个进来"是域内决定 —— 包一层,不改引擎。
      const open = app.openModal.bind(app);
      app.openModal = function (name, transition) {
        open(name, transition);
        if (name === 'bag') fillBag(app, M.bag || []);
      };
    },
  };
})();
