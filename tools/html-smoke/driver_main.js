// driver_main.js — main 示例的行为冒烟。目前只有一件事:**v1.1 的 @in: 真的能用**。
//
// 那个 ✗ 是 figma 原稿画的线(nodes.json 里 4:12 上的 CLOSE),由 flow_from_figma.py
// 落成 `@in:bag:4:12`。v1.0 表达不了它 —— 只能拿"点哪都关 / 点面板外关"近似。
// 所以这条断言要同时说明两件事:按下去**关得掉**,以及关掉它的是**这个按钮**而不是
// 冒泡上去的 @panelOutside(✗ 就在面板里,冒泡上去反而不该触发)。
(function () {
  var CASE = parseInt((location.search.match(/case=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };

  function settle() {
    document.getAnimations().forEach(function (a) {
      try { a.finish(); } catch (e) { /* 不可结束的忽略 */ }
    });
  }
  function shown(name) {
    var l = document.querySelector('[data-modal="' + name + '"]');
    return !!l && l.style.display !== 'none';
  }
  function report(o) { document.title = 'FIGKIT-SMOKE ' + JSON.stringify(o); }

  var CASES = {
    // ① 弹窗内的 ✗(@in:bag:4:12)= v1.1 新增能力
    0: function () {
      Q('1:52').click();                       // 底栏页签 → 开背包(figma 原稿的 MOVE_IN)
      settle();
      var opened = shown('bag');
      var closeBtn = document.querySelector('[data-modal="bag"] [data-id="4:12"]');
      var found = !!closeBtn;
      if (found) closeBtn.click();
      settle();
      return function () {
        // ⚠️ `settle()` 只结束**动画**,而 closeModal 把层藏起来那一步走的是
        //    `setTimeout(done, dur)` —— 一个**不受动画控制的定时器**(GIF driver 那边
        //    踩过同一个坑,只是方向相反:那次是要抢在它之前)。等它跑完再量,
        //    否则读到的是"动画播完了、层还在",看着像 ✗ 根本没起作用。
        setTimeout(function () {
          report({ opened: opened, closeButtonFound: found, stillOpen: shown('bag'),
                   current: window.FigApp.current });
        }, 400);                               // 出场 180ms,留足余量
      };
    },

    // ② 反向锚:点面板**里**别的地方(标题)不该关 —— 否则上面那条也就没意义了,
    //    毕竟同一层上还挂着 @panelOutside:bag。
    1: function () {
      Q('1:52').click();
      settle();
      document.querySelector('[data-modal="bag"] [data-id="4:11"]').click();
      settle();
      return function () { report({ stillOpen: shown('bag'), current: window.FigApp.current }); };
    },
  };

  setTimeout(function () {
    var after = CASES[CASE]();
    setTimeout(after, 40);
  }, 260);
})();
