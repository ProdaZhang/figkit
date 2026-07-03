// login.app.js — 登录示例的 app 专属 hook(域内语义),挂 window.APPHOOK。
// 引擎(assemble.js)管结构/机制;这里只管:服务器数据→行、选服回填、状态色、公告、默认选第一个。
// 协议名(enter/selectServer)为**示例协议**,接真后端时按项目契约替换。
(function () {
  const STATUS_COLOR = {
    1: 'rgba(139,193,45,1)', 2: 'rgba(6,192,150,1)', 3: 'rgba(166,44,56,1)',
    4: 'rgba(239,191,0,1)', 5: 'rgba(160,160,160,1)',
  };
  const ROW_BG_NORMAL = 'rgba(255,251,242,1)', ROW_BG_SELECT = 'rgba(223,197,140,1)';
  const INK_NORMAL = 'rgba(57,57,57,1)', INK_SELECT = 'rgba(255,251,242,1)', INK_OFF = 'rgba(219,208,184,1)';
  const SEL_T = '1:11', SEL_G = '1:12', NOTICE_T = '2:11', NOTICE_B = '2:12', LIST = '3:20';
  let SEL = { name: null, status: 0 };

  function $(layer, id) { return layer ? layer.querySelector('[data-id="' + id + '"]') : null; }
  function rowParts(row) {
    return {
      pill: row.querySelector('[data-name="pill"]'),
      text: row.querySelector('[data-name="row-name"]'),
      gem:  row.querySelector('[data-name="gem"]'),
    };
  }
  function msg(text, err) {
    const el = document.getElementById('boot-err');
    if (el) { el.textContent = text; el.style.color = err ? '#f99' : '#7fd'; clearTimeout(el._t); el._t = setTimeout(() => el.textContent = '', 3000); }
    else console.log('[msg]', text);
  }

  function renderList(app, servers) {
    app.renderRows('serverlist', LIST, servers, (row, srv) => {
      const isM = srv.status === 5, isS = app.state.selected === srv.id, p = rowParts(row);
      row.dataset.serverId = srv.id; row.dataset.status = srv.status;
      row.style.cursor = isM ? 'not-allowed' : 'pointer';
      if (p.gem)  p.gem.style.background  = isM ? STATUS_COLOR[5] : (STATUS_COLOR[srv.status] || STATUS_COLOR[5]);
      if (p.pill) p.pill.style.background = isM ? 'transparent' : (isS ? ROW_BG_SELECT : ROW_BG_NORMAL);
      if (p.text) { p.text.textContent = srv.name; p.text.style.color = isM ? INK_OFF : (isS ? INK_SELECT : INK_NORMAL); }
    });
  }
  function fillNotice(app, n) {
    if (!n) return;
    const L = app.layers.notice;
    const T = $(L, NOTICE_T), B = $(L, NOTICE_B);
    if (T) T.textContent = n.title || '';
    if (B) B.textContent = n.body || '';
  }
  function fillSel(app) {
    const base = app.layers.base;
    const t = $(base, SEL_T); if (t) t.textContent = SEL.name || '未选择';
    const g = $(base, SEL_G); if (g && SEL.status) g.style.background = STATUS_COLOR[SEL.status] || STATUS_COLOR[5];
  }

  window.APPHOOK = {
    register(app) {
      app.registerActions({
        // 开始游戏(guard 已在引擎判过 agreed&selected)
        send: async (type) => {
          if (type !== 'Enter') return;
          const r = await app.net.send({ type: 'enter', serverId: app.state.selected, agreed: true });
          msg(r.err === 0 ? ('进入成功 token=' + (r.sessionToken || '')) : ('进入失败 err=' + r.err), r.err !== 0);
        },
        // 选服:维护中拦截、否则发 selectServer、回填底屏已选服条、关弹窗
        selectServer: async (row) => {
          const status = Number(row.dataset.status);
          if (status === 5) { msg('该服务器维护中，暂不可进入', true); return; }
          const id = Number(row.dataset.serverId);
          const r = await app.net.send({ type: 'selectServer', serverId: id });
          if (r.err === 0) {
            app.state.selected = id;
            const t = row.querySelector('[data-name="row-name"]');
            SEL = { name: t ? t.textContent : ('服务器' + id), status: status };
            fillSel(app); renderList(app, app._servers); app.closeModal();
            msg('已选择：' + SEL.name, false);
          } else msg('选服失败 err=' + r.err, true);
        },
        syncBindings: () => fillSel(app),
        onPush: (m) => { if (m.servers) { app._servers = m.servers; renderList(app, m.servers); } if (m.notice) fillNotice(app, m.notice); },
        onGuardFail: () => { if (!app.state.agreed) msg('请先勾选同意协议', true); else if (!app.state.selected) msg('请先选择服务器', true); },
      });
    },
    init(app) {
      const M = (typeof MOCK !== 'undefined') ? MOCK : { servers: [], notice: null };
      const boot = { err: 0, servers: M.servers || [], notice: M.notice || null };
      app._servers = boot.servers;
      renderList(app, boot.servers);
      fillNotice(app, boot.notice);
      if (!app.state.selected && boot.servers.length) {   // 首次默认选第一个
        const f = boot.servers[0];
        app.state.selected = f.id; SEL = { name: f.name, status: f.status };
        fillSel(app); renderList(app, boot.servers);
      }
      app.syncBindings();
    },
  };
})();
