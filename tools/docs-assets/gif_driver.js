// gif_driver.js — 分帧重放:按 ?step=N 演到那一步,并把**真实动画对象**暂停在指定时刻。
//
// 无头浏览器不能录屏。用 --virtual-time-budget 去"卡"中间帧不可靠(时间被压缩,
// 截图那一刻动画多半已经跑完)。这里改用 Web Animations API:触发之后拿
// document.getAnimations() 把真动画 pause() 并把 currentTime 定到某毫秒 ——
// 停住的是**真动画在那一刻的样子**,不是手改样式伪造出来的中间帧。
(function () {
  var STEP = parseInt((location.search.match(/step=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };
  var F = function () { return window.__FIGKIT_FIXTURES['flow.json']; };

  function freeze(ms) {
    document.getAnimations().forEach(function (a) {
      try { a.pause(); a.currentTime = ms; } catch (e) { /* 已结束的动画设不了,忽略 */ }
    });
  }

  // 每一步 = [做什么, 停在第几毫秒]。停在 null 表示让它跑完。
  var STEPS = [
    [function () {}, null],                                   // 0 静止
    [function () { Q('1:40').click(); }, 70],                 // 1 公告淡入 · 早期
    [function () { Q('1:40').click(); }, 150],                // 2 公告淡入 · 中段
    [function () { Q('1:40').click(); }, null],               // 3 公告完全显示
    [function () { Q('1:10').click(); }, 90],                 // 4 选服下滑 · 早期
    [function () { Q('1:10').click(); }, 190],                // 5 选服下滑 · 中段 + 行错开
    [function () { Q('1:10').click(); }, null],               // 6 选服完全显示
    [function () { Q('1:20').click(); }, null],               // 7 没勾协议就点开始 → guard 拦下
    [function () { Q('1:30').click(); }, null],               // 8 勾协议(checkbox 双态绑定)
    [function () { Q('1:30').click(); Q('1:20').click(); }, null],   // 9 再点开始 → 通过
  ];

  setTimeout(function () {
    var s = STEPS[Math.min(STEP, STEPS.length - 1)];
    s[0]();
    if (s[1] !== null) setTimeout(function () { freeze(s[1]); }, 20);
  }, 260);
})();
