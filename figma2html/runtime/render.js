// render.js v2 — 全保真 .ui.json (records) -> 嵌套 DOM
// 数据源:figma_capture.py 产的 <屏>.ui.json(每节点几何=相对帧的绝对px + 全部真样式)。
// 渲染:按 parent 嵌套,几何转成父相对;逐节点真样式
//       (radius/border/shadow/blur/opacity/rot/填充[纯色含透明/渐变/图片]/文字[含字形描边])。
// 不走 DSL、不折叠、不退 flat skin —— 与 figma 节点树一致。

// 注意:本函数(出运行时 DOM)与 scripts/figma_capture.py 的 rec_to_css(出 .tree.html 静态预览)
// 是**同一套贴样式映射**。改任一处样式逻辑务必同步另一处,否则"预览 ≠ 运行时"会悄悄漂移。
//
// 素材路径:IR 里的 `img` 是**相对 .ui.json 自己**的(capture 就是这么发的),所以页面在哪、
// 深几层,取决于 flow.caps 把 .ui.json 指到了哪里 —— `assetBase` 由调用方从那条路径推出来
// (见 assemble.js 的 assetBaseOf)。这里曾经写死过 '../../',那是**某一个工程**的目录深度
// 被固化进了共享运行时:换个布局(比如 app.html 与素材同级)整屏图片就 404,而且不报错、
// 只是"图没了",看着像设计如此。tree.html 那侧不用这套:它与素材同级,裸路径即可。
function nextFigSvgId() {
  window.__figkitSvgSequence = (window.__figkitSvgSequence || 0) + 1;
  return 'figsvg_' + window.__figkitSvgSequence;
}

// cloneNode copies SVG document IDs too. List clones must not share clip/mask/filter refs.
function namespaceSvgIds(root) {
  for (const svg of root.querySelectorAll('svg')) {
    const ids = new Map();
    for (const el of svg.querySelectorAll('[id]')) {
      const old = el.getAttribute('id'), id = nextFigSvgId();
      ids.set(old, id); el.setAttribute('id', id);
    }
    for (const el of [svg, ...svg.querySelectorAll('*')]) {
      for (const attr of Array.from(el.attributes)) {
        let value = attr.value;
        for (const [old, id] of ids) value = value.split('url(#' + old + ')').join('url(#' + id + ')');
        if (value !== attr.value) el.setAttribute(attr.name, value);
      }
    }
  }
}

function figMatrixMul(a, b) {
  return [a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],
          a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];
}
function figMatrixInverse(m) {
  const det=m[0]*m[3]-m[1]*m[2];
  if (Math.abs(det)<1e-10) throw new Error('Singular IR matrix');
  const a=m[3]/det,b=-m[1]/det,c=-m[2]/det,d=m[0]/det;
  return [a,b,c,d,-a*m[4]-c*m[5],-b*m[4]-d*m[5]];
}
function figRecMatrix(el) { return el.matrix || [1,0,0,1,el.x,el.y]; }

