// figma-ui.ts — Cocos Creator 3.x 运行时解释器:.ui.json(cap)→ 动态节点树。
// 语义对齐 figma2html/runtime/render.js(applyRecStyle + renderScreen + subtreeOf):
//   几何 = 相对帧的绝对 px(y 向下、原点左上)→ Creator(y 向上、锚点)坐标,转换约定见
//   references/mapping.md(每节点默认锚 (0,1),child.pos = (dx, -dy);旋转节点锚 (0.5,0.5) 保证绕中心转)。
// known-loss(全表见 references/mapping.md):带模糊的阴影不渲、渐变取首色、
//   字体族/字重映射为系统字体 + isBold。
// v1.1/v1.2/v1.3 都已实现:clip(Mask GRAPHICS_STENCIL,跟随圆角且可嵌套)、paths(Graphics 真画)、
//   borderAlign + 硬阴影(垫层兄弟节点)、text.wrap(enableWrapText)、四角各自的圆角(逐角贝塞尔)。
// 注意 UIOpacity **不作用于 Graphics**(自身/级联都不),所以 Graphics 的颜色要自己乘累计 alpha,见 toColor。

import {
  _decorator, Component, Node, Graphics, Label, LabelOutline, Mask, Sprite,
  SpriteFrame, Texture2D, TTFFont, UITransform, UIOpacity, JsonAsset, resources, Color,
} from 'cc';
import {
  RGBA, BorderSpec, Corner, Corners, GradientSpec, PathCmd, parseColor, parseRadius, parseBorder,
  parseTextStroke, parseLinearGradient, fillFirstColor, parsePathCmds, parseViewBox, parseShadow,
  splitRing,
} from './parse-css';

const { ccclass, property } = _decorator;

// ── IR 类型(见 figma2html references/ui.json-schema.md)──────────────────

export interface CapText {
  content: string; color: string; size: number; family: string; weight: number;
  lh: number; ls: number; alignH: string; alignV: string; textAlign: string; stroke: string;
  wrap?: boolean;                                    // v1.3:定宽折行 / 随字撑宽不折
}
export interface CapPath { d: string; rule: string; fill: string; clip?: string }
export interface CapEl {
  id: string; name: string; type: string; parent: string;
  x: number; y: number; w: number; h: number; z: number;
  rot: number; opacity: number;
  radius: string; border: string; shadow: string; blur: string;
  fill: string; img: string; imgSize: string; vec: boolean;
  text: CapText | null;
  clip?: boolean;                                    // v1.1:把子节点裁进本盒(遮罩/clipsContent)
  paths?: CapPath[]; viewBox?: string;               // v1.2:矢量按路径画
  borderAlign?: string;                              // v1.2:inside / outside / center
}
export interface Cap { frame: string; w: number; h: number; stageBg: string; els: CapEl[] }

// ── 工具 ─────────────────────────────────────────────────────────────────

/**
 * RGBA → `Color`,顺带乘上**累计不透明度**。
 *
 * `mul` 不是可有可无的方便参数,是**必需的**:`UIOpacity` 在 Creator 里**完全不作用于 Graphics**
 * —— 挂在自己身上不行,挂在祖先上级联也不行(Graphics 自管 model,不进 UI 合批的顶点色)。
 * 实机探针测过:`fillColor` 自带的 alpha 生效(白 20% 压 #333 底读到 110),
 * 而自身 / 父级 `UIOpacity=51` 两种写法都读到**纯白 255**。
 * 所以 `opacity: 0.38` 的白色装饰会被画成不透明纯白,糊住整条顶栏 —— alpha 必须在这里乘进去。
 */
function toColor(c: RGBA, mul: number): Color {
  return new Color(c.r, c.g, c.b, Math.round(c.a * mul * 255));
}

/**
 * 祖先链累计不透明度(Graphics 专用,理由见 `toColor`)。
 * Sprite / Label 走 `UIOpacity`,那条链本来就是级联的,不用管。
 */
function cumOpacity(el: CapEl, recById: Map<string, CapEl>): number {
  let a = 1;
  let cur: CapEl | undefined = el;
  const seen: Record<string, boolean> = {};
  while (cur) {
    if (seen[cur.id]) break;                 // parent 环:宁可少乘也不死循环
    seen[cur.id] = true;
    if (typeof cur.opacity === 'number') a *= cur.opacity;
    if (!cur.parent) break;
    cur = recById.get(cur.parent);
  }
  return a;
}

/**
 * 运行时新建的节点必须**继承挂载点的 layer**。Creator 里 `new Node()` 落在 `Layers.Enum.DEFAULT`,
 * 而 UI 相机只照 `UI_2D` —— 编辑器里拖出来的节点自动在 UI_2D,代码建的不会。
 * 少了这一句,整棵树建得好好的、组件也都在,**画面上一个像素都没有**,而且不报任何错。
 */
function adopt(node: Node, mount: Node): Node {
  node.layer = mount.layer;
  return node;
}

/** 节点锚点约定:默认 (0,1) 左上锚;旋转节点 (0.5,0.5)(CSS transform-origin 是 center,
 *  Creator 绕锚点转 —— 换锚 + 位置补偿,旋转枢轴才一致)。 */
