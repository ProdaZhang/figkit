// driver.js — 在真浏览器里演一小段,把量到的数写进 <title>,由 check.py 用 --dump-dom 读回。
//
// 为什么是"写数"而不是"截图":要断言的是**行为**(面板滑了多远、遮罩动没动、guard 拦没拦),
// 不是"看起来像不像"。数字能进 assert,截图只能靠人眼 —— 而这套东西正是因为没人天天用眼睛
// 盯着,才漏了三个缺陷过去。同理不需要 Pillow:纯标准库 + 一个浏览器。
//
// 每个 case 独立开一个页面,互不串状态。?case=N 选。
(function () {
  var CASE = parseInt((location.search.match(/case=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };

  // 把**真实动画对象**暂停并钉到某毫秒(与 docs-assets 的 GIF driver 同一套办法)。
  // t=0 尤其有用:那一刻进度必然是 0,位移必然等于**基准本身** —— 断言里不必掺进缓动曲线。
  function freeze(ms) {
    document.getAnimations().forEach(function (a) {
      try { a.pause(); a.currentTime = ms; } catch (e) { /* 已结束的设不了 */ }
    });
  }

  // 量静止态之前必须把转场收干净。否则量到的是**半路上**那一帧 ——
  // 第一次跑就踩了:面板 y 量出 2300 = 380 + 1920,正好是入场起点,看着像"坐标全错了"。
  function settle() {
    document.getAnimations().forEach(function (a) {
      try { a.finish(); } catch (e) { /* 不可结束的(无限循环)忽略 */ }
    });
  }

  function report(o) { document.title = 'FIGKIT-SMOKE ' + JSON.stringify(o); }

  // 页面被 mountStage 整体缩放过,量回 IR 坐标要除掉这个比例。
  function stage() {
    var l = document.getElementById('layer-base').getBoundingClientRect();
    return { rect: l, scale: l.width / 1080 };
  }
  function boxIn(el, s) {
    var r = el.getBoundingClientRect();
    return { x: (r.left - s.rect.left) / s.scale, y: (r.top - s.rect.top) / s.scale,
             w: r.width / s.scale, h: r.height / s.scale };
  }
  var round = function (b) { return { x: Math.round(b.x), y: Math.round(b.y),
                                      w: Math.round(b.w), h: Math.round(b.h) }; };

  var CASES = {
    // ① 静止态:弹窗内容按 IR 的绝对坐标叠加上来,行是从模板克隆出来的。
    0: function () {
      Q('1:10').click();
      return function () {
        settle();
        var s = stage();
        var layer = document.querySelector('[data-modal="serverlist"]');
        report({
          panel: round(boxIn(layer.querySelector('[data-id="3:10"]'), s)),
          rows: layer.querySelectorAll('[data-row]').length,
          // 收**每一行的文字**,不是"有没有文字"。行是从首行克隆的,模板自带文字 ——
          // 只验非空的话,rowFn 压根没被调用也照样绿(变异验证抓到过这一点)。
          rowTexts: Array.prototype.map.call(
            layer.querySelectorAll('[data-row]'), function (r) { return r.textContent.trim(); }),
          backdrops: layer.querySelectorAll('[data-backdrop]').length,
        });
      };
    },

    // ② MOVE_IN 停在 **0ms**:进度=0,面板此刻应当整整偏出一个**舞台**高度(1920),
    //    而不是它自己的高度(1160)。这一条就是那个真漂过的缺陷本身。
    //    顺带钉住遮罩:transform 只许贴面板,遮罩跟着淡不跟着滑(当年那个只有截图才抓到的 bug)。
    1: function () {
      Q('1:10').click();
      return function () {
        freeze(0);
        var s = stage();
        var layer = document.querySelector('[data-modal="serverlist"]');
        var panel = layer.querySelector('[data-id="3:10"]');
        var bd = layer.querySelector('[data-backdrop]');
        report({
          panelOffsetY: Math.round(boxIn(panel, s).y - 380),   // IR 里 y=380
          backdropOffsetY: Math.round(boxIn(bd, s).y),         // 遮罩不该动 → 0
          backdropH: Math.round(boxIn(bd, s).h),
        });
      };
    },

    // ③ guard:没勾协议 + 没选服 → 点开始必须被拦下,且**要有反馈**(抖动是个真动画对象)。
    //    以前这里是彻底的沉默 —— 界面毫无反应,玩家读到的是"卡了"。
    2: function () {
      var sent = [];
      window.FigApp.registerAction('send', function (arg) { sent.push(arg); });
      Q('1:20').click();
      return function () {
        report({
          sentWhileBlocked: sent.length,
          shakeAnimations: document.getAnimations().length,
          agreedBefore: window.FigApp.state.agreed,
        });
      };
    },

    // ④ checkbox 双态由引擎通用绑定管:点一下 flag 翻转、勾出现;再点回去勾消失。
    3: function () {
      Q('1:30').click();
      var after = Q('1:30').textContent.trim();
      Q('1:30').click();
      return function () {
        report({ markAfterCheck: after, markAfterUncheck: Q('1:30').textContent.trim(),
                 flag: window.FigApp.state.agreed });
      };
    },
  };

  // 260ms 让 app 的 onReady / 列表注入跑完(与 GIF driver 同一个等待)。
  setTimeout(function () {
    var after = CASES[CASE]();
    setTimeout(after, 40);
  }, 260);
})();
