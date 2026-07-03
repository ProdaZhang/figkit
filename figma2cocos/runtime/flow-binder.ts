// flow-binder.ts — Cocos Creator 3.x 组装引擎:flow.json(声明)+ caps(.ui.json)→ 可跑 UI。
// 语义对齐 figma2html/runtime/assemble.js:
//   底屏常驻 + 弹窗叠加(非 swap)、事件按 figma node id 绑、guard/toggleFlag/send、
//   列表模板行克隆、checkbox 双态;域内语义由 FigmaAppHook 注册(引擎不写死)。
// 注意:本文件未在 Creator 内实机运行验证,交付态 = 源码 + 集成说明(见 SKILL.md / mapping.md)。

import {
  _decorator, Component, Node, Graphics, Label, UITransform, JsonAsset,
  instantiate, Color, EventTouch, Vec2,
} from 'cc';
import { FigmaUI, Cap, CapEl, paintRect } from './figma-ui';
import { parseColor } from './parse-css';

const { ccclass, property } = _decorator;

// ── flow.json 类型(见 figma2html references/flow-events.md)──────────────

export interface FlowEvent {
  on: string;                    // 目前 'click' → 映射 Node.EventType.TOUCH_END
  el: string | string[];         // figma node id / '@any:<modal>' / '@panelOutside:<modal>'
  guard?: string[];
  do: string;
  arg?: string;
}
export interface FlowModal { cap: string; roots: string[]; panel?: string }
export interface FlowJson {
  stage?: { w: number; h: number };
  caps: Record<string, string>;
  base: string;
  modals?: Record<string, FlowModal>;
  state?: Record<string, unknown>;
  events?: FlowEvent[];
  list?: { modal: string; container: string; onRowClick: string };
  bindings?: {
    checkbox?: {
      el: string; flag: string; checkedBg?: string; uncheckedBg?: string;
      mark?: string; markColor?: string;
    };
  };
}

/** 域内 hook 契约(对齐 figma2html 的 window.APPHOOK):
 *  register:注册 actions(send/selectServer/onPush/syncBindings/onReady/onGuardFail…);
 *  init:构建完成后的后置初始化(灌数据、renderRows、默认选中…)。
 *  用法:在场景里任一更早 onLoad 的组件(或模块顶层)调 FlowBinder.registerHook(hook);
 *  FlowBinder 在 start() 才构建,onLoad 阶段注册一定来得及。 */
export interface FigmaAppHook {
  register?(app: FlowBinder): void;
  init?(app: FlowBinder): void;
}

type ActionFn = (...args: unknown[]) => unknown;
const SEL_RE = /^@(\w+):(\w+)$/;

@ccclass('FlowBinder')
export class FlowBinder extends Component {
  @property({ type: JsonAsset, tooltip: 'flow.json(导入为 JsonAsset)' })
  flowAsset: JsonAsset | null = null;

  @property({ type: [JsonAsset], tooltip: '各屏 .ui.json;按资源名匹配 flow.caps 路径的 stem(如 "screen-login.ui")' })
  capAssets: JsonAsset[] = [];

  @property({ tooltip: 'resources 下图片根前缀,透传给 FigmaUI' })
  assetRoot = '';

  static hook: FigmaAppHook | null = null;
  static registerHook(hook: FigmaAppHook): void { FlowBinder.hook = hook; }

  flow: FlowJson | null = null;
  caps: Record<string, Cap> = {};
  state: Record<string, unknown> = {};
  layers: Record<string, Node> = {};              // 'base' + 各 modal 名 → 层节点
  current: string | null = null;                  // 当前弹窗名

  private actions: Record<string, ActionFn> = {};
  private maps: Record<string, Map<string, Node>> = {};   // 层名 → (figma id → Node)
  private listTpl: Record<string, { tpl: Node; baseX: number; baseY: number; step: number }> = {};

  registerAction(name: string, fn: ActionFn): this { this.actions[name] = fn; return this; }
  registerActions(map: Record<string, ActionFn>): this { Object.assign(this.actions, map); return this; }

  /** 层内按 figma id 取节点(对齐 assemble 的 $())。 */
  getNode(layerName: string, id: string): Node | null {
    const m = this.maps[layerName];
    return m ? (m.get(id) || null) : null;
  }
  baseNode(id: string): Node | null { return this.getNode('base', id); }

  // ── 构建 ──────────────────────────────────────────────────────────────

  start(): void {
    if (!this.flowAsset || !this.flowAsset.json) {
      console.warn('[flow-binder] 未配置 flowAsset');
      return;
    }
    this.build(this.flowAsset.json as unknown as FlowJson);
  }