function anchorOf(el: CapEl): [number, number] {
  // 不写成三目:两支都是数组字面量时,Cocos 构建器里的 Babel 推断会崩(见 mapping.md known-issue)
  if (el.rot) return [0.5, 0.5];
  return [0, 1];
}

/**
 * 坐标转换核心(推导见 references/mapping.md §2):
 * 子节点 position = 父锚点→父左上角偏移 + (dx, -dy) + 子左上角→子锚点偏移
 *   dx = childAbsX - parentAbsX,dy = childAbsY - parentAbsY(IR 是 y 向下的绝对 px)
 * 默认锚 (0,1) 时退化为约定式:child.position = (dx, -dy)。
 * 挂载根(mount)必须是锚 (0,1) 的节点(buildCap / FlowBinder 建层时已保证)。
 */
function setPos(node: Node, el: CapEl, parent: CapEl | null): void {
  const [ax, ay] = anchorOf(el);
  const dx = el.x - (parent ? parent.x : 0);
  const dy = el.y - (parent ? parent.y : 0);
  let pox = 0, poy = 0;                       // 父锚点 → 父左上角(局部系,y 向上)
  if (parent) {
    const [pax, pay] = anchorOf(parent);
    pox = -pax * parent.w;
    poy = (1 - pay) * parent.h;
  }
  node.setPosition(pox + dx + ax * el.w, poy - dy - (1 - ay) * el.h, 0);
}

/** 90° 圆弧的三次贝塞尔控制点系数。 */
const KAPPA = 0.5522847498307936;

/**
 * 四角**各自**的圆角矩形路径。`Graphics.roundRect` 只收单半径,而 figma 里
 * "上圆下方"的头图/面板很常见(`73px 73px 0px 0px`),统一取 tl 会把下面两角也抹圆。
 * 逐角画就没有这条 known-loss;半径按 CSS 的等比规则先夹紧(相邻两角之和不超边长)。
 *
 * **圆角必须用 bezierCurveTo,不能用 `Graphics.arc`** —— 引擎那个 arc 有两处会咬人:
 *   ① 它第一个点走的是 `ctx.moveTo(x, y)`,**永远另起一条子路径**、不从当前点接上,
 *      于是"直边 + 四个角"变成四段互不相连的子路径,fill 把它们并成一坨 → 形状被撕成斜楔;
 *   ② 方向约定与 canvas **相反**:`counterclockwise=false` 时它 `while (da > 0) da -= 2π`,
 *      按 canvas 语义传的 (-90°→0°, false) 会被理解成 -270°,绕大圈 → 画出巨大的环。
 * 贝塞尔从当前点接着走,也没有方向歧义,两个坑一起绕开。
 */
function roundRectPath(g: Graphics, x: number, y: number, w: number, h: number, c: Corners): void {
  // CSS 的等比夹紧(Backgrounds §5.5):每条边上相邻两角的半径之和不得超过边长,
  // 超了就把**四个角**一起乘同一个系数 —— 逐角单独夹会把等半径的角夹成不等的。
  let f = 1;
  const pairs: [number, number][] = [
    [c.tl.x + c.tr.x, w], [c.bl.x + c.br.x, w], [c.tl.y + c.bl.y, h], [c.tr.y + c.br.y, h]];
  for (const [sum, edge] of pairs) if (sum > 0 && edge > 0) f = Math.min(f, edge / sum);
  const s = (v: Corner): Corner => ({ x: Math.max(0, v.x * f), y: Math.max(0, v.y * f) });
  const tl = s(c.tl), tr = s(c.tr), br = s(c.br), bl = s(c.bl);
  const k = KAPPA;
  // 局部系 y 向上:(x,y) 是左下角,逆时针走一圈。每个角是**椭圆弧**(rx≠ry 时不是圆)
  g.moveTo(x + bl.x, y);
  g.lineTo(x + w - br.x, y);
  if (br.x > 0 || br.y > 0) {
    g.bezierCurveTo(x + w - br.x + k * br.x, y, x + w, y + br.y - k * br.y, x + w, y + br.y);
  }
  g.lineTo(x + w, y + h - tr.y);
  if (tr.x > 0 || tr.y > 0) {
    g.bezierCurveTo(x + w, y + h - tr.y + k * tr.y, x + w - tr.x + k * tr.x, y + h, x + w - tr.x, y + h);
  }
  g.lineTo(x + tl.x, y + h);
  if (tl.x > 0 || tl.y > 0) {
    g.bezierCurveTo(x + tl.x - k * tl.x, y + h, x, y + h - tl.y + k * tl.y, x, y + h - tl.y);
  }
  g.lineTo(x, y + bl.y);
  if (bl.x > 0 || bl.y > 0) {
    g.bezierCurveTo(x, y + bl.y - k * bl.y, x + bl.x - k * bl.x, y, x + bl.x, y);
  }
  g.close();
}

/** 渐变纹理的边长(取样精度)。64² 的双线性放大对 172px 的奖励底已看不出色阶。 */
const GRAD_TEX = 64;

/**
 * 线性渐变 → 一张运行时生成的 `SpriteFrame`。
 *
 * Graphics 没有渐变填充 API,以前这里是"取首个 stop 纯色"的 known-loss —— 奖励底那种
 * 上下双色的红块会整块变成单色。改成自己烘一张小纹理:**每个纹素按元素真实 w/h 投影到
 * 渐变轴**再插值,所以任意角度都准(不是只处理 0/90° 的特例);拉伸到元素尺寸由双线性负责。
 */
