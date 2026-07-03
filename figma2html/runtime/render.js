// render.js v2 — 全保真 .ui.json (records) -> 嵌套 DOM
// 数据源:figma_capture.py 产的 <屏>.ui.json(每节点几何=相对帧的绝对px + 全部真样式)。
// 渲染:按 parent 嵌套,几何转成父相对;逐节点真样式
//       (radius/border/shadow/blur/opacity/rot/填充[纯色含透明/渐变/图片]/文字[含字形描边])。
// 不走 DSL、不折叠、不退 flat skin —— 与 figma 节点树一致。

// 注意:本函数(出运行时 DOM)与 scripts/figma_capture.py 的 rec_to_css(出 .tree.html 静态预览)
// 是**同一套贴样式映射**。改任一处样式逻辑务必同步另一处,否则"预览 ≠ 运行时"会悄悄漂移。
// 已知**有意**差异(别对齐):图片 url 这里补 '../../'(app.html 在 client 目录、深两层),
// rec_to_css 用裸路径(tree.html 与素材同级)。
function applyRecStyle(el, div) {
  const s = div.style;
  s.position  = 'absolute';
  s.boxSizing = 'border-box';
  if (el.rot)            { s.transform = 'rotate(' + el.rot + 'deg)'; s.transformOrigin = 'center center'; }
  if (el.opacity !== 1)  s.opacity = el.opacity;
  if (el.radius)         s.borderRadius = el.radius;
  if (el.border)         s.border = el.border;
  if (el.shadow)         s.boxShadow = el.shadow;
  if (el.blur)           s.filter = el.blur;

  const t = el.text;
  if (t) {
    div.textContent  = t.content;
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
    // 多行(含 \n)保留换行;单行用 nowrap,避免字体回退偏宽撑出文本框被迫折行
    s.whiteSpace = (t.content.indexOf('\n') >= 0) ? 'pre-wrap' : 'nowrap';
    s.overflow   = 'visible';
  } else if (el.img) {
    s.backgroundImage    = "url('../../" + el.img + "')";   // 有意:app.html 深两层,补 ../../(rec_to_css 用裸路径)
    s.backgroundSize     = el.imgSize || 'cover';
    s.backgroundPosition = 'center';
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
function renderScreen(cap, mountEl) {
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
    applyRecStyle(el, div);
    divById.set(el.id, div);
  }

  // pass2：绝对几何 → 父相对，按 parent 嵌套挂载
  for (const el of els) {
    const div = divById.get(el.id);
    const p   = el.parent ? recById.get(el.parent) : null;
    const px  = p ? p.x : 0, py = p ? p.y : 0;
    div.style.left   = (el.x - px) + 'px';
    div.style.top    = (el.y - py) + 'px';
    div.style.width  = el.w + 'px';
    div.style.height = el.h + 'px';
    div.style.zIndex = el.z;
    const pdiv = el.parent ? divById.get(el.parent) : null;
    (pdiv || mountEl).appendChild(div);
  }

  // 层背景（帧自身的图片/纯色/渐变）；图片 url 相对项目根 → 补 ../../ 对齐 client 目录
  if (cap.stageBg) mountEl.style.background = cap.stageBg.replace(/url\(/g, 'url(../../');
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