function applyRecStyle(el, div, assetBase) {
  const s = div.style;
  s.position  = 'absolute';
  s.boxSizing = 'border-box';
  if (el.rot && !el.matrix) { s.transform = 'rotate(' + el.rot + 'deg)'; s.transformOrigin = 'center center'; }
  if (el.opacity !== 1)  s.opacity = el.opacity;
  if (el.radius)         s.borderRadius = el.radius;
  if (el.clip)           s.overflow = 'hidden';   // figma 遮罩:capture 已把遮罩形状折进 radius,这里只管裁
  if (el.border)         s.border = el.border;
  if (el.shadow && !(el.paths && el.paths.length && el.vectorShadows)) s.boxShadow = el.shadow;
  if (el.blur)           s.filter = el.blur;

  const t = el.text;
  if (t) {
    div.textContent  = t.content;
    if (t.decoration && !t.runs) s.textDecorationLine = t.decoration;
    if (t.runs && t.runs.length) {
      div.textContent = '';
      const line = document.createElement('span');
      line.style.minWidth = '0'; line.style.maxWidth = '100%';
      for (const run of t.runs) {
        const span = document.createElement('span'); span.textContent = run.content;
        span.style.textDecorationLine = run.decoration || 'none';
        span.style.color = run.color; span.style.fontSize = run.size + 'px';
        span.style.fontWeight = run.weight; span.style.letterSpacing = run.ls + 'px';
        span.style.fontFamily = "'FigCJK','" + run.family + "',sans-serif";
        line.appendChild(span);
      }
      div.appendChild(line);
    }
    s.display        = 'flex';
    s.justifyContent = t.alignH;
    s.alignItems     = t.alignV;
    s.textAlign      = t.textAlign;
    s.color          = t.color;
    s.fontSize       = t.size + 'px';
    s.fontWeight     = t.weight;
    s.fontFamily     = "'FigCJK','" + t.family + "','Source Han Sans SC','Noto Sans SC','Microsoft YaHei',sans-serif";
    s.lineHeight     = t.lh ? (t.lh + 'px') : 'normal';
    if (t.ls)     s.letterSpacing = t.ls + 'px';
    if (t.stroke) { s.webkitTextStroke = t.stroke; s.paintOrder = 'stroke fill'; }
    // figma 说这段定宽(textAutoResize ≠ WIDTH_AND_HEIGHT)就折行;随字撑宽的不折,
    // 免得字体回退偏宽逼出假换行。t.wrap 缺失 = v1.3 之前的老产物,退回旧口径。
    s.whiteSpace = (t.wrap || t.content.indexOf('\n') >= 0) ? 'pre-wrap' : 'nowrap';
    s.overflow   = 'visible';
  } else if (el.paths && el.paths.length) {
    // 矢量按路径画,不是位图。与 figma_capture.py 的 svg_markup 同一套写法,改一处必同步。
    // preserveAspectRatio='none':路径坐标就是节点自身包围盒,不许 SVG 再等比缩放居中。
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', el.viewBox || ('0 0 ' + (el.w || 1) + ' ' + (el.h || 1)));
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.style.cssText = 'width:100%;height:100%;display:block;overflow:visible';
    // figma 的 strokeGeometry 是「预裁带」(骑在边线上、总宽 2w),要按 strokeAlign 裁:
    // inside 裁进形状内,outside 裁到形状外,裁完各剩 w。不裁就两边各多一倍。
    const uid = nextFigSvgId();
    const shape = el.paths.filter(function (q) { return !q.clip; })
                          .map(function (q) { return q.d; }).join(' ');
    const need = {};
    el.paths.forEach(function (q) { if (q.clip) need[q.clip] = 1; });
    if (need.inside || need.outside) {
      const defs = document.createElementNS(NS, 'defs');
      if (need.inside) {
        const cp = document.createElementNS(NS, 'clipPath');
        cp.setAttribute('id', 'cin_' + uid);
        const p = document.createElementNS(NS, 'path'); p.setAttribute('d', shape);
        cp.appendChild(p); defs.appendChild(cp);
      }
      if (need.outside) {
        const vb = (el.viewBox || ('0 0 ' + (el.w || 1) + ' ' + (el.h || 1))).split(/\s+/).map(Number);
        const mk = document.createElementNS(NS, 'mask');
        mk.setAttribute('id', 'cout_' + uid);
        const r = document.createElementNS(NS, 'rect');
        r.setAttribute('x', vb[0] - 64); r.setAttribute('y', vb[1] - 64);
        r.setAttribute('width', vb[2] + 128); r.setAttribute('height', vb[3] + 128);
        r.setAttribute('fill', '#fff');
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('d', shape); p.setAttribute('fill', '#000');
        mk.appendChild(r); mk.appendChild(p); defs.appendChild(mk);
      }
      svg.appendChild(defs);
    }
    let paintTarget = svg;
    if (el.vectorShadows && el.vectorShadows.length) {
      const make = (name, attrs, parent) => {
        const e = document.createElementNS(NS, name);
        for (const [key,value] of Object.entries(attrs)) e.setAttribute(key, value);
        parent.appendChild(e); return e;
      };
      const vb=(el.viewBox || ('0 0 '+el.w+' '+el.h)).split(/\s+/).map(Number);
      const pad=Math.max(...el.vectorShadows.map(e=>Math.max(Math.abs(e.x),Math.abs(e.y))+Math.abs(e.spread)+4*e.blur),1);
      const defs=make('defs',{},svg);
      const filter=make('filter',{id:'shadow_'+uid,filterUnits:'userSpaceOnUse',
        x:vb[0]-pad,y:vb[1]-pad,width:vb[2]+2*pad,height:vb[3]+2*pad,'color-interpolation-filters':'sRGB'},defs);
      el.vectorShadows.forEach((e,i)=>{
        let input='SourceAlpha';
        if(e.spread) { make('feMorphology',{in:input,operator:e.spread>0?'dilate':'erode',radius:Math.abs(e.spread),result:'spread'+i},filter); input='spread'+i; }
        make('feGaussianBlur',{in:input,stdDeviation:e.blur,result:'blur'+i},filter);
        make('feOffset',{in:'blur'+i,dx:e.x,dy:e.y,result:'offset'+i},filter);
        make('feFlood',{'flood-color':e.color,result:'color'+i},filter);
        make('feComposite',{in:'color'+i,in2:'offset'+i,operator:'in',result:'shadow'+i},filter);
      });
      const merge=make('feMerge',{},filter);
      for(let i=el.vectorShadows.length-1;i>=0;i--) make('feMergeNode',{in:'shadow'+i},merge);
      make('feMergeNode',{in:'SourceGraphic'},merge);
      paintTarget=make('g',{filter:'url(#shadow_'+uid+')'},svg);
    }
    el.paths.forEach(function (q) {
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', q.d);
      path.setAttribute('fill', q.fill);
      path.setAttribute('fill-rule', q.rule);
      if (q.clip === 'inside')       path.setAttribute('clip-path', 'url(#cin_' + uid + ')');
      else if (q.clip === 'outside') path.setAttribute('mask', 'url(#cout_' + uid + ')');
      paintTarget.appendChild(path);
    });
    div.appendChild(svg);
  } else if (el.img) {
    s.backgroundImage    = "url('" + (assetBase || '') + el.img + "')";
    s.backgroundSize     = el.imgSize || 'cover';
    // v1.4:figma 的裁剪填充(scaleMode STRETCH + imageTransform)把图放在格子里的
    // 某个位置、并不铺满,capture 已把它算成 px。缺这个字段的旧产物照旧居中。
    s.backgroundPosition = el.imgPos || 'center';
    s.backgroundRepeat   = 'no-repeat';
  } else if (el.fill) {
    s.background = el.fill;
  }
}