function gradientFrame(g: GradientSpec, w: number, h: number): SpriteFrame {
  const n = GRAD_TEX;
  const buf = new Uint8Array(n * n * 4);
  const a = (g.angleDeg * Math.PI) / 180;
  const dx = Math.sin(a), dy = -Math.cos(a);          // CSS:0deg 指向上方,顺时针增大
  const len = Math.abs(w * dx) + Math.abs(h * dy);    // 渐变线长度(CSS Images §3.3)
  const stops = g.stops.slice().sort((p, q) => p.pos - q.pos);
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const px = ((i + 0.5) / n - 0.5) * w;
      const py = ((j + 0.5) / n - 0.5) * h;
      let t = 0.5;
      if (len > 0) t = 0.5 + (px * dx + py * dy) / len;
      if (t < 0) t = 0;
      if (t > 1) t = 1;
      let lo = stops[0], hi = stops[stops.length - 1];
      for (let k = 0; k + 1 < stops.length; k++) {
        if (t >= stops[k].pos && t <= stops[k + 1].pos) { lo = stops[k]; hi = stops[k + 1]; break; }
      }
      let f = 0;
      if (hi.pos > lo.pos) f = (t - lo.pos) / (hi.pos - lo.pos);
      const o = (j * n + i) * 4;
      buf[o] = Math.round(lo.color.r + (hi.color.r - lo.color.r) * f);
      buf[o + 1] = Math.round(lo.color.g + (hi.color.g - lo.color.g) * f);
      buf[o + 2] = Math.round(lo.color.b + (hi.color.b - lo.color.b) * f);
      buf[o + 3] = Math.round((lo.color.a + (hi.color.a - lo.color.a) * f) * 255);
    }
  }
  // 必须走 `reset` + `uploadData` 这条**裸数据**路径。用 `new ImageAsset({_data:…})` 再
  // `tex.image = img` 看着也对,实机会每帧抛
  // `Failed to execute 'texSubImage2D' … Overload resolution failed`(一屏刷了 4686 条),
  // 因为那条路走的是"图片元素"的上传重载,喂进去的却是 TypedArray。
  const tex = new Texture2D();
  tex.reset({ width: n, height: n, format: Texture2D.PixelFormat.RGBA8888, mipmapLevel: 1 });
  tex.uploadData(buf);
  tex.setFilters(Texture2D.Filter.LINEAR, Texture2D.Filter.LINEAR);
  const sf = new SpriteFrame();
  sf.texture = tex;
  return sf;
}

/**
 * 把渐变画进节点:一个 Mask 子节点(圆角模板)套一个铺满的渐变 Sprite。
 * 走 Mask 而不是直接给本体挂 Sprite,是因为**圆角**要跟上 —— Sprite 自己不认 border-radius,
 * 而 GRAPHICS_STENCIL 的模板是能嵌套的(本体自己的 `clip` 再套一层也没问题)。
 */
function paintGradient(node: Node, el: CapEl, spec: GradientSpec, c: Corners, ga: number): void {
  const ut = node.getComponent(UITransform)!;
  const holder = adopt(new Node((el.name || el.id) + '-grad'), node);
  const hut = holder.addComponent(UITransform);
  hut.setAnchorPoint(ut.anchorX, ut.anchorY);
  hut.setContentSize(el.w, el.h);
  node.addChild(holder);
  holder.setPosition(0, 0, 0);
  const mask = holder.addComponent(Mask);
  mask.type = Mask.Type.GRAPHICS_STENCIL;
  const mg = mask.subComp as Graphics | null;
  if (mg) {
    mg.clear();
    roundRectPath(mg, -ut.anchorX * el.w, -ut.anchorY * el.h, el.w, el.h, c);
    mg.fill();
  } else {
    console.warn('[figma-ui] 渐变的圆角模板建不出来,退化成方角:', el.id);
  }
  const fill = adopt(new Node('fill'), holder);
  const fut = fill.addComponent(UITransform);
  fut.setAnchorPoint(ut.anchorX, ut.anchorY);
  fut.setContentSize(el.w, el.h);
  holder.addChild(fill);
  fill.setPosition(0, 0, 0);
  const sp = fill.addComponent(Sprite);
  sp.sizeMode = Sprite.SizeMode.CUSTOM;
  sp.spriteFrame = gradientFrame(spec, el.w, el.h);
  if (ga < 1) sp.color = new Color(255, 255, 255, Math.round(ga * 255));
}

/**
 * 矩形绘制(fill + border),FlowBinder 的 checkbox 重绘也走这里。
 * - 渐变:烘一张小纹理走 Sprite + 圆角 Mask(见 `paintGradient`);解析不出来的渐变才退首色。
 * - border:CSS 是内描边(border-box),Graphics.stroke 沿路径居中 → 路径内缩 width/2 逼近内描边。
 */
