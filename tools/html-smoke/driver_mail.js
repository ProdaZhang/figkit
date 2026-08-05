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

    // ③ 每段文字有没有溢出**设计稿量给它的那个盒子**。
    //    这条不是排版洁癖,是量尺的完整性:`tools/design-diff` 把误差拆成"文字内/文字外",
    //    文字那半靠 IR 里每个文字元素的盒子(外扩 4px)遮掉。字一旦长过盒子,溢出来的
    //    那截就落在"文字外"里,被当成几何误差报出来 —— 实测本示例译成英文后,正文多绕
    //    了一行,详情屏的"文字外"从 0.53 涨到 0.82,而渲染一个像素都没变。
    //    (量之前得把各层都亮出来:display:none 的层 scrollHeight 恒为 0,溢出无从谈起。)
    2: function () {
      document.querySelectorAll('[data-modal]').forEach(function (l) { l.style.display = 'block'; });
      var over = [], seen = 0;
      document.querySelectorAll('[data-id]').forEach(function (d) {
        var txt = false;
        d.childNodes.forEach(function (n) { if (n.nodeType === 3 && n.nodeValue.trim()) txt = true; });
        if (!txt) return;
        seen++;
        var dx = d.scrollWidth - d.clientWidth, dy = d.scrollHeight - d.clientHeight;
        if (dx > 0 || dy > 0) {
          over.push({ id: d.getAttribute('data-id'), dx: dx, dy: dy,
                      lh: parseFloat(getComputedStyle(d).lineHeight) || 0 });
        }
      });
      return function () { report({ over: over, seen: seen }); };
    },
  };

  setTimeout(function () {
    var after = CASES[CASE]();
    setTimeout(after, 40);
  }, 260);
})();