/**
 * 把一屏 cap(.ui.json)渲染到 mountEl。
 * @param {Object} cap     - { frame, w, h, stageBg, els:[...] }
 * @param {Element} mountEl - 目标层
 */
function renderScreen(cap, mountEl, assetBase) {
  const base = assetBase || '';
  const els = cap.els || [];
  const recById = new Map();
  const divById = new Map();
  for (const el of els) recById.set(el.id, el);

  // pass1：建 div + 贴样式
  for (const el of els) {
    const div = document.createElement('div');
    div.dataset.id     = el.id;
    div.dataset.parent = el.parent || '';
    div.dataset.type   = el.type;
    div.dataset.name   = el.name || '';
    applyRecStyle(el, div, base);
    divById.set(el.id, div);
  }

  // pass2：绝对几何 → 父相对，按 parent 嵌套挂载
  //
  // 父级带 INSIDE 描边时，绝对定位的子元素是从父级的**内边距盒**起算的，而 border
  // 恰好把内边距盒往里推了一整个描边宽 —— 于是父级只要有描边，整棵子树就被顶偏。
  // 实测返回按钮那圈 8px 描边把里面的箭头右下各推了 8px，而按钮本身分毫不差
  // （所以肉眼只会觉得"图标没对齐"，不会想到是描边）。这里减回去。
  // figma_capture.py 的 rec_to_css 有同一段补偿，改一处必同步。
  const insetOf = (rec) => {
    const m = /^\s*([\d.]+)px/.exec((rec && rec.border) || '');
    return m ? parseFloat(m[1]) : 0;
  };
  for (const el of els) {
    const div = divById.get(el.id);
    const p   = el.parent ? recById.get(el.parent) : null;
    const bi  = p ? insetOf(p) : 0;
    const px  = p ? p.x + bi : 0, py = p ? p.y + bi : 0;
    div.style.left   = (el.x - px) + 'px';
    div.style.top    = (el.y - py) + 'px';
    if (el.matrix || (p && p.matrix)) {
      const matrix = p ? figMatrixMul(figMatrixInverse(figRecMatrix(p)),figRecMatrix(el)) : figRecMatrix(el).slice();
      matrix[4] -= bi; matrix[5] -= bi;
      div.style.left = '0px'; div.style.top = '0px';
      div.style.transformOrigin = '0 0';
      div.style.transform = 'matrix(' + matrix.join(',') + ')';
    }
    div.style.width  = el.w + 'px';
    div.style.height = el.h + 'px';
    div.style.zIndex = el.z;
    const pdiv = el.parent ? divById.get(el.parent) : null;
    (pdiv || mountEl).appendChild(div);
  }

  // 层背景(帧自身的图片/纯色/渐变);里面的 url 同样相对 .ui.json,按 assetBase 改写
  if (cap.stageBg) {
    mountEl.style.background = base
      ? cap.stageBg.replace(/url\(/g, 'url(' + base)
      : cap.stageBg;
  }
}

/**
 * 抽出一个或多个节点的子树作为独立 cap（把弹窗组件从整帧里取出来叠加到底屏）。
 * rootIds 可为单个 id 或 id 数组（弹窗常由多个顶层兄弟组成：外框+页签+列表…）。
 * 每个根 parent 置空（挂到目标层）；几何仍是相对帧的绝对 px，叠加后位置正确，z 保持。
 */
function subtreeOf(cap, rootIds) {
  const roots = Array.isArray(rootIds) ? rootIds : [rootIds];
  const rootSet = new Set(roots);
  const keep = new Set(roots);
  let changed = true;
  while (changed) {
    changed = false;
    for (const e of cap.els) {
      if (!keep.has(e.id) && e.parent && keep.has(e.parent)) { keep.add(e.id); changed = true; }
    }
  }
  const els = cap.els
    .filter(e => keep.has(e.id))
    .map(e => (rootSet.has(e.id) ? Object.assign({}, e, { parent: '' }) : e));
  return Object.assign({}, cap, { stageBg: '', els: els });
}

/**
 * 设置 stage 尺寸并按视口等比缩放。
 */
function mountStage(stageEl, fw, fh) {
  stageEl.style.position = 'relative';
  stageEl.style.width    = fw + 'px';
  stageEl.style.height   = fh + 'px';
  stageEl.style.overflow = 'hidden';

  function applyScale() {
    const vw = window.innerWidth, vh = window.innerHeight - 36; // 顶栏 36px
    const scale = Math.min(vw / fw, vh / fh);
    const offX = (vw - fw * scale) / 2;
    const offY = Math.max(0, (vh - fh * scale) / 2);
    stageEl.style.transformOrigin = '0 0';
    stageEl.style.transform = `translate(${offX}px, ${offY}px) scale(${scale})`;
  }
  applyScale();
  window.addEventListener('resize', applyScale);
}
