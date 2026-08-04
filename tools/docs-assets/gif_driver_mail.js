// gif_driver_mail.js — examples/mail 的分帧重放。用法与规矩见同目录 README。
//
// 这份演的是 **v1.1 的 `@in:<modal>:<nodeId>`** 和**原地换态**:
// 领取不是"关一个弹窗再开另一个",是同一个面板换内容(flow 里声明成 DISSOLVE),
// 而触发它的按钮住在**弹窗那一屏**上 —— v1.0 的 events 只能绑 base 屏,这条根本写不出来。
(function () {
  var STEP = parseInt((location.search.match(/step=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };
  var IN = function (modal, id) {
    return document.querySelector('[data-modal="' + modal + '"] [data-id="' + id + '"]');
  };
  var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  function freeze(ms) {
    document.getAnimations().forEach(function (a) {
      try { a.pause(); a.currentTime = ms; } catch (e) { /* 已结束的动画设不了,忽略 */ }
    });
  }

  var MAIL_WITH = '25:1615';      // 带附件的那封(列表第一行)
  var MAIL_PLAIN = '25:1629';     // 无附件的那封
  var CLAIM = '25:2568';          // @in:read:25:2568
  var CLOSE_CLAIMED = '31:1424';  // @in:claimed:31:1424 —— 已领取态的「删除」

  // 每一帧都是**新开一页**,所以每一步都得从开机状态自己走到位。
  // 停在中途的那几帧必须**先停时钟**:出场/换态播完是由定时器收尾的,而定时器不受
  // pause() 影响 —— 光 freeze 的话,截图那一刻层已经被藏起来了,帧长得跟下一步一样。
  function afterOpen(then) {
    return function () {
      Q(MAIL_WITH).click();
      return wait(500).then(then);
    };
  }

  var STEPS = [
    [function () {}, null],                                   // 0 静止:邮件列表
    [function () { Q(MAIL_WITH).click(); }, 60],              // 1 弹窗入场 · 早期(SCALE_IN)
    [function () { Q(MAIL_WITH).click(); }, 150],             // 2 弹窗入场 · 中段
    [function () { Q(MAIL_WITH).click(); }, null],            // 3 停住:带附件的邮件详情
    [afterOpen(function () {                                  // 4 领取 · 换态中途(DISSOLVE)
      window.setTimeout = function () { return 0; };
      IN('read', CLAIM).click();
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { freeze(90); });
      });
    }), null],
    [afterOpen(function () { IN('read', CLAIM).click(); }), null],   // 5 停住:已领取态
    [afterOpen(function () {                                  // 6 关闭 · 出场中途(SCALE_OUT)
      IN('read', CLAIM).click();
      return wait(400).then(function () {
        window.setTimeout = function () { return 0; };
        IN('claimed', CLOSE_CLAIMED).click();
        requestAnimationFrame(function () {
          requestAnimationFrame(function () { freeze(90); });
        });
      });
    }), null],
    [function () { Q(MAIL_PLAIN).click(); }, null],           // 7 停住:无附件的邮件(只有删除)
  ];

  setTimeout(function () {
    var s = STEPS[Math.min(STEP, STEPS.length - 1)];
    Promise.resolve(s[0]()).then(function () {
      if (s[1] !== null) setTimeout(function () { freeze(s[1]); }, 20);
    });
  }, 260);
})();
