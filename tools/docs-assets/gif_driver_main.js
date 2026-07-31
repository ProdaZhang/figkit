// gif_driver_main.js — examples/main 的分帧重放。用法与规矩见同目录 README。
//
// 这份比 login 那份多演一件事:**hook 侧的动效**。领奖那三帧(爆开 / 停顿 / 吸入)拍的是
// app.js 里的「飞向目标」—— 它之所以录得到,正因为轨迹是**采样成关键帧交给浏览器播**的;
// 换成每帧 JS 算位置,无头这一路一次 rAF 都不触发,录出来会是静止的。
(function () {
  var STEP = parseInt((location.search.match(/step=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function freeze(ms) {
    document.getAnimations().forEach(function (a) {
      try { a.pause(); a.currentTime = ms; } catch (e) { /* 已结束的动画设不了,忽略 */ }
    });
  }

  var BAG = '1:52', CODEX = '1:56', SHOP = '1:50', CLAIM = '1:30';

  // 领奖那三帧:点一下 → 冻在第 N 毫秒。金币各自带 delay(fly-stagger),所以同一个毫秒上
  // 前面的已经在飞、后面的还没出发 —— "逐个出发"那件事因此录得到。
  //
  // ⚠️ 必须先停时钟。飞行体播完由**定时器**删掉(动画事件要有帧才派发,清理不能指望它),
  //    而定时器不受 pause() 影响:光 freeze 的话,截图那一刻八枚金币早被删干净了,
  //    三帧长得一模一样。和弹窗出场是同一个坑 —— 凡是"播完要收拾"的效果都吃这一刀。
  function claimAt(ms) {
    return function () {
      window.setTimeout = function () { return 0; };
      Q(CLAIM).click();
      return new Promise(function (done) {
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { freeze(ms); done(); });
        });
      });
    };
  }

  var STEPS = [
    [function () {}, null],                                   // 0 静止
    [function () { Q(BAG).click(); }, 90],                    // 1 背包下滑 · 早期
    [function () { Q(BAG).click(); }, 190],                   // 2 背包下滑 · 中段 + 格子逐项
    [function () { Q(BAG).click(); }, null],                  // 3 背包完全显示(12 格铺满)
    [function () {                                            // 4 按弹窗里的 ✗ → 出场中途
      Q(BAG).click();
      return wait(500).then(function () {
        // 出场那一帧要先停时钟:closeModal 播完会用定时器把层藏起来,那个定时器不受 pause 影响。
        window.setTimeout = function () { return 0; };
        // 点的是**弹窗里的那个 ✗**(`@in:bag:4:12`,v1.1 才有的写法),不是"点面板外关"。
        // 这是 figma 原稿真画的那条线;v1.0 只能拿 @panelOutside 近似,而那是另一回事。
        document.querySelector('[data-modal="bag"] [data-id="4:12"]').click();
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { freeze(90); });
        });
      });
    }, null],
    [function () { Q(CODEX).click(); }, null],                // 5 图鉴(DISSOLVE)+ 列表克隆
    [function () { Q(SHOP).click(); }, 25],                   // 6 点被锁的页签 → guard 抖动峰值
    [claimAt(120), null],                                     // 7 领奖 · 爆开(散开)
    [claimAt(320), null],                                     // 8 领奖 · 停顿看清个数 → 起飞
    [claimAt(620), null],                                     // 9 领奖 · 抛物线吸入中
    [function () { Q(CLAIM).click(); }, null],                // 10 落袋:数字已到账 + 胶囊闪
  ];

  setTimeout(function () {
    var s = STEPS[Math.min(STEP, STEPS.length - 1)];
    Promise.resolve(s[0]()).then(function () {
      if (s[1] !== null) setTimeout(function () { freeze(s[1]); }, 20);
    });
  }, 260);
})();