export function paintRect(node: Node, el: CapEl, fillOverride?: string, ga: number = 1): void {
  const ut = node.getComponent(UITransform)!;
  const g = node.getComponent(Graphics) || node.addComponent(Graphics);
  g.clear();
  const w = el.w, h = el.h;
  const x0 = -ut.anchorX * w, y0 = -ut.anchorY * h;   // 局部系矩形左下角
  const c = parseRadius(el.radius, w, h);

  const fillCss = fillOverride !== undefined ? fillOverride : el.fill;
  const grad = parseLinearGradient(fillCss);
  const fc = fillFirstColor(fillCss);
  if (grad && grad.stops.length > 1) {
    paintGradient(node, el, grad, c, ga);
  } else if (fc) {
    if (!parseColor(fillCss)) console.warn('[figma-ui] 渐变取首色回退(known-loss):', el.id);
    g.fillColor = toColor(fc, ga);
    roundRectPath(g, x0, y0, w, h, c);
    g.fill();
  }
  const b = parseBorder(el.border);
  if (b && b.width > 0) {
    g.lineWidth = b.width;
    g.strokeColor = toColor(b.color, ga);
    const d = b.width / 2;                            // 内缩半线宽 ≈ CSS 内描边
    const shrink = (v: Corner): Corner => ({ x: Math.max(0, v.x - d), y: Math.max(0, v.y - d) });
    roundRectPath(g, x0 + d, y0 + d, w - b.width, h - b.width,
                  { tl: shrink(c.tl), tr: shrink(c.tr), br: shrink(c.br), bl: shrink(c.bl) });
    g.stroke();
  }
}

// ── v1.2 矢量 ────────────────────────────────────────────────────────────

/** viewBox 坐标 → 节点局部坐标(y 翻向:IR 的 y 向下,Creator 向上)。 */
function vbMapper(ut: UITransform, el: CapEl): ((x: number, y: number) => [number, number]) | null {
  // **一个变量不要既接 TS 类型的值、又接数组/对象字面量。** Cocos 构建器里的 Babel 会把
  // 字面量推成 Flow 的注解、把另一头推成 TS 的,凑 union 时直接抛
  // "expected node to be of a type [TSType] but instead got GenericTypeAnnotation",
  // **整份脚本编译不进包**(见 mapping.md 的 known-issue)。所以这里全部落到标量上。
  const vbp = parseViewBox(el.viewBox || '');
  const vx = vbp ? vbp[0] : 0;
  const vy = vbp ? vbp[1] : 0;
  const vw = vbp ? vbp[2] : el.w;
  const vh = vbp ? vbp[3] : el.h;
  if (!vw || !vh) return null;
  const sx = el.w / vw, sy = el.h / vh;
  const left = -ut.anchorX * el.w, top = (1 - ut.anchorY) * el.h;
  return (x, y) => [left + (x - vx) * sx, top - (y - vy) * sy];
}

/**
 * 一条路径拆成若干闭合轮廓的包围盒 [minX, minY, maxX, maxY](给"洞"判定用)。
 *
 * 刻意用**数字数组**而不是 `{x0,y0,x1,y1}` 对象:声明成 TS 类型的变量再被赋对象/数组
 * 字面量,Cocos 构建器里的 Babel 会一边推 TS 一边推 Flow,凑 union 时整份脚本编译不进包
 * (见 mapping.md 的 known-issue)。
 */
function contourBoxes(cmds: PathCmd[]): number[][] {
  const out: number[][] = [];
  for (const c of cmds) {
    if (c.op === 'Z') continue;
    if (c.op === 'M') { out.push([c.x, c.y, c.x, c.y]); continue; }
    if (!out.length) continue;
    const b = out[out.length - 1];
    b[0] = Math.min(b[0], c.x); b[1] = Math.min(b[1], c.y);
    b[2] = Math.max(b[2], c.x); b[3] = Math.max(b[3], c.y);
  }
  return out;
}

/**
 * `paths` → Graphics 真画。一条 path 一个子节点(一个 Graphics 只有一种 fillColor)。
 *
 * **填充规则**:Graphics 没有 fill-rule API。IR 里 evenodd 的多轮廓几乎都是"环/带洞"
 * (v1.3 起描边带就是发的这种环),而 Graphics 按缠绕方向定内外 —— 所以**把落在别的轮廓
 * 里面的那条反向**:这样无论底层按 nonzero 还是 evenodd,洞都是洞。
 */
