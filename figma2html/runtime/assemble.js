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

    // ── 弹窗显隐(底屏常驻)──
    openModal(name) {
      Object.keys(this.modals).forEach(k => this.modals[k].el.style.display = 'none');
      if (this.modals[name]) this.modals[name].el.style.display = '';
      this.current = name;
    },
    closeModal() {
      Object.keys(this.modals).forEach(k => this.modals[k].el.style.display = 'none');
      this.current = null;
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
        if (this.actions.onGuardFail) this.actions.onGuardFail(ev);
        return;
      }
      switch (ev.do) {
        case 'openModal':  this.openModal(ev.arg); break;
        case 'closeModal': this.closeModal(); break;
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
      items.forEach((item, idx) => {
        const row = tpl.cloneNode(true);
        row.style.top = (baseTop + idx * step) + 'px';
        row.dataset.row = '1';
        rowFn(row, item, idx);
        list.appendChild(row);
      });
    },
  };
  window.FigApp = APP;
})();
