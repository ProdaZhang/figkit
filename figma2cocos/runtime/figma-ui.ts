// figma-ui.ts — Cocos Creator 3.x 运行时解释器:.ui.json(cap)→ 动态节点树。
// 语义对齐 figma2html/runtime/render.js(applyRecStyle + renderScreen + subtreeOf):
//   几何 = 相对帧的绝对 px(y 向下、原点左上)→ Creator(y 向上、锚点)坐标,转换约定见
//   references/mapping.md(每节点默认锚 (0,1),child.pos = (dx, -dy);旋转节点锚 (0.5,0.5) 保证绕中心转)。
// known-loss(全表见 references/mapping.md):blur/shadow 不渲、渐变取首色、四角不等圆角统一取 tl、
//   字体族/字重映射为系统字体 + isBold。
// 注意:本文件未在 Creator 内实机运行验证,交付态 = 源码 + 集成说明(见 SKILL.md / mapping.md)。

import {
  _decorator, Component, Node, Graphics, Label, LabelOutline, Sprite, SpriteFrame,
  UITransform, UIOpacity, JsonAsset, resources, Color,
} from 'cc';
import {
  RGBA, parseColor, parseRadius, parseBorder, parseTextStroke, fillFirstColor,
} from './parse-css';

const { ccclass, property } = _decorator;

// ── IR 类型(见 figma2html references/ui.json-schema.md)──────────────────

export interface CapText {
  content: string; color: string; size: number; family: string; weight: number;
  lh: number; ls: number; alignH: string; alignV: string; textAlign: string; stroke: string;
}
export interface CapEl {
  id: string; name: string; type: string; parent: string;
  x: number; y: number; w: number; h: number; z: number;
  rot: number; opacity: number;
  radius: string; border: string; shadow: string; blur: string;
  fill: string; img: string; imgSize: string; vec: boolean;
  text: CapText | null;
}
export interface Cap { frame: string; w: number; h: number; stageBg: string; els: CapEl[] }

// ── 工具 ─────────────────────────────────────────────────────────────────

function toColor(c: RGBA): Color {
  return new Color(c.r, c.g, c.b, Math.round(c.a * 255));
}

/** 节点锚点约定:默认 (0,1) 左上锚;旋转节点 (0.5,0.5)(CSS transform-origin 是 center,
 *  Creator 绕锚点转 —— 换锚 + 位置补偿,旋转枢轴才一致)。 */