function paintPaths(node: Node, el: CapEl, ga: number): void {
  const ut = node.getComponent(UITransform)!;
  const map = vbMapper(ut, el);
  if (!map) return;
  if (!el.paths) return;
  // **画序按 clip 分三趟**,与 figma2unity 同一套办法。figma 的 strokeGeometry 是
  // 骑在形状边线上、总宽 2w 的**预裁带**,指望消费方按 strokeAlign 裁掉一半。
  // Graphics 没有布尔裁剪,但 OUTSIDE 那半可以靠绘制顺序精确做掉:
  // 先画带子、再拿不透明的填充形状盖上去,盖住的正好是骑在里面的那一半。
  // 之前这里是照数组顺序画的,而带子在 IR 里排在形状**后面** —— 于是整条 2w 的带
  // 完整露着,描边看起来正好粗了一倍(信封上的折线就是这么变粗的)。
  // INSIDE 那半没有等价技巧,只能全宽画,记 known-loss。
  const order: CapPath[] = [];
  for (const q of el.paths) if (String(q.clip || '') === 'outside') order.push(q);
  for (const q of el.paths) if (!q.clip) order.push(q);
  for (const q of el.paths) {
    const k = String(q.clip || '');
    if (k === 'inside' || k === 'center') order.push(q);
  }
  order.forEach((p, idx) => {
    const cmds = parsePathCmds(p.d);
    if (!cmds) {
      console.warn('[figma-ui] 路径认不出来,整条跳过(不画半截):', el.id, idx);
      return;
    }
    // 这个函数里**一个三目/逻辑表达式都不留**。Cocos 构建器(Babel)在推断
    // ConditionalExpression / LogicalExpression 两支的类型时,只要一支被推成 Flow 注解、
    // 另一支是 TS 注解,就抛 "expected node to be of a type [TSType]" —— 而且不是这一行报错,
    // 是**整份脚本编译不进包**。哪一支会被推成 Flow 取决于 Babel 版本的实现细节,逐个躲不如不用。
    // (定位过程:二分到本函数,挖掉它就过、留着就崩;见 mapping.md 的 known-issue。)
    let col = parseColor(p.fill);
    if (!col) col = fillFirstColor(p.fill);
    if (!col) return;
    const child = adopt(new Node('path' + idx), node);
    const cut = child.addComponent(UITransform);
    cut.setAnchorPoint(ut.anchorX, ut.anchorY);
    cut.setContentSize(el.w, el.h);
    node.addChild(child);
    child.setPosition(0, 0, 0);
    const g = child.addComponent(Graphics);
    g.fillColor = toColor(col, ga);
    // **只有 evenodd 才能翻轮廓方向**。nonzero 的路径里,绕向本身就是数据 ——
    // figma 导出的多轮廓形状(信封上镂空的折线、48 段的描边几何)靠内外相反的绕向挖洞,
    // 无条件按包围盒把"内轮廓"翻一遍,等于把这份数据毁掉:洞被填实,线看着就粗了一圈。
    // evenodd 则相反:Graphics 只认 nonzero,得把内轮廓翻过来才挖得出洞。
    const evenOdd = String(p.rule || '').toLowerCase() === 'evenodd';
    const boxes = contourBoxes(cmds);
    const inside = boxes.map((b, i) => evenOdd && boxes.some((o, j) =>
      j !== i && o[0] <= b[0] && o[1] <= b[1] && o[2] >= b[2] && o[3] >= b[3]));
    // 轮廓用**下标区间**表示,不用一个反复重新赋值的数组变量 —— 同上那条 Babel 约束:
    // `let sub: PathCmd[] = []` 再被 `sub = [c]` 赋值,声明的 TS 注解与字面量推出的 Flow 注解
    // 撞在一起,整份脚本编译不进包。
    const starts: number[] = [];
    for (let k = 0; k < cmds.length; k++) if (cmds[k].op === 'M') starts.push(k);
    starts.forEach((s0, ci) => {
      let end = cmds.length;
      if (ci + 1 < starts.length) end = starts[ci + 1];
      const raw: PathCmd[] = cmds.slice(s0, end).filter(c => c.op !== 'Z');
      if (!raw.length) return;
      let seq: PathCmd[] = raw;
      if (inside[ci]) seq = reverseContour(raw);
      for (const c of seq) {
        if (c.op === 'M') { const [x, y] = map(c.x, c.y); g.moveTo(x, y); }
        else if (c.op === 'L') { const [x, y] = map(c.x, c.y); g.lineTo(x, y); }
        else if (c.op === 'C') {
          const [x1, y1] = map(c.x1, c.y1), [x2, y2] = map(c.x2, c.y2), [x, y] = map(c.x, c.y);
          g.bezierCurveTo(x1, y1, x2, y2, x, y);
        } else if (c.op === 'Q') {
          const [x1, y1] = map(c.op1x, c.op1y), [x, y] = map(c.x, c.y);
          g.quadraticCurveTo(x1, y1, x, y);
        }
      }
      g.close();
    });
    g.fill();
  });
}

/** 轮廓反向(首个 M 不动,其余命令倒着重连) —— 用来把"洞"的缠绕方向翻过来。 */
function reverseContour(sub: PathCmd[]): PathCmd[] {
  const pts: PathCmd[] = sub.slice();
  if (!pts.length || pts[0].op !== 'M') return sub;
  const start = pts[0] as { op: 'M'; x: number; y: number };
  const ends: [number, number][] = [[start.x, start.y]];
  for (const c of pts.slice(1)) if (c.op !== 'Z') ends.push([c.x, c.y]);
  const out: PathCmd[] = [{ op: 'M', x: ends[ends.length - 1][0], y: ends[ends.length - 1][1] }];
  for (let k = pts.length - 1; k >= 1; k--) {
    const c = pts[k];
    const to = ends[k - 1];
    if (c.op === 'L') out.push({ op: 'L', x: to[0], y: to[1] });
    else if (c.op === 'C') out.push({ op: 'C', x1: c.x2, y1: c.y2, x2: c.x1, y2: c.y1, x: to[0], y: to[1] });
    else if (c.op === 'Q') out.push({ op: 'Q', op1x: c.op1x, op1y: c.op1y, x: to[0], y: to[1] });
  }
  return out;
}

