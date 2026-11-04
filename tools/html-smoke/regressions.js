// Real-browser regressions: geometry and interaction, not source-string assertions.
(async function () {
  const results = [], warnings = [], cases = [];
  console.warn = (...args) => warnings.push(args.join(' '));
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const test = (name, fn) => cases.push([name, fn]);
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  // Virtual timers do not advance Chrome's compositor clock. Finish real CSS
  // transitions before measuring their resting geometry (same as driver_login).
  const settle = () => document.getAnimations().forEach(a => { try { a.finish(); } catch (_) {} });
  const rec = (id, parent, x, y, w, h, extra = {}) => ({id, parent, x, y, w, h, z:1, opacity:1, fill:'#888', ...extra});
  const cap = els => ({spec:'1.6', w:400, h:400, stageBg:'#fff', els});
  const box = el => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; };
  const sameBox = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < .1);
  function build(flow, caps) {
    document.body.innerHTML = '<div id="stage"><div id="layer-base" class="screen-layer"></div><div id="modal-layers"></div></div>';
    Object.assign(FigApp, {modals:{}, layers:{}, actions:{}, current:null});
    FigApp.build({stage:{w:400, h:400}, caps:{base:'base.ui.json', m:'m.ui.json'}, base:'base', ...flow}, caps, null);
  }
  const matrixButton = () => rec('button', '', 120, 80, 40, 20, {matrix:[0,1,-1,0,140,80]});
  test('press_restores_matrix_and_legacy_rotation', () => {
    for (const button of [matrixButton(), rec('button', '', 120,80,40,20,{rot:30})]) {
      build({events:[{el:'button', on:'click', do:'toggleFlag', arg:'x'}],
        motion:{press:{duration:0, scale:.96, easing:{type:'LINEAR'}}}}, {base:cap([button])});
      const el = FigApp.baseEl('button'), before = box(el), transform = el.style.transform;
      for (const end of ['pointerup', 'pointercancel', 'pointerleave']) {
        el.dispatchEvent(new Event('pointerdown'));
        check(el.style.transform.includes(transform), 'press replaced the base transform');
        const pressed = box(el);
        check(Math.abs(pressed[0] + pressed[2]/2 - before[0] - before[2]/2) < .1 &&
          Math.abs(pressed[1] + pressed[3]/2 - before[1] - before[3]/2) < .1, 'press moved the element centre');
        el.dispatchEvent(new Event(end));
        check(el.style.transform === transform && sameBox(before, box(el)), end + ' lost geometry');
      }
    }
  });
  test('modal_keeps_matrix_with_and_without_animation', async () => {
    for (const transition of [null, {type:'MOVE_IN', direction:'BOTTOM', duration:10, easing:{type:'LINEAR'}}]) {
      build({modals:{m:{cap:'m', roots:['panel'], panel:'panel'}}},
        {base:cap([]), m:cap([rec('panel','',120,80,80,50,{matrix:[0,1,-1,0,170,80]})])});
      const panel = FigApp._panelOf('m'), transform = panel.style.transform;
      FigApp.modals.m.el.style.display = '';
      const before = box(panel);
      FigApp.openModal('m', transition); await sleep(35); settle();
      check(panel.style.transform === transform && sameBox(before, box(panel)), 'open lost matrix ' + JSON.stringify({transition, before, after:box(panel), transform:panel.style.transform, computed:getComputedStyle(panel).transform}));
      FigApp.closeModal(transition); await sleep(35); settle();
      FigApp.openModal('m');
      check(sameBox(before, box(panel)), 'reopen lost matrix');
    }
  });
  function listBuild(matrix = false, stagger = false) {
    build({modals:{m:{cap:'m', roots:['list'], panel:'list'}}, list:{modal:'m', container:'list', onRowClick:'select'},
      motion:stagger ? {stagger:{duration:10, step:5, from:24, easing:{type:'LINEAR'}}} : {}},
      {base:cap([]), m:cap([
        rec('list','',100,100,160,180,matrix ? {matrix:[0,1,-1,0,280,100]} : {}),
        rec('r0','list',110,110,100,20,matrix ? {matrix:[0,1,-1,0,270,110]} : {}),
        rec('r1','list',110,140,100,20,matrix ? {matrix:[0,1,-1,0,240,110]} : {})])});
    FigApp.modals.m.el.style.display = '';
  }
  const rows = () => [...FigApp.layers.m.querySelectorAll('[data-row]')];
  const render = items => FigApp.renderRows('m','list',items,(row,item) => { row.textContent = String(item); });
  test('empty_list_recovers_and_keeps_original_spacing', () => {
    listBuild(); render([]); render([1]); render([1,2,3]);
    check(rows().length === 3, 'empty list destroyed template');
    check(rows().map(e => e.style.top).join() === '10px,40px,70px', 'one result lost original spacing');
    check(rows().map(e => e.textContent).join() === '1,2,3', 'row data not refreshed');
    render([]); render([4,5]);
    check(rows().length === 2 && rows()[1].style.top === '40px', 'second empty cycle failed');
  });
  test('matrix_rows_are_distinct_even_with_stagger', async () => {
    for (const stagger of [false, true]) {
      listBuild(true, stagger);
      const initial = [...FigApp.layers.m.querySelectorAll('[data-parent="list"]')].map(box);
      render([1,2,3]); await sleep(50); settle();
      const actual = rows().map(box);
      check(actual.length === 3 && sameBox(initial[0], actual[0]) && sameBox(initial[1], actual[1]), 'matrix row positions changed ' + JSON.stringify({stagger,initial,actual,styles:rows().map(e=>[e.style.top,e.style.transform,getComputedStyle(e).transform])}));
      check(Math.abs(actual[2][0] - actual[1][0]) > 1, 'matrix rows overlap');
      render([]); render([4,5]); await sleep(50); settle();
      check(sameBox(initial[1], box(rows()[1])), 'matrix row spacing lost after clear');
    }
  });
  test('unicode_modal_selectors_close_the_correct_modal', () => {
    for (const kind of ['any', 'panelOutside']) {
      const name = '公告-详情';
      build({modals:{[name]:{cap:'m', roots:['panel'], panel:'panel'}}, events:[{el:'@'+kind+':'+name,on:'click',do:'closeModal'}]},
        {base:cap([]),m:cap([rec('panel','',10,10,80,50)])});
      FigApp.openModal(name);
      if (kind === 'panelOutside') {
        FigApp._panelOf(name).dispatchEvent(new MouseEvent('click',{bubbles:true}));
        check(FigApp.current === name, 'panel click closed modal');
      }
      FigApp.layers[name].dispatchEvent(new MouseEvent('click',{bubbles:true}));
      check(FigApp.current === null, 'Unicode selector was not bound');
    }
  });
  test('invalid_modal_target_warns_and_preserves_current_modal', () => {
    build({modals:{m:{cap:'m',roots:['panel'],panel:'panel'}}}, {base:cap([]),m:cap([rec('panel','',10,10,80,50)])});
    FigApp.openModal('m'); const n = warnings.length;
    for (const target of ['nonexistent-modal', 'toString', '__proto__', null]) {
      FigApp.openModal(target);
      check(FigApp.current === 'm' && FigApp.layers.m.style.display !== 'none', 'bad target hid current modal');
    }
    check(warnings.length > n, 'bad target was silent');
  });
  test('image_paint_alpha_does_not_fade_children_or_node', () => {
    for (const alpha of [0, .25, 1]) {
      const base = cap([rec('image','',0,0,100,100,{img:'test.png',imgOpacity:alpha,opacity:.6}),rec('child','image',0,0,20,20)]);
      base.stageBg = 'url(test.png) center/cover no-repeat'; base.stageBgOpacity = alpha;
      build({}, {base});
      const el = FigApp.baseEl('image'), child = FigApp.baseEl('child');
      check(getComputedStyle(el).opacity === '0.6' && getComputedStyle(child).opacity === '1', 'paint alpha affected the subtree');
      const paint = el.querySelector('[data-fig-paint]');
      check(alpha === 1 ? !paint : paint && Number(getComputedStyle(paint).opacity) === alpha, 'paint alpha missing');
      check(getComputedStyle(FigApp.layers.base).opacity === '1', 'stage paint faded the whole screen');
      if (alpha !== 1) check(Number(FigApp.layers.base.querySelector('[data-fig-paint]').style.opacity) === alpha, 'stage paint alpha missing');
    }
  });
  for (const [name, fn] of cases) {
    try { await fn(); results.push({name, passed:true}); }
    catch (error) { results.push({name, passed:false, error:String(error)}); }
  }
  document.title = 'FIGKIT-SMOKE ' + JSON.stringify({results});
})();
