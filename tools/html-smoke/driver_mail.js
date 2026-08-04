// driver_mail.js — mail 示例的行为冒烟。盯的是 **v1.1 的 `@in:<modal>:<nodeId>` 真的能用**。
//
// mail 这份有两个住在弹窗里的按钮:详情里的「领取」(`@in:read:25:2568`)和已领取态里的
// 「删除」(`@in:claimed:31:1424`)。v1.0 表达不了它们 —— events 只能绑 base 屏,
// 只能拿"点哪都关 / 点面板外关"近似,而那是另一回事。
//
// 所以这两条断言要说明的是同一件事的两面:弹窗里的按钮**按得着、按下去有用**,
// 以及有用的是**这个按钮**而不是冒泡上去的 `@panelOutside`(按钮就在面板里,
// 冒泡上去反而不该触发)。
(function () {
  var CASE = parseInt((location.search.match(/case=(\d+)/) || [0, 0])[1], 10) || 0;
  var Q = function (id) { return document.querySelector('#layer-base [data-id="' + id + '"]'); };
  var IN = function (modal, id) {
    return document.querySelector('[data-modal="' + modal + '"] [data-id="' + id + '"]');
  };

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

  var MAIL = '25:1615';         // 列表第一行:带附件的邮件
  var CLAIM = '25:2568';        // @in:read:25:2568 —— 详情里的「领取」
  var DELETE = '31:1424';       // @in:claimed:31:1424 —— 已领取态里的「删除」
  var TITLE = '25:2567';        // 面板标题(非按钮),用作反向锚

  var CASES = {
    // ① 弹窗内的按钮(@in:)= v1.1 新增能力。这里连着按两个:
    //    领取(换态到 claimed)→ 删除(关掉)。两个都住在弹窗层里。
    0: function () {
      Q(MAIL).click();                         // 底屏行 → 开详情(SCALE_IN)
      settle();
      var opened = shown('read');
      var claimBtn = IN('read', CLAIM);
      var found = !!claimBtn;
      if (found) claimBtn.click();             // @in:read:… → 原地换成已领取态
      settle();
      return function () {
        // ⚠️ `settle()` 只结束**动画**,而换态/关闭把层藏起来那一步走的是
        //    `setTimeout(done, dur)` —— 一个**不受动画控制的定时器**。等它跑完再量,
        //    否则读到的是"动画播完了、层还在",看着像按钮根本没起作用。
        setTimeout(function () {
          var swapped = shown('claimed');
          var delBtn = IN('claimed', DELETE);
          if (delBtn) delBtn.click();          // @in:claimed:… → 关掉
          settle();
          setTimeout(function () {
            report({ opened: opened, closeButtonFound: found && !!delBtn,
                     swapped: swapped, stillOpen: shown('claimed'),
                     current: window.FigApp.current });
          }, 400);                             // 出场 180ms,留足余量
        }, 400);                               // 换态 180ms,同上
      };
    },

    // ② 反向锚:点面板**里**别的地方(标题)不该关 —— 否则上面那条也就没意义了,
    //    毕竟同一层上还挂着 @panelOutside:read。
    1: function () {
      Q(MAIL).click();
      settle();
      var t = IN('read', TITLE);
      if (t) t.click();
      settle();
      return function () {
        report({ anchorFound: !!t, stillOpen: shown('read'), current: window.FigApp.current });
      };
    },
  };

  setTimeout(function () {
    var after = CASES[CASE]();
    setTimeout(after, 40);
  }, 260);
})();