const H_ALIGN: Record<string, number> = {
  'flex-start': Label.HorizontalAlign.LEFT, 'center': Label.HorizontalAlign.CENTER,
  'flex-end': Label.HorizontalAlign.RIGHT,
};
const V_ALIGN: Record<string, number> = {
  'flex-start': Label.VerticalAlign.TOP, 'center': Label.VerticalAlign.CENTER,
  'flex-end': Label.VerticalAlign.BOTTOM,
};

/**
 * 设计字体在 resources 下的前缀,约定 `<FONT_ROOT>Regular` / `<FONT_ROOT>Bold` 两个 TTFFont。
 * 空串 = 不加载,退回系统字体 + 合成粗体(旧行为)。由 `FigmaUI.fontRoot` 写入。
 *
 * 为什么非要真字体:四端各拿各的系统默认字体时,连**换行位置**都对不上
 * (同一段定宽正文,html 断在第 12 字、unity 断在第 14 字),像素比出来剩下的全是字形噪声。
 * 设计稿用的是 Source Han Sans SC,与 Noto Sans SC 同一套字形。
 */
let FONT_ROOT = '';

function buildText(node: Node, t: CapText): void {
  const label = node.addComponent(Label);
  label.string = t.content;
  label.fontSize = t.size;
  label.lineHeight = t.lh > 0 ? t.lh : Math.round(t.size * 1.2);  // render.js 'normal' ≈ 1.2
  const col = parseColor(t.color);
  if (col) label.color = toColor(col, 1);
  label.horizontalAlign = H_ALIGN[t.alignH] ?? Label.HorizontalAlign.CENTER;
  label.verticalAlign = V_ALIGN[t.alignV] ?? Label.VerticalAlign.CENTER;
  label.overflow = Label.Overflow.CLAMP;      // 保住文本框内对齐;系统字体偏宽可能截字(known-loss)
  // 折不折行由 IR 的 `text.wrap` 说了算(v1.3,读的是 figma 的 textAutoResize),
  // 不是"内容里有没有 \n" —— 只看 \n 的话定宽正文会一行冲出文本框。
  // wrap 缺失 = v1.3 之前的老产物,退回旧口径(nowrap,显式 \n 仍换行)。
  label.enableWrapText = t.wrap === true || t.content.indexOf('\n') >= 0;
  label.isItalic = false;
  // 设计字体:装了就用真字重,没装才退"系统字体 + 合成粗体"。
  // 两者不能同时来 —— 真 Bold 字面再叠 `isBold` 会被引擎再合成一次,笔画糊成一团。
  const face = FONT_ROOT ? FONT_ROOT + (t.weight >= 600 ? 'Bold' : 'Regular') : '';
  if (!face) {
    label.isBold = t.weight >= 600;           // 字重→粗体阈值(known-loss:无 500/800 分档)
    return;
  }
  label.isBold = false;
  resources.load(face, TTFFont, (err, f) => {
    if (err || !f) {
      console.warn('[figma-ui] 设计字体缺失,退系统字体:', face);
      if (node.isValid) label.isBold = t.weight >= 600;
      return;
    }
    if (node.isValid) label.font = f;
  });
  if (t.stroke) {
    const st = parseTextStroke(t.stroke);
    if (st) {
      const outline = node.addComponent(LabelOutline);
      outline.width = st.width;
      outline.color = toColor(st.color, 1);
    }
  }
}

/** 图片:resources.load 按 img 路径 stem(去扩展名),加 assetRoot 前缀;缺失 → 透明回退 + warn。 */
function buildImage(node: Node, el: CapEl, assetRoot: string): void {
  const sprite = node.addComponent(Sprite);
  sprite.sizeMode = Sprite.SizeMode.CUSTOM;   // 强制铺满 contentSize(cover/contain 差异见 known-loss)
  sprite.type = Sprite.Type.SIMPLE;
  // **必须关掉 trim**。Creator 导入 PNG 时默认把四周的全透明边裁掉,再配上
  // `SizeMode.CUSTOM` 把**裁剪后**的图拉满 contentSize —— figma 导出的图案周围本来就带
  // 透明留白,于是画面里的图案被整体**放大**(实测奖励格的礼物图标胖了约 8%,
  // 戒指往右下多伸一截,顶栏的信封也跟着变粗)。关掉之后按原始尺寸贴,留白才算数。
  sprite.trim = false;
  const stem = el.img.replace(/\.[A-Za-z0-9]+$/, '');
  const path = assetRoot + stem + '/spriteFrame';
  resources.load(path, SpriteFrame, (err, sf) => {
    if (err || !sf) {
      console.warn('[figma-ui] 图片缺失,透明回退:', el.id, path);
      return;                                 // 不平涂占位色,与 render.js 缺图语义一致
    }
    if (node.isValid) sprite.spriteFrame = sf;
  });
}

/**
 * v1.1 的 `clip`:把子节点裁进本盒(**跟随圆角**)。
 * Creator 的 Mask 有 GRAPHICS_STENCIL —— 自己往 `mask.subComp` 画形状当模板,
 * 圆角裁剪天然做得到,而且模板是走 stencil buffer 的,**能嵌套**
 * (Godot 的 clip_children 一条链只能有一个,那边才需要挑外层)。
 */