  build(flow: FlowJson): void {
    this.flow = flow;
    this.state = Object.assign({}, flow.state || {});
    this.caps = this.resolveCaps(flow);
    const w = flow.stage?.w ?? 1080, h = flow.stage?.h ?? 1920;

    // 根:锚 (0,1)、stage 尺寸;置于屏幕左上由 Widget 负责(mapping.md §4)
    const ut = this.node.getComponent(UITransform) || this.node.addComponent(UITransform);
    ut.setAnchorPoint(0, 1);
    ut.setContentSize(w, h);

    const hook = FlowBinder.hook;
    if (hook?.register) hook.register(this);

    // 底屏(常驻)
    const baseLayer = this.makeLayer('base', w, h, true);
    const baseCap = this.caps[flow.base];
    if (baseCap) {
      if (baseCap.stageBg) FigmaUI.buildStageBg(baseCap, baseLayer, this.assetRoot);
      this.maps['base'] = FigmaUI.buildEls(baseCap.els, baseLayer, this.assetRoot);
    } else {
      console.warn('[flow-binder] base cap 未匹配到 JsonAsset:', flow.base);
    }

    // 弹窗 = 半透明黑 backdrop + 抽面板子树叠加(几何仍是帧绝对 px,叠上即对位)
    for (const name of Object.keys(flow.modals || {})) {
      const m = flow.modals![name];
      const layer = this.makeLayer(name, w, h, false);
      const bd = new Node('backdrop');
      const but = bd.addComponent(UITransform);
      but.setAnchorPoint(0, 1);
      but.setContentSize(w, h);
      layer.addChild(bd);
      bd.setPosition(0, 0, 0);
      const g = bd.addComponent(Graphics);
      g.fillColor = new Color(0, 0, 0, 128);        // rgba(0,0,0,0.5),对齐 assemble
      g.rect(0, -h, w, h);
      g.fill();
      const cap = this.caps[m.cap];
      if (cap) this.maps[name] = FigmaUI.buildSubtree(cap, m.roots, layer, this.assetRoot);
      else console.warn('[flow-binder] modal cap 未匹配到 JsonAsset:', name, m.cap);
    }

    this.wireEvents();
    this.syncBindings();
    if (hook?.init) hook.init(this);
    if (this.actions.onReady) this.actions.onReady();
  }

  /** flow.caps 的路径 stem(去目录、去 .json)↔ JsonAsset.name 匹配。 */
  private resolveCaps(flow: FlowJson): Record<string, Cap> {
    const out: Record<string, Cap> = {};
    for (const name of Object.keys(flow.caps || {})) {
      const path = flow.caps[name];
      const stem = path.split(/[\\/]/).pop()!.replace(/\.json$/i, '');   // 'screen-login.ui'
      const asset = this.capAssets.find(a => a && (a.name === stem || stem.endsWith(a.name)));
      if (asset && asset.json) out[name] = asset.json as unknown as Cap;
      else console.warn('[flow-binder] caps[' + name + '] 找不到资源(期望资源名 "' + stem + '")');
    }
    return out;
  }

  private makeLayer(name: string, w: number, h: number, visible: boolean): Node {
    const layer = new Node('layer-' + name);
    const ut = layer.addComponent(UITransform);
    ut.setAnchorPoint(0, 1);
    ut.setContentSize(w, h);
    this.node.addChild(layer);
    layer.setPosition(0, 0, 0);
    layer.active = visible;
    this.layers[name] = layer;
    return layer;
  }

  // ── 弹窗显隐(底屏常驻)──────────────────────────────────────────────

  openModal(name: string): void {
    for (const k of Object.keys(this.flow?.modals || {})) {
      if (this.layers[k]) this.layers[k].active = false;
    }
    if (this.layers[name]) this.layers[name].active = true;
    this.current = name;
  }

  closeModal(): void {
    for (const k of Object.keys(this.flow?.modals || {})) {
      if (this.layers[k]) this.layers[k].active = false;
    }
    this.current = null;
  }

  // ── 状态 ──────────────────────────────────────────────────────────────

  setFlag(name: string, val: unknown): void { this.state[name] = val; this.syncBindings(); }
  setValue(name: string, val: unknown): void { this.state[name] = val; this.syncBindings(); }

  guardOk(guards?: string[]): boolean {
    return (guards || []).every(gn => {
      const v = this.state[gn];
      return v !== null && v !== undefined && v !== false && v !== 0 && v !== '';
    });
  }

  // ── 事件接线(click → TOUCH_END)────────────────────────────────────

  private wireEvents(): void {
    for (const ev of this.flow?.events || []) {
      const sels = Array.isArray(ev.el) ? ev.el : [ev.el];
      for (const sel of sels) {
        const sp = String(sel).match(SEL_RE);         // @any:modal / @panelOutside:modal
        if (sp) {
          const kind = sp[1], modal = sp[2];
          const layer = this.layers[modal];
          if (!layer) continue;
          layer.on(Node.EventType.TOUCH_END, (e: EventTouch) => {
            if (kind === 'any') { this.dispatch(ev, e); return; }
            if (kind === 'panelOutside') {
              const panelId = this.flow?.modals?.[modal]?.panel;
              const panel = panelId ? this.getNode(modal, panelId) : null;
              const put = panel?.getComponent(UITransform);
              const p = e.getUILocation();
              if (!put || !put.getBoundingBoxToWorld().contains(new Vec2(p.x, p.y))) {
                this.dispatch(ev, e);
              }
            }
          }, this);
          continue;
        }
        const node = this.baseNode(String(sel));      // 事件元素在底屏上找(对齐 assemble.baseEl)
        if (!node) { console.warn('[flow-binder] 事件元素未找到:', sel); continue; }
        node.on(Node.EventType.TOUCH_END, (e: EventTouch) => {
          e.propagationStopped = true;                // 对齐 DOM stopPropagation
          this.dispatch(ev, e);
        }, this);
      }
    }
  }