function anchorOf(el: CapEl): [number, number] {
  return el.rot ? [0.5, 0.5] : [0, 1];
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

/**
 * 矩形绘制(fill + border),FlowBinder 的 checkbox 重绘也走这里。
 * - 圆角:Graphics.roundRect 只收单半径 → 四角不等时统一取 tl 并 console.warn(known-loss)。
 *   选"取 tl"而非分段贝塞尔:分段可做但代码量大、命中率低(capture 里绝大多数是等角),收益不抵复杂度。
 * - 渐变:Graphics 无渐变填充 API → 取首个 stop 纯色回退(known-loss)。
 *   选"首色回退"而非逐段近似:逐段条带会引入可见色阶且与真渐变仍有差,不如确定性的首色 + 文档声明。
 * - border:CSS 是内描边(border-box),Graphics.stroke 沿路径居中 → 路径内缩 width/2 逼近内描边。
 */
export function paintRect(node: Node, el: CapEl, fillOverride?: string): void {
  const ut = node.getComponent(UITransform)!;
  const g = node.getComponent(Graphics) || node.addComponent(Graphics);
  g.clear();
  const w = el.w, h = el.h;
  const x0 = -ut.anchorX * w, y0 = -ut.anchorY * h;   // 局部系矩形左下角
  const c = parseRadius(el.radius, w, h);
  let r = c.tl;
  if (c.tr !== c.tl || c.br !== c.tl || c.bl !== c.tl) {
    console.warn('[figma-ui] 四角不等圆角统一取 tl(known-loss):', el.id, el.radius);
  }
  r = Math.min(r, w / 2, h / 2);

  const fillCss = fillOverride !== undefined ? fillOverride : el.fill;
  const fc = fillFirstColor(fillCss);
  if (fc) {
    if (!parseColor(fillCss)) console.warn('[figma-ui] 渐变取首色回退(known-loss):', el.id);
    g.fillColor = toColor(fc);
    g.roundRect(x0, y0, w, h, r);
    g.fill();
  }
  const b = parseBorder(el.border);
  if (b && b.width > 0) {
    g.lineWidth = b.width;
    g.strokeColor = toColor(b.color);
    const inset = b.width / 2;                        // 内缩半线宽 ≈ CSS 内描边
    g.roundRect(x0 + inset, y0 + inset, w - b.width, h - b.width, Math.max(0, r - inset));
    g.stroke();
  }
}

const H_ALIGN: Record<string, number> = {
  'flex-start': Label.HorizontalAlign.LEFT, 'center': Label.HorizontalAlign.CENTER,
  'flex-end': Label.HorizontalAlign.RIGHT,
};
const V_ALIGN: Record<string, number> = {
  'flex-start': Label.VerticalAlign.TOP, 'center': Label.VerticalAlign.CENTER,
  'flex-end': Label.VerticalAlign.BOTTOM,
};

function buildText(node: Node, t: CapText): void {
  const label = node.addComponent(Label);
  label.string = t.content;
  label.fontSize = t.size;
  label.lineHeight = t.lh > 0 ? t.lh : Math.round(t.size * 1.2);  // render.js 'normal' ≈ 1.2
  const col = parseColor(t.color);
  if (col) label.color = toColor(col);
  label.horizontalAlign = H_ALIGN[t.alignH] ?? Label.HorizontalAlign.CENTER;
  label.verticalAlign = V_ALIGN[t.alignV] ?? Label.VerticalAlign.CENTER;
  label.overflow = Label.Overflow.CLAMP;      // 保住文本框内对齐;系统字体偏宽可能截字(known-loss)
  label.enableWrapText = false;               // 对齐 render.js nowrap;显式 \n 仍换行
  label.isBold = t.weight >= 600;             // 字重→粗体阈值(known-loss:无 500/800 分档)
  label.isItalic = false;
  if (t.stroke) {
    const st = parseTextStroke(t.stroke);
    if (st) {
      const outline = node.addComponent(LabelOutline);
      outline.width = st.width;
      outline.color = toColor(st.color);
    }
  }
}

/** 图片:resources.load 按 img 路径 stem(去扩展名),加 assetRoot 前缀;缺失 → 透明回退 + warn。 */
function buildImage(node: Node, el: CapEl, assetRoot: string): void {
  const sprite = node.addComponent(Sprite);
  sprite.sizeMode = Sprite.SizeMode.CUSTOM;   // 强制铺满 contentSize(cover/contain 差异见 known-loss)
  sprite.type = Sprite.Type.SIMPLE;
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

function applyEl(node: Node, el: CapEl, assetRoot: string): void {
  if (el.opacity !== 1) {
    node.addComponent(UIOpacity).opacity = Math.round(el.opacity * 255);
  }
  if (el.rot) node.angle = -el.rot;           // CSS 顺时针为正 → Creator 逆时针为正
  if (el.text) {
    buildText(node, el.text);
  } else if (el.img) {
    buildImage(node, el, assetRoot);
  } else if (el.fill || el.border) {
    paintRect(node, el);
  }
  // el.shadow / el.blur:Creator 无对应轻量手段,不渲(known-loss,见 mapping.md)
}

// ── 组件 ─────────────────────────────────────────────────────────────────

@ccclass('FigmaUI')
export class FigmaUI extends Component {
  @property({ type: JsonAsset, tooltip: 'figma_capture.py 产的 <屏>.ui.json(导入为 JsonAsset)' })
  capAsset: JsonAsset | null = null;

  @property({ tooltip: 'resources 下图片根前缀(如 "figma/"),拼在 img 路径 stem 前' })
  assetRoot = '';

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
    };
    const um = cap.stageBg.match(/url\(([^)]+)\)/);
    if (um) bgEl.img = um[1].replace(/^['"]|['"]$/g, '');
    else bgEl.fill = cap.stageBg;
    const node = new Node('stage-bg');
    const ut = node.addComponent(UITransform);
    ut.setAnchorPoint(0, 1);
    ut.setContentSize(cap.w, cap.h);
    mount.addChild(node);
    node.setSiblingIndex(0);
    setPos(node, bgEl, null);
    applyEl(node, bgEl, assetRoot);
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
      const node = new Node(el.name || el.id);
      const ut = node.addComponent(UITransform);
      const [ax, ay] = anchorOf(el);
      ut.setAnchorPoint(ax, ay);
      ut.setContentSize(el.w, el.h);
      (node as any).__figEl = el;             // 原始 IR 挂节点上,hook/binder 可回查
      applyEl(node, el, assetRoot);
      byId.set(el.id, node);
    }

    // pass2:挂载 + 坐标转换(z 升序遍历 → 兄弟顺序即 z 序)
    for (const el of sorted) {
      const node = byId.get(el.id)!;
      const parentRec = el.parent ? recById.get(el.parent) || null : null;
      const parentNode = parentRec ? byId.get(parentRec.id)! : mount;
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
    return FigmaUI.buildEls(els, mount, assetRoot);
  }
}
