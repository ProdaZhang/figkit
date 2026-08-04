// app.js — 邮箱原型的域内 hook。
//
// 引擎(assemble.js)只管结构与机制:底屏 / 弹窗叠加 / 事件 / 转场 / 按压。
// 这里只放两类东西:
//   1) flow.json 里 do:"claim" 指向的域内动作;
//   2) 视觉修正 —— 分两种,**必须分清楚,别混成一坨"调样式"**:
//      · 【捕获缺陷绕行】figma 里是对的、figkit capture 没还原出来 → 见 patchCaptureGaps()
//      · 【设计修正】figma 里就画错了、用户当面指出要改 → 见 fixPlainButton()
//      前者将来 figkit 修好就该删掉;后者要等设计改了 figma 才能删。

(function () {
  'use strict';

  // ── 视觉修正 1:捕获缺陷绕行 ───────────────────────────────────────────────
  // 三条都已核到根因(拿 figma 自己渲染的 PNG 当地面真值比对出来的),
  // 都是 figma_capture.py 的通用缺陷,不是本项目特例。

  // (a) 定宽文本不换行 —— **已在 figkit 修好,这里不再绕行**。
  //     capture 现在读 figma 的 style.textAutoResize 并落成 IR v1.3 的 `text.wrap`
  //     (NONE / HEIGHT = 宽度固定 → 折行;WIDTH_AND_HEIGHT = 随字撑宽 → 不折)。
  //     以前靠"盒子比一行高就当它要折"来猜,html 侧猜得到、引擎侧没有等价 hook,
  //     于是同一份 IR 在 Godot 里正文照样冲出面板。真源在 capture,绕行留着只会
  //     掩盖捕获层到底修没修好。

  // (b) 文字竖直锚点 —— **已在 figkit 修好,这里不再绕行**。
  //     以前靠"行高大于盒高就把行高压成盒高再居中"来猜。现在 capture 在 IR 里就把
  //     单行文本的盒子归一成了**行盒**(y 落到行块位置、h = lineHeight、alignV=center),
  //     三端只要"在盒子里居中"就精确一致 —— godot/unity 没有 line-height,
  //     绕行留在 html 侧只会让引擎侧继续错下去(实测 godot 低 12px、unity 高 8.5px)。

  // (c) 遮罩 —— **已在 figkit 修好,这里不再绕行**。
  //     道具底框那组里 'Rectangle 203' 带 isMask:true(60px 圆角),负责把兄弟节点
  //     'Decorator'(品质渐变)裁成圆角。capture 以前不认 isMask,遮罩被当普通图层画出来、
  //     Decorator 原样方角盖上去 → 道具成了红方块。现在 capture 把它折成父级的
  //     clip + radius(IR v1.1 的 `clip` 字段),渲染层自然就是圆的。
  //     这条绕行删掉不是因为不重要,是因为**留着会掩盖捕获层到底修没修好**。

  function patchCaptureGaps(_layer) {
    // 三条捕获缺陷都已在 figkit 修好,这里现在是空的 —— 留着函数是为了下一条有地方放。
  }

  // ── 视觉修正 2:设计修正 ─────────────────────────────────────────────────
  // 第四个界面(无附件邮件)在 figma 里放的是黄色「领取」按钮 —— 无附件邮件没东西可领,
  // 这里的动作就是删除。改成第三个界面那颗绿色按钮:底色、纹理贴图、文案、尺寸
  // 全部照抄 31:1424(已领取态的「删除」),数值取自 screen-readclaimed.ui.json。
  // 按钮纹理**不是贴图,是矢量**(那圈半调网点是 BOOLEAN_OPERATION,render.js 画成内联 svg)。
  // 换色就得改 path 的 fill —— 早先这里给裁剪框贴了张 backgroundImage,
  // 图根本不存在(404),而里面的黄色网点子节点原封不动还在:
  // 于是绿按钮外面糊了一圈黄网点。**贴图换不掉矢量子节点。**
  var GREEN_BTN = {
    fill: 'rgba(6,192,150,1.0)',        // 底色矩形(对 31:1424 的 135:12219)
    edge: 'rgba(4,173,118,1.0)',        // 同一个矩形的 7px 内描边 —— 换底色不换它就剩一圈黄边
    dots: 'rgba(6,186,145,1.0)',        // 半调网点(对 135:12221)
    btnW: 363, rectW: 363, texW: 349, textW: 269.8, textLeft: 46, label: '删除'
  };

  function repaintVector(el, fill) {
    if (el) el.querySelectorAll('path').forEach(function (p) { p.setAttribute('fill', fill); });
  }

  function fixPlainButton(layer) {
    var btn = layer.querySelector('[data-id="245:1844"]');
    if (!btn) { console.warn('[app] 第四界面按钮未找到,绿色删除按钮修正没生效'); return; }
    var rect = btn.querySelector('[data-id="I245:1844;135:9615"]');
    var tex = btn.querySelector('[data-id="I245:1844;553:9718"]');
    var dots = btn.querySelector('[data-id="I245:1844;135:9617"]');
    var txt = btn.querySelector('[data-id="I245:1844;135:9984"]');
    btn.style.width = GREEN_BTN.btnW + 'px';
    if (rect) {
      rect.style.background = GREEN_BTN.fill;
      rect.style.borderColor = GREEN_BTN.edge;
      rect.style.width = GREEN_BTN.rectW + 'px';
    }
    if (tex) tex.style.width = GREEN_BTN.texW + 'px';
    repaintVector(dots, GREEN_BTN.dots);
    if (txt) { txt.textContent = GREEN_BTN.label; txt.style.width = GREEN_BTN.textW + 'px'; txt.style.left = GREEN_BTN.textLeft + 'px'; }
  }

  // 三个阅读面板在 figma 里的 y 不一致:带附件那帧是 288,另外两帧是 297。
  // 「领取」是原地换态(同一封邮件),9px 的跳动读起来像 bug 而不像设计,
  // 所以对齐到多数派 297。这条也是设计侧该顺手统一的。
  var PANEL_TOP = 297;
  function alignPanel(layer, panelId) {
    var p = layer.querySelector('[data-id="' + panelId + '"]');
    if (p) p.style.top = PANEL_TOP + 'px';
  }

  window.APPHOOK = {
    register: function (app) {
      app.registerActions({
        // 领取 → 原地换成「已领取」那一态(水印 + 绿色删除按钮)。
        // 引擎的 openModal 会先关掉当前弹窗再开新的,配 flow 里声明的 DISSOLVE,
        // 读起来就是同一个面板在换内容,而不是"关一个再开一个"。
        // 自定义 action 拿到的是 (ev, e),转场声明在 ev.transition 上,要自己传下去。
        claim: function (ev) {
          app.openModal('claimed', ev.transition);
        },

        // build() 结束后跑一次。三个弹窗层此时都已渲染好(引擎是一次性全建、按需显隐),
        // 所以这里能一把补完所有层,不用等弹窗第一次打开。
        onReady: function () {
          Object.keys(app.layers).forEach(function (name) {
            patchCaptureGaps(app.layers[name]);
          });
          if (app.layers.plain) fixPlainButton(app.layers.plain);
          if (app.layers.read) alignPanel(app.layers.read, '25:4193');
          if (app.layers.claimed) alignPanel(app.layers.claimed, '31:1382');
          if (app.layers.plain) alignPanel(app.layers.plain, '245:1802');
        }
      });
    }
  };
})();