function applyClip(node: Node, el: CapEl): void {
  const ut = node.getComponent(UITransform)!;
  const mask = node.addComponent(Mask);
  mask.type = Mask.Type.GRAPHICS_STENCIL;
  const g = mask.subComp as Graphics | null;
  if (!g) {
    console.warn('[figma-ui] Mask 没给出 Graphics,裁剪没生效:', el.id);
    return;
  }
  g.clear();
  roundRectPath(g, -ut.anchorX * el.w, -ut.anchorY * el.h, el.w, el.h,
                parseRadius(el.radius, el.w, el.h));
  g.fill();
}

/**
 * 需要**垫在本体下面**的额外盒子 → [(后缀, 画法)]。
 * Creator 没有 box-shadow,但硬阴影和 OUTSIDE 描边环本来就是"同形状的另一个盒子":
 *   · 硬阴影 `2px 6px 0px c` → 同尺寸同圆角、按 (2,6) 位移、填阴影色;
 *   · OUTSIDE 描边环 `0 0 0 Npx c` → 四边各外扩 N、圆角 +N、填描边色。
 * 画得出来就不该记成丢失;**带模糊的**投影才是真丢(Creator 无轻量逐节点模糊)。
 */
function underlays(el: CapEl): { suffix: string; dx: number; dy: number; grow: number; color: RGBA }[] {
  const out: { suffix: string; dx: number; dy: number; grow: number; color: RGBA }[] = [];
  const [ring, rest] = splitRing(el.shadow || '', (el.borderAlign || '').toLowerCase());
  if (ring && ring.width > 0) {
    out.push({ suffix: 'ring', dx: 0, dy: 0, grow: ring.width, color: ring.color });
  }
  for (const part of rest.split(/,(?![^(]*\))/)) {
    const sh = parseShadow(part.trim());
    if (!sh) continue;
    if (sh.blur > 0) {
      console.warn('[figma-ui] 带模糊的阴影丢弃(known-loss,硬阴影已用垫层还原):', el.id, part.trim());
      continue;
    }
    out.push({ suffix: 'shadow', dx: sh.x, dy: sh.y, grow: sh.spread || 0, color: sh.color });
  }
  return out;
}

/** 画一个垫层节点(与本体同形状,按 grow 外扩 / 按 dx,dy 位移)。 */
function buildUnderlay(host: Node, el: CapEl, u: { suffix: string; dx: number; dy: number; grow: number; color: RGBA }, ga: number): Node {
  const ut = host.getComponent(UITransform)!;
  const n = adopt(new Node((el.name || el.id) + '-' + u.suffix), host);
  const nut = n.addComponent(UITransform);
  nut.setAnchorPoint(ut.anchorX, ut.anchorY);
  const w = el.w + 2 * u.grow, h = el.h + 2 * u.grow;
  nut.setContentSize(w, h);
  const c = parseRadius(el.radius, el.w, el.h);
  const g = n.addComponent(Graphics);
  g.fillColor = toColor(u.color, ga);
  const grow = (v: Corner): Corner => ({ x: v.x + u.grow, y: v.y + u.grow });
  roundRectPath(g, -nut.anchorX * w, -nut.anchorY * h, w, h,
                { tl: grow(c.tl), tr: grow(c.tr), br: grow(c.br), bl: grow(c.bl) });
  g.fill();
  return n;
}

function applyEl(node: Node, el: CapEl, assetRoot: string, ga: number): void {
  if (el.opacity !== 1) {
    node.addComponent(UIOpacity).opacity = Math.round(el.opacity * 255);
  }
  if (el.rot) node.angle = -el.rot;           // CSS 顺时针为正 → Creator 逆时针为正
  if (el.text) {
    buildText(node, el.text);
  } else if (el.paths && el.paths.length) {
    paintPaths(node, el, ga);                 // v1.2:矢量照路径画,不退位图
  } else if (el.img) {
    buildImage(node, el, assetRoot);
  } else if (el.fill || el.border) {
    paintRect(node, el, undefined, ga);
  }
  if (el.clip) applyClip(node, el);           // v1.1:圆角裁剪(Mask GRAPHICS_STENCIL)
  if (el.blur) console.warn('[figma-ui] blur 丢弃(known-loss):', el.id, el.blur);
}

// ── 组件 ─────────────────────────────────────────────────────────────────

@ccclass('FigmaUI')
export class FigmaUI extends Component {
  @property({ type: JsonAsset, tooltip: 'figma_capture.py 产的 <屏>.ui.json(导入为 JsonAsset)' })
  capAsset: JsonAsset | null = null;

  @property({ tooltip: 'resources 下图片根前缀(如 "figma/"),拼在 img 路径 stem 前' })
  assetRoot = '';

  @property({ tooltip: 'resources 下设计字体前缀(如 "fonts/FigCJK-"),留空则用系统字体' })
  fontRoot = '';

  /** 设定设计字体前缀。`buildSubtree` 这类静态入口也要能设,所以放在类上。 */
  static setFontRoot(root: string): void {
    FONT_ROOT = root || '';
  }

  @property({ tooltip: '是否渲染 stageBg 帧底(叠加子树时通常关掉)' })
  renderStageBg = true;

  private _byId: Map<string, Node> = new Map();

  onLoad(): void {
    if (this.capAsset && this.capAsset.json) {
      this.buildCap(this.capAsset.json as unknown as Cap);
    }
  }

