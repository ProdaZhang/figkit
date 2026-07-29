// gif_driver.js — 分帧重放:按 ?step=N 演到那一步,并把**真实动画对象**暂停在指定时刻。
//
// 无头浏览器不能录屏。用 --virtual-time-budget 去"卡"中间帧不可靠(时间被压缩,
// 截图那一刻动画多半已经跑完)。这里改用 Web Animations API:触发之后拿
// document.getAnimations() 把真动画 pause() 并把 currentTime 定到某毫秒 ——
// 停住的是**真动画在那一刻的样子**,不是手改样式伪造出来的中间帧。
// (CSS transition 也在 getAnimations() 里,所以入场/出场与 WAAPI 的抖动是同一套办法。)
//
// ⚠️ **停在 null = 让它跑完**,那一帧就只剩终态。一次性效果如果停 null,截图时它早已归位 ——
//    画面上什么都看不见,而你会以为录进去了。真踩过:guard 抖动那一步原本停 null,
//    GIF 里只剩 hook 弹出的那行提示文字,**抖动本身一帧都没进去**。
(function () {
  var STEP = parseInt((location.search.match(/step=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function freeze(ms) {
    document.getAnimations().forEach(function (a) {
      try { a.pause(); a.currentTime = ms; } catch (e) { /* 已结束的动画设不了,忽略 */ }
    });
  }

  // 每一步 = [做什么, 停在第几毫秒]。做什么可返回 Promise(需要先演到某状态再触发时)。
  var STEPS = [
    [function () {}, null],                                   // 0 静止
    [function () { Q('1:40').click(); }, 70],                 // 1 公告淡入 · 早期
    [function () { Q('1:40').click(); }, 150],                // 2 公告淡入 · 中段
    [function () { Q('1:40').click(); }, null],               // 3 公告完全显示
    [function () {                                            // 4 公告出场中途(SCALE_OUT)
      Q('1:40').click();                                      //   出场是 preset 补的 —— figma
      return wait(420).then(function () {                     //   原稿只画了入场,没画出场
        // ⚠️ 出场这一帧比入场难截:closeModal 播完会把层 display:none 收掉,那个收尾是
        //    一个**不受 pause 影响的定时器** —— 光 freeze 动画,层照样在截图前被藏起来,
        //    拍到的是底屏,和"没点过"一模一样。所以先把之后的定时器全停掉。
        window.setTimeout = function () { return 0; };
        document.querySelector('[data-modal="notice"]').click();   // @any:notice → closeModal
        // 过渡对象要等一次样式重算才存在,所以隔两帧再 freeze(此时 setTimeout 已停,用 rAF)。
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { freeze(90); });
        });
      });
    }, null],
    [function () { Q('1:10').click(); }, 90],                 // 5 选服下滑 · 早期
    [function () { Q('1:10').click(); }, 190],                // 6 选服下滑 · 中段 + 行错开
    [function () { Q('1:10').click(); }, null],               // 7 选服完全显示
    [function () { Q('1:20').click(); }, 25],                 // 8 没勾协议就点开始 → guard 拦下 + 抖动
    //   25ms ≈ 抖动位移的峰值:sin(2πp)·(1−p) 在 p≈0.22 最大(120ms × 0.22)。
    //   停在别处会小一半,读起来像"没抖" —— 幅度本来就只有 wiggle-amp 那几个像素。
    [function () { Q('1:30').click(); }, null],               // 9 勾协议(checkbox 双态绑定)
    [function () { Q('1:30').click(); Q('1:20').click(); }, null],   // 10 再点开始 → 通过
  ];

  setTimeout(function () {
    var s = STEPS[Math.min(STEP, STEPS.length - 1)];
    Promise.resolve(s[0]()).then(function () {
      if (s[1] !== null) setTimeout(function () { freeze(s[1]); }, 20);
    });
  }, 260);
})();