  async dispatch(ev: FlowEvent, e?: EventTouch): Promise<void> {
    if (ev.guard && !this.guardOk(ev.guard)) {
      if (this.actions.onGuardFail) this.actions.onGuardFail(ev);
      return;
    }
    switch (ev.do) {
      case 'openModal': this.openModal(String(ev.arg)); break;
      case 'closeModal': this.closeModal(); break;
      case 'toggleFlag': this.setFlag(String(ev.arg), !this.state[String(ev.arg)]); break;
      case 'send':
        if (this.actions.send) await this.actions.send(ev.arg, ev);
        break;
      default:
        if (this.actions[ev.do]) await this.actions[ev.do](ev, e);
        else console.warn('[flow-binder] 未知 action:', ev.do);
    }
  }

  /** hook 收到网络推送时转进引擎(对齐 assemble 的 net.onPush → actions.onPush)。 */
  push(msg: unknown): void {
    if (this.actions.onPush) this.actions.onPush(msg);
  }

  // ── 通用绑定:checkbox 双态;其余域内字段由 hook 的 syncBindings 管 ──

  syncBindings(): void {
    const c = this.flow?.bindings?.checkbox;
    if (c) {
      const node = this.baseNode(c.el);
      if (node) {
        const on = !!this.state[c.flag];
        const el = (node as any).__figEl as CapEl | undefined;   // FigmaUI 建节点时挂的原始 IR
        if (el) {
          paintRect(node, el, on ? (c.checkedBg || 'rgba(255,255,255,1)')
                                 : (c.uncheckedBg || 'rgba(255,255,255,0.2)'));
        }
        let mark = node.getChildByName('check-mark');
        if (!mark) {
          mark = new Node('check-mark');
          const ut = node.getComponent(UITransform)!;
          const mut = mark.addComponent(UITransform);
          mut.setAnchorPoint(0.5, 0.5);
          mut.setContentSize(ut.width, ut.height);
          node.addChild(mark);
          // 父锚 (0,1) → 中心在 (w/2, -h/2)
          mark.setPosition(ut.width / 2, -ut.height / 2, 0);
          const label = mark.addComponent(Label);
          label.string = c.mark || '✓';
          label.fontSize = Math.round(ut.height * 0.7);
          label.lineHeight = Math.round(ut.height * 0.7);
          label.horizontalAlign = Label.HorizontalAlign.CENTER;
          label.verticalAlign = Label.VerticalAlign.CENTER;
          label.isBold = true;
          const col = parseColor(c.markColor || 'rgba(27,76,87,1)');
          if (col) label.color = new Color(col.r, col.g, col.b, Math.round(col.a * 255));
        }
        mark.active = on;
      }
    }
    if (this.actions.syncBindings) this.actions.syncBindings(this.layers['base']);
  }

  // ── 列表:模板行克隆(对齐 assemble.renderRows)────────────────────
  //   首次调用把容器下第一行缓存为模板(行距 = 前两行 y 差,单行则取行高),
  //   之后每次清容器、逐项 instantiate 模板 → rowFn 填充 → 行绑 TOUCH_END → list.onRowClick。

  renderRows(modalName: string, containerId: string, items: unknown[],
             rowFn?: (row: Node, item: unknown, idx: number) => void): void {
    const container = this.getNode(modalName, containerId);
    if (!container) { console.warn('[flow-binder] 列表容器未找到:', containerId); return; }
    const key = modalName + '/' + containerId;
    let t = this.listTpl[key];
    if (!t) {
      const rows = container.children.slice();
      if (!rows.length) { console.warn('[flow-binder] 无模板行:', containerId); return; }
      const p0 = rows[0].position;
      const step = rows.length > 1
        ? Math.abs(rows[0].position.y - rows[1].position.y)
        : (rows[0].getComponent(UITransform)?.height || 104);
      t = this.listTpl[key] = { tpl: instantiate(rows[0]), baseX: p0.x, baseY: p0.y, step };
    }
    container.removeAllChildren();
    const onRow = this.flow?.list?.onRowClick;
    items.forEach((item, idx) => {
      const row = instantiate(t.tpl);
      container.addChild(row);
      row.setPosition(t.baseX, t.baseY - idx * t.step, 0);   // y 向上 → 下一行更小
      row.on(Node.EventType.TOUCH_END, (e: EventTouch) => {
        e.propagationStopped = true;
        if (onRow && this.actions[onRow]) this.actions[onRow](row, item, idx, e);
      }, this);
      if (rowFn) rowFn(row, item, idx);
    });
  }
}