  /** 按 figma node id 取节点(hook / FlowBinder 用)。 */
  getNode(id: string): Node | null {
    return this._byId.get(id) || null;
  }

  /** 整屏构建:本组件节点即根容器(锚 (0,1)、contentSize=(cap.w,cap.h);
   *  置于屏幕左上由 Widget 对齐负责,见 mapping.md §4 Canvas 适配)。 */
  buildCap(cap: Cap): Map<string, Node> {
    FigmaUI.setFontRoot(this.fontRoot);
    const ut = this.node.getComponent(UITransform) || this.node.addComponent(UITransform);
    ut.setAnchorPoint(0, 1);
    ut.setContentSize(cap.w, cap.h);
    if (this.renderStageBg && cap.stageBg) {
      FigmaUI.buildStageBg(cap, this.node, this.assetRoot);
    }
    this._byId = FigmaUI.buildEls(cap.els, this.node, this.assetRoot);
    return this._byId;
  }

  /** stageBg:url(..) → Sprite 铺满;纯色/渐变 → Graphics(渐变取首色)。 */
  static buildStageBg(cap: Cap, mount: Node, assetRoot: string): void {
    const bgEl: CapEl = {
      id: '@stageBg', name: 'stage-bg', type: 'BG', parent: '',
      x: 0, y: 0, w: cap.w, h: cap.h, z: -1, rot: 0, opacity: 1,
      radius: '', border: '', shadow: '', blur: '',
      fill: '', img: '', imgSize: 'cover', vec: false, text: null,
      clip: false, paths: [], viewBox: '', borderAlign: '',
    };
    const um = cap.stageBg.match(/url\(([^)]+)\)/);
    if (um) bgEl.img = um[1].replace(/^['"]|['"]$/g, '');
    else bgEl.fill = cap.stageBg;
    const node = adopt(new Node('stage-bg'), mount);
    const ut = node.addComponent(UITransform);
    ut.setAnchorPoint(0, 1);
    ut.setContentSize(cap.w, cap.h);
    mount.addChild(node);
    node.setSiblingIndex(0);
    setPos(node, bgEl, null);
    applyEl(node, bgEl, assetRoot, 1);
  }

  /**
   * els → 节点树。两遍(对齐 render.js renderScreen):
   *   pass1 全量建节点 + 贴视觉;pass2 按 parent 挂载 + 绝对几何转父相对。
   * z:els 先按 z 升序稳定排序再挂载 → 同父兄弟追加顺序即绘制顺序
   *   (Creator 兄弟顺序 = 层级,等效 setSiblingIndex)。
   * mount 必须锚 (0,1)(buildCap / buildSubtree / FlowBinder 建层时已保证)。
   */
  static buildEls(els: CapEl[], mount: Node, assetRoot: string): Map<string, Node> {
    const sorted = els.slice().sort((a, b) => (a.z || 0) - (b.z || 0));
    const recById = new Map<string, CapEl>();
    const byId = new Map<string, Node>();
    for (const el of els) recById.set(el.id, el);

    // pass1:建节点 + UITransform(锚/尺寸)+ 视觉组件
    for (const el of sorted) {
      const node = adopt(new Node(el.name || el.id), mount);
      const ut = node.addComponent(UITransform);
      const [ax, ay] = anchorOf(el);
      ut.setAnchorPoint(ax, ay);
      ut.setContentSize(el.w, el.h);
      (node as any).__figEl = el;             // 原始 IR 挂节点上,hook/binder 可回查
      applyEl(node, el, assetRoot, cumOpacity(el, recById));
      byId.set(el.id, node);
    }

    // pass2:挂载 + 坐标转换(z 升序遍历 → 兄弟顺序即 z 序)
    // 垫层(硬阴影 / OUTSIDE 描边环)排在本体**之前**挂进同一个父 —— Creator 没有 z-index,
    // 先 addChild 的在下面。
    for (const el of sorted) {
      const node = byId.get(el.id)!;
      const parentRec = el.parent ? recById.get(el.parent) || null : null;
      const parentNode = parentRec ? byId.get(parentRec.id)! : mount;
      for (const u of underlays(el)) {
        const un = buildUnderlay(node, el, u, cumOpacity(el, recById));
        parentNode.addChild(un);
        setPos(un, Object.assign({}, el, {
          x: el.x + u.dx - u.grow, y: el.y + u.dy - u.grow,
          w: el.w + 2 * u.grow, h: el.h + 2 * u.grow, rot: 0,
        }), parentRec);
      }
      parentNode.addChild(node);
      setPos(node, el, parentRec);
    }
    return byId;
  }

  /**
   * 抽子树(对齐 render.js subtreeOf):rootIds(单个或数组)的整棵后代挂到 mount,
   * 根节点 parent 视为空(几何仍是相对帧的绝对 px,叠加后位置正确)。弹窗叠加用。
   */
  static buildSubtree(cap: Cap, rootIds: string | string[], mount: Node, assetRoot: string): Map<string, Node> {
    const roots: string[] = [];               // 同上:不写 `Array.isArray(x) ? x : [x]`
    if (Array.isArray(rootIds)) roots.push(...rootIds);
    else roots.push(rootIds);
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
    return FigmaUI.buildEls(els, mount, assetRoot);
  }
}
