// assemble.js — 通用组装引擎:flow(声明) + caps(.ui.json) → 可跑客户端
// 架构 = 底屏 + 弹窗叠加(非 swap):底部 UI 只一份,状态唯一不串。
// 声明驱动:flow.base / flow.modals / flow.events / flow.list / flow.bindings。
// 依赖 render.js 的 renderScreen / subtreeOf / mountStage。
// 域内专属逻辑(列表行渲染、选服、回填…)由 app 通过 FigApp.action()/rowHook() 注册,引擎不写死。
//
// flow 事件 action 内置:openModal(arg) / closeModal / toggleFlag(arg) / send(arg)
//   其余 do 名 → 查 app 注册的 action。
// 事件元素选择器:figma node id(底屏元素)/ 特殊 "@any:<modal>"、"@panelOutside:<modal>"。

(function () {
  const APP = {
    flow: null, caps: null, net: null,
    layers: {},      // name -> layer 元素(base + 各 modal)
    modals: {},      // name -> { el, panel }
    state: {},       // 标志/值
    actions: {},     // do 名 -> async fn(ev,e)
    current: null,

    registerAction(name, fn) { this.actions[name] = fn; return this; },
    registerActions(map) { Object.assign(this.actions, map); return this; },

    $(layer, id) { return layer ? layer.querySelector('[data-id="' + id + '"]') : null; },
    baseEl(id) { return this.$(this.layers.base, id); },

    // ── 构建 ──
    build(flow, caps, net) {
      this.flow = flow; this.caps = caps; this.net = net;
      this.state = Object.assign({}, flow.state || {});
      const w = (flow.stage && flow.stage.w) || 1080, h = (flow.stage && flow.stage.h) || 1920;
      mountStage(document.getElementById('stage'), w, h);

      // 底屏
      this.layers.base = document.getElementById('layer-base');
      if (caps[flow.base]) renderScreen(caps[flow.base], this.layers.base);

      // 弹窗 = 抽面板子树叠加 + 半透明遮罩
      const wrap = document.getElementById('modal-layers');
      Object.keys(flow.modals || {}).forEach((name, i) => {
        const m = flow.modals[name];
        const layer = document.createElement('div');
        layer.className = 'screen-layer'; layer.style.display = 'none'; layer.style.zIndex = String(50 + i);
        layer.dataset.modal = name;
        wrap.appendChild(layer);
        const bd = document.createElement('div');
        bd.dataset.backdrop = '1';
        Object.assign(bd.style, { position: 'absolute', left: '0', top: '0', width: w + 'px', height: h + 'px', background: 'rgba(0,0,0,0.5)', zIndex: '0' });
        layer.appendChild(bd);
        if (caps[m.cap]) renderScreen(subtreeOf(caps[m.cap], m.roots), layer);
        this.layers[name] = layer;
        this.modals[name] = { el: layer, panel: m.panel };
      });

      this.wireEvents();
      this.syncBindings();
      if (this.actions.onReady) this.actions.onReady();
      document.body.dataset.rendered = '1';
    },

    // ── 转场(flow.events[].transition,来自 figma 原型)──
    // 浏览器原生就有 cubic-bezier,所以这里**把 figma 的四个控制点原样喂给 CSS**,
    // 不映射到 ease/ease-in-out 之流的关键字 —— 同名不同形,一映射手感就变了。
    // 表达不了的(弹簧、SMART_ANIMATE、figma 没公开控制点的具名曲线)一律 warn 后瞬时显示:
    // **说出来的降级**,不是静默丢失。
    easeCss(ez) {
      ez = ez || {};
      if (Array.isArray(ez.bezier) && ez.bezier.length === 4) return 'cubic-bezier(' + ez.bezier.join(',') + ')';
      if (ez.spring) { console.warn('[assemble][known-loss] 弹簧缓动 CSS 表达不了,瞬时:', ez.spring); return null; }
      // 注意:这里查的是 **figma/CSS 的具名缓动**(EASE_OUT = (0,0,.58,1))。
      // 预设里那条 `ease-out` 是另一条曲线 (.23,1,.32,1),它走上面的 bezier 分支。
      // 两者形状差近 20 个百分点,绝不能互相顶替。
      const css = { LINEAR: 'linear', EASE_IN: 'ease-in', EASE_OUT: 'ease-out',
                    EASE_IN_AND_OUT: 'ease-in-out' }[ez.type];
      if (!css) console.warn('[assemble][known-loss] 未知缓动,瞬时:', ez.type);
      return css || null;
    },

    // tr → { dur, ease, from:{transform, opacity} }(from = 动画的**起点**;出场则是终点)
    transitionCss(tr) {
      if (!tr) return null;
      const dur = Math.max(0, Number(tr.duration) || 0);
      const ease = this.easeCss(tr.easing);
      if (!dur || !ease) return null;
      const off = { LEFT: ['-100%', '0'], RIGHT: ['100%', '0'],
                    TOP: ['0', '-100%'], BOTTOM: ['0', '100%'] }[tr.direction] || null;
      const at = (t) => ({ transform: t, opacity: '0' });
      switch (tr.type) {
        case 'DISSOLVE':   return { dur, ease, from: at('') };
        case 'SCALE_IN':   return { dur, ease, from: at('scale(' + (tr.fromScale || 0.95) + ')') };
        case 'SCALE_OUT':  return { dur, ease, from: at('scale(' + (tr.toScale || 0.95) + ')') };
        case 'MOVE_IN': case 'SLIDE_IN':
        case 'MOVE_OUT': case 'SLIDE_OUT':
          if (off) return { dur, ease, from: at('translate(' + off[0] + ',' + off[1] + ')') };
          break;
        default: break;
      }
      console.warn('[assemble][known-loss] 转场类型', tr.type, '未实现,退化成淡入');
      return { dur, ease, from: at('') };
    },

    // 复位到起点 → 强制生效 → 放开。中间那次读 offsetWidth **不能省**:
    // 元素身上挂着 transition 时,移除终态不会瞬间跳回起点,而是平滑退回去;
    // 下一帧再加回来,它才退了约 6%,肉眼完全看不出动过。这不是 bug,是可打断性的代价。
    _play(el, t, to, done) {
      el.style.transition = 'none';
      el.style.transform = t.from.transform;
      el.style.opacity = t.from.opacity;
      void el.offsetWidth;
      el.style.transition = 'opacity ' + t.dur + 'ms ' + t.ease + ', transform ' + t.dur + 'ms ' + t.ease;
      el.style.transform = to.transform;
      el.style.opacity = to.opacity;
      if (done) setTimeout(done, t.dur);
    },

    // ── 弹窗显隐(底屏常驻)──
    _hideAll() { Object.keys(this.modals).forEach(k => this.modals[k].el.style.display = 'none'); },

    openModal(name, transition) {
      this._hideAll();
      const m = this.modals[name];
      if (m) {
        const el = m.el, t = this.transitionCss(transition);
        el.style.display = '';
        if (t) this._play(el, t, { transform: '', opacity: '1' });
        else { el.style.transition = ''; el.style.opacity = ''; el.style.transform = ''; }
      }
      this.current = name;
    },

    // **有入场必有出场。** 只做入场 = 消失时硬闪,而开合不对称到刺眼。
    // 出场用的时长来自 flow(figma 声明的,或预设补的 dur-exit —— 后者比入场快,这是有意的:
    // 对称的开合读起来比实际慢)。没有转场声明就保持瞬时,不自作主张。
    closeModal(transition) {
      const cur = this.current, m = cur && this.modals[cur];
      const t = m ? this.transitionCss(transition) : null;
      this.current = null;
      if (!t) { this._hideAll(); return; }
      const el = m.el;
      el.style.transition = 'none';
      el.style.transform = ''; el.style.opacity = '1';
      void el.offsetWidth;
      el.style.transition = 'opacity ' + t.dur + 'ms ' + t.ease + ', transform ' + t.dur + 'ms ' + t.ease;
      el.style.transform = t.from.transform;
      el.style.opacity = t.from.opacity;
      setTimeout(() => {
        // 期间又开了别的弹窗就别抢着藏(快速连点会撞上)
        if (this.current === null) { this._hideAll(); el.style.transition = ''; el.style.transform = ''; el.style.opacity = ''; }
      }, t.dur);
    },

    // ── 默认动效:按压 / 逐项入场 / guard 失败(flow.motion,来源见其 source 字段)──
    motionOf(k) { return (this.flow && this.flow.motion && this.flow.motion[k]) || null; },

    // 可点元素没有按下态是**缺陷不是风格**:点下去毫无反应,玩家读到的是"卡了"。
    wirePress(el) {
      const p = this.motionOf('press');
      if (!p) return;
      const ease = this.easeCss(p.easing) || 'ease-out';
      const set = s => { el.style.transition = 'transform ' + p.duration + 'ms ' + ease; el.style.transform = s; };
      el.addEventListener('pointerdown', () => set('scale(' + (p.scale || 0.96) + ')'));
      ['pointerup', 'pointercancel', 'pointerleave'].forEach(e => el.addEventListener(e, () => set('')));
    },

    // 一个元素说「错了」。用 WAAPI 而不是 transition:抖动是**一次性、播完即弃**的,
    // 而 transition 被快速重复触发时要先关掉才能重放(见 _play 的注释);
    // WAAPI 的 animate() 每次都是新动画,没有这个坑。
    wiggle(el) {
      const g = this.motionOf('guardFail');
      if (!g || !el || !el.animate) return;
      const a = g.amp || 6;
      el.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(' + -a + 'px)' },
                  { transform: 'translateX(' + a + 'px)' }, { transform: 'translateX(0)' }],
                 { duration: g.duration || 120, easing: 'ease-in-out' });
    },

    // ── 状态 ──
    setFlag(name, val) { this.state[name] = val; this.syncBindings(); },
    setValue(name, val) { this.state[name] = val; this.syncBindings(); },
    guardOk(guards) {
      return (guards || []).every(g => {
        const v = this.state[g];
        return v !== null && v !== undefined && v !== false && v !== 0 && v !== '';
      });
    },

    // ── 事件接线 ──
    wireEvents() {
      const self = this;
      (this.flow.events || []).forEach(ev => {
        const sels = Array.isArray(ev.el) ? ev.el : [ev.el];
        sels.forEach(sel => {
          const sp = String(sel).match(/^@(\w+):(\w+)$/);   // @any:modal / @panelOutside:modal
          if (sp) {
            const kind = sp[1], modal = sp[2], layer = self.layers[modal];
            if (!layer) return;
            layer.addEventListener('click', e => {
              if (kind === 'any') { self.dispatch(ev, e); return; }
              if (kind === 'panelOutside') {
                const p = self.$(layer, self.modals[modal].panel);
                if (!p || !p.contains(e.target)) self.dispatch(ev, e);
              }
            });
            return;
          }
          const el = self.baseEl(sel);
          if (!el) { console.warn('[assemble] 事件元素未找到:', sel); return; }
          el.style.cursor = 'pointer';
          self.wirePress(el);
          el.addEventListener('click', e => { e.stopPropagation(); self.dispatch(ev, e); });
        });
      });

      // 列表行点击委托(app 用 FigApp.renderRows 注入带 data-row 的行)
      const L = this.flow.list;
      if (L && this.layers[L.modal]) {
        this.layers[L.modal].addEventListener('click', async e => {
          const row = e.target.closest('[data-row]');
          if (row && self.actions[L.onRowClick]) await self.actions[L.onRowClick](row, e);
        });
      }
      if (this.net && this.net.onPush && this.actions.onPush) this.net.onPush(m => self.actions.onPush(m));
    },

    async dispatch(ev, e) {
      if (ev.guard && !this.guardOk(ev.guard)) {
        // 以前这里是**彻底的沉默** —— 协议没勾就点"开始游戏",界面毫无反应。
        // onGuardFail 这个 hook 一直在,只是没人给它默认行为。
        this.wiggle(e && e.currentTarget);
        if (this.actions.onGuardFail) this.actions.onGuardFail(ev);
        return;
      }
      switch (ev.do) {
        case 'openModal':  this.openModal(ev.arg, ev.transition); break;
        case 'closeModal': this.closeModal(ev.transition); break;
        case 'toggleFlag': this.setFlag(ev.arg, !this.state[ev.arg]); break;
        case 'send':       if (this.actions.send) await this.actions.send(ev.arg, ev); break;
        default:           if (this.actions[ev.do]) await this.actions[ev.do](ev, e);
                           else console.warn('[assemble] 未知 action:', ev.do);
      }
    },

    // ── 通用绑定:checkbox(flag→白底/半透+勾)。其余字段由 app 的 syncBindings hook 管 ──
    syncBindings() {
      const b = this.flow.bindings || {}, base = this.layers.base;
      if (b.checkbox && base) {
        const c = b.checkbox, box = this.$(base, c.el);
        if (box) {
          const on = !!this.state[c.flag];
          box.style.display = 'flex'; box.style.justifyContent = 'center'; box.style.alignItems = 'center';
          box.style.background = on ? (c.checkedBg || 'rgba(255,255,255,1)') : (c.uncheckedBg || 'rgba(255,255,255,0.2)');
          box.style.color = c.markColor || 'rgba(27,76,87,1)';
          box.style.fontSize = '24px'; box.style.fontWeight = '900'; box.style.lineHeight = '1';
          box.textContent = on ? (c.mark || '✓') : '';
        }
      }
      if (this.actions.syncBindings) this.actions.syncBindings(base);
    },

    // ── 列表渲染助手:克隆容器内首行为模板,逐项 rowFn 填充并打 data-row ──
    renderRows(modalName, containerId, items, rowFn) {
      const layer = this.layers[modalName];
      if (!layer) return;
      const list = this.$(layer, containerId);
      if (!list) { console.warn('[assemble] 列表容器未找到:', containerId); return; }
      list.style.overflowY = 'auto'; list.style.overflowX = 'hidden';
      const rows = Array.prototype.slice.call(list.querySelectorAll('[data-parent="' + containerId + '"]'));
      if (!rows.length) { console.warn('[assemble] 无模板行'); return; }
      const tpl = rows[0].cloneNode(true);
      const baseTop = parseFloat(rows[0].style.top) || 0;
      const step = rows.length > 1 ? (parseFloat(rows[1].style.top) - baseTop) : (parseFloat(rows[0].style.height) || 104);
      rows.forEach(r => r.remove());
      // 逐项入场:全部同时出现 = 一整块东西闪进来,量感全无;错开一点才读得出"有几条"。
      // 间隔来自 flow.motion.stagger(figma 里没有这个概念,所以它必然是预设补的)。
      const st = this.motionOf('stagger');
      const ease = st ? (this.easeCss(st.easing) || 'ease-out') : null;
      items.forEach((item, idx) => {
        const row = tpl.cloneNode(true);
        row.style.top = (baseTop + idx * step) + 'px';
        row.dataset.row = '1';
        rowFn(row, item, idx);
        list.appendChild(row);
        if (!st) return;
        row.style.transition = 'none';
        row.style.opacity = '0';
        row.style.transform = 'translateY(' + (st.from || 24) + 'px)';
        void row.offsetWidth;
        setTimeout(() => {
          row.style.transition = 'opacity ' + st.duration + 'ms ' + ease +
                                 ', transform ' + st.duration + 'ms ' + ease;
          row.style.opacity = ''; row.style.transform = '';
        }, idx * (st.step || 45));
      });
    },
  };
  window.FigApp = APP;
})();
