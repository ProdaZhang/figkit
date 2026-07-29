// flow-binder.ts — Cocos Creator 3.x 组装引擎:flow.json(声明)+ caps(.ui.json)→ 可跑 UI。
// 语义对齐 figma2html/runtime/assemble.js:
//   底屏常驻 + 弹窗叠加(非 swap)、事件按 figma node id 绑、guard/toggleFlag/send、
//   列表模板行克隆、checkbox 双态;域内语义由 FigmaAppHook 注册(引擎不写死)。
// 注意:本文件未在 Creator 内实机运行验证,交付态 = 源码 + 集成说明(见 SKILL.md / mapping.md)。

import {
  _decorator, Component, Node, Graphics, Label, UITransform, UIOpacity, JsonAsset,
  instantiate, Color, EventTouch, Vec2, Vec3,
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
  motion?: Record<string, Record<string, unknown>>;   // press / stagger / guardFail(见 §动效)
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

/** motion.json 里一条烘好的曲线(采样点 + 该怎么把进度贴到画面上所需的元数据)。 */
export interface CurveDef {
  points: number[][];      // [[x, y] …] 归一化进度,17 点
  dur: number;             // 秒
  type: string;            // DISSOLVE / MOVE_IN / SCALE_IN / SCALE_OUT / …
  direction: string;       // LEFT / RIGHT / TOP / BOTTOM(方向类才有)
  fromScale: number;
}

function num(v: unknown, dflt: number): number {
  return typeof v === 'number' && isFinite(v) ? v : dflt;
}

/** 采样点之间**线性**插值 —— 引擎侧唯一被允许做的曲线运算。 */
function sampleCurve(pts: number[][], x: number): number {
  if (pts.length < 2) return x;
  if (x <= pts[0][0]) return pts[0][1];
  const last = pts[pts.length - 1];
  if (x >= last[0]) return last[1];
  for (let i = 1; i < pts.length; i++) {
    if (x <= pts[i][0]) {
      const x0 = pts[i - 1][0], y0 = pts[i - 1][1];
      const span = pts[i][0] - x0;
      return span <= 0 ? pts[i][1] : y0 + (pts[i][1] - y0) * ((x - x0) / span);
    }
  }
  return last[1];
}

@ccclass('FlowBinder')
export class FlowBinder extends Component {
  @property({ type: JsonAsset, tooltip: 'flow.json(导入为 JsonAsset)' })
  flowAsset: JsonAsset | null = null;

  @property({ type: [JsonAsset], tooltip: '各屏 .ui.json;按资源名匹配 flow.caps 路径的 stem(如 "screen-login.ui")' })
  capAssets: JsonAsset[] = [];

  @property({ type: JsonAsset, tooltip: 'motion.json(scripts/bake_motion.py 烘的采样曲线;不配 = 瞬时显隐)' })
  motionAsset: JsonAsset | null = null;

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
  private lastPressed: Node | null = null;                // 最后被按下的元素(guard 拒绝时抖它)

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

    this.loadMotion();        // 必须在接线之前:按压要在 wireEvents 里挂上

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

  // ── 动效(motion.json)────────────────────────────────────────────────
  //
  // **TS 这边一条曲线都不算。** figma 给的是具体曲线(cubic-bezier / 弹簧三参),
  // 而 Creator 的 `easing.quadOut` 之流是**另一套同名不同形**的曲线 —— 各后端各挑
  // "最像的枚举",同一份 IR 在六个引擎里就是六种手感,而每家测试照样绿。所以曲线在
  // python 侧(scripts/bake_motion.py → motion.py)解成 17 个采样点,这里只做**线性**插值。
  // 与 figma2godot / figma2unity / figma2unreal 同一分工;逐点一致由 tools/conformance 对账。
  //
  // ⚠️ 帧间必须是线性插值:采样点一致只保证**关键帧上**一致,插值模式不对齐照样各算各的
  //    (Godot 的默认切线把每段两头压平、Unity 的默认平滑切线在段内拱起来,都吃过)。

  private curves: Record<string, CurveDef> = {};
  private motionCfg: Record<string, Record<string, unknown>> = {};
  private homes: Map<Node, Vec3> = new Map();          // 元素的原位(动效只是临时偏离它)

  private loadMotion(): void {
    this.motionCfg = this.flow?.motion || {};
    const root = this.motionAsset?.json as { curves?: Record<string, Record<string, unknown>> } | null;
    for (const key of Object.keys(root?.curves || {})) {
      const c = root!.curves![key];
      const pts = (c['points'] as number[][] | undefined) || [];
      if (pts.length < 2) continue;                    // unresolved 的曲线没有点
      this.curves[key] = {
        points: pts,
        dur: num(c['duration'], 0) / 1000,
        type: String(c['type'] || ''),
        direction: String(c['direction'] || ''),
        fromScale: 'fromScale' in c ? num(c['fromScale'], 0.95)
                 : ('toScale' in c ? num(c['toScale'], 0.95) : 0.95),
      };
    }
  }

  private curveForEvent(ev: FlowEvent): CurveDef | null {
    // motion.json 的 key 是 flow.events 的下标(ev<i>)—— 与 bake_flow 同一约定。
    const events = this.flow?.events || [];
    const i = events.indexOf(ev);
    return i < 0 ? null : (this.curves['ev' + i] || null);
  }

  /** 按采样曲线驱动一段动画。进度 v:0=起点 1=终点;apply 决定往哪儿贴。 */
  private play(c: CurveDef | null, reverse: boolean,
               apply: (v: number) => void, done?: () => void): void {
    if (!c || c.dur <= 0) { apply(reverse ? 0 : 1); if (done) done(); return; }
    let elapsed = 0;
    apply(reverse ? 1 : 0);
    const step = (dt: number): void => {
      elapsed += dt;
      const x = Math.min(1, elapsed / c.dur);
      const v = sampleCurve(c.points, x);
      apply(reverse ? 1 - v : v);
      if (x >= 1) { this.unschedule(step); if (done) done(); }
    };
    this.schedule(step, 0);
  }

  private home(node: Node): Vec3 {
    let p = this.homes.get(node);
    if (!p) { p = node.position.clone(); this.homes.set(node, p); }
    return p;
  }

  private setOpacity(node: Node, v: number): void {
    const op = node.getComponent(UIOpacity) || node.addComponent(UIOpacity);
    op.opacity = Math.round(255 * Math.max(0, Math.min(1, v)));
  }

  /** 绕**中心**缩放。锚点是 (0,1)(左上,见 mapping.md §2),node.scale 因此以左上角为
   *  基准 —— 直接设 scale 会让面板往右下角坍缩。位置补 (w(1−s)/2, −h(1−s)/2) 才是绕中心。 */
  private scaleAboutCenter(node: Node, s: number): void {
    const p = this.home(node);
    const ut = node.getComponent(UITransform);
    const w = ut ? ut.width : 0, h = ut ? ut.height : 0;
    node.setScale(s, s, 1);
    node.setPosition(p.x + w * (1 - s) / 2, p.y - h * (1 - s) / 2, p.z);
  }

  /** 把进度贴到画面上(与 assemble.js transitionCss 同一张表)。
   *
   * ⚠️ **位移/缩放只贴面板本体,遮罩只跟着淡。** 早先(html/godot/unity 三端同构同病)
   * 把 transform 贴在弹窗**层**上,而 backdrop 是层的子节点 —— 遮罩跟着面板一起滑/缩:
   * 顶部不变暗、四边缩进露出底屏。数值层面完全看不出来,是 Godot 实机截图才抓到的。 */
  private applyProgress(mname: string, c: CurveDef, v: number): void {
    const layer = this.layers[mname];
    if (!layer) return;
    this.setOpacity(layer, v);                          // 遮罩 + 面板整体淡
    const panelId = this.flow?.modals?.[mname]?.panel;
    const panel = panelId ? this.getNode(mname, panelId) : null;
    if (!panel) return;                                 // 没声明 panel 就只淡,不猜该动谁
    const t = c.type || 'DISSOLVE';
    if (t === 'SCALE_IN' || t === 'SCALE_OUT') {
      this.scaleAboutCenter(panel, c.fromScale + (1 - c.fromScale) * v);
    } else if (t === 'MOVE_IN' || t === 'SLIDE_IN' || t === 'MOVE_OUT' || t === 'SLIDE_OUT') {
      let ux = 0, uy = -1;                              // 缺省 BOTTOM;cocos y 向上 → 下方为负
      if (c.direction === 'LEFT') { ux = -1; uy = 0; }
      else if (c.direction === 'RIGHT') { ux = 1; uy = 0; }
      else if (c.direction === 'TOP') { ux = 0; uy = 1; }
      const lut = layer.getComponent(UITransform);
      const w = lut ? lut.width : 0, h = lut ? lut.height : 0;
      const p = this.home(panel);
      panel.setPosition(p.x + ux * w * (1 - v), p.y + uy * h * (1 - v), p.z);
    }
  }

  private resetModal(mname: string): void {
    const layer = this.layers[mname];
    if (!layer) return;
    this.setOpacity(layer, 1);
    const panelId = this.flow?.modals?.[mname]?.panel;
    const panel = panelId ? this.getNode(mname, panelId) : null;
    if (!panel) return;
    const p = this.home(panel);
    panel.setScale(1, 1, 1);
    panel.setPosition(p.x, p.y, p.z);
  }

  /** 一个元素说「错了」。guard 拒绝时抖一下 —— 参数来自 flow.motion.guardFail。 */
  wiggle(node: Node | null): void {
    const g = this.motionCfg['guardFail'];
    if (!node || !g) return;
    const amp = num(g['amp'], 6);
    const dur = num(g['duration'], 120) / 1000;
    const p = this.home(node);
    let t = 0;
    // 一去一回一归零。抖动是一次性、播完即弃的,直接按相位算,不复用转场曲线。
    const step = (dt: number): void => {
      t += dt;
      const x = Math.min(1, t / dur);
      node.setPosition(p.x + Math.sin(x * Math.PI * 2) * amp * (1 - x), p.y, p.z);
      if (x >= 1) { this.unschedule(step); node.setPosition(p.x, p.y, p.z); }
    };
    this.schedule(step, 0);
  }

  /** 可点元素没有按下态是**缺陷不是风格**:点下去毫无反应,玩家读到的是"卡了"。 */
  private wirePress(node: Node): void {
    const cfg = this.motionCfg['press'];
    if (!cfg) return;
    const target = num(cfg['scale'], 0.96);
    const c = this.curves['press'] || null;
    node.on(Node.EventType.TOUCH_START, () => {
      this.lastPressed = node;
      if (c) this.play(c, false, v => this.scaleAboutCenter(node, 1 + (target - 1) * v));
      else this.scaleAboutCenter(node, target);
    }, this);
    const up = (): void => { this.scaleAboutCenter(node, 1); };
    node.on(Node.EventType.TOUCH_END, up, this);
    node.on(Node.EventType.TOUCH_CANCEL, up, this);
  }

  /** 逐项入场:全部同时出现 = 一整块东西闪进来,量感全无;错开一点才读得出"有几条"。 */
  private staggerIn(row: Node, index: number): void {
    const cfg = this.motionCfg['stagger'];
    const c = this.curves['stagger'];
    if (!cfg || !c) return;
    const step = num(cfg['step'], 45) / 1000;
    const from = num(cfg['from'], 24);
    const p = row.position.clone();
    this.setOpacity(row, 0);
    this.scheduleOnce(() => {
      this.play(c, false, v => {
        this.setOpacity(row, v);
        row.setPosition(p.x, p.y - from * (1 - v), p.z);   // 从下方滑上来(y 向上)
      });
    }, index * step);
  }

  // ── 弹窗显隐(底屏常驻)──────────────────────────────────────────────

  openModal(name: string, c: CurveDef | null = null): void {
    for (const k of Object.keys(this.flow?.modals || {})) {
      if (this.layers[k]) this.layers[k].active = false;
    }
    this.current = name;
    const layer = this.layers[name];
    if (!layer) return;
    layer.active = true;
    if (c) this.play(c, false, v => this.applyProgress(name, c, v));
    else this.resetModal(name);
  }

  /** **有入场必有出场** —— 只做入场 = 消失时硬闪。没有转场声明就保持瞬时,不自作主张。 */
  closeModal(c: CurveDef | null = null): void {
    const cur = this.current;
    this.current = null;
    if (!c || !cur || !this.layers[cur]) {
      for (const k of Object.keys(this.flow?.modals || {})) {
        if (this.layers[k]) this.layers[k].active = false;
      }
      return;
    }
    const layer = this.layers[cur];
    this.play(c, true, v => this.applyProgress(cur, c, v), () => {
      if (this.current === null) {          // 期间又开了别的弹窗就别抢着藏
        layer.active = false;
        this.resetModal(cur);
      }
    });
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
        this.wirePress(node);                         // 先于 dispatch 挂:抬手复位要先于 guard 抖动
        node.on(Node.EventType.TOUCH_END, (e: EventTouch) => {
          e.propagationStopped = true;                // 对齐 DOM stopPropagation
          this.dispatch(ev, e);
        }, this);
      }
    }
  }

  async dispatch(ev: FlowEvent, e?: EventTouch): Promise<void> {
    if (ev.guard && !this.guardOk(ev.guard)) {
      // 以前这里对玩家是**彻底的沉默**:协议没勾就点"开始",界面毫无反应。
      this.wiggle(this.lastPressed);
      if (this.actions.onGuardFail) this.actions.onGuardFail(ev);
      return;
    }
    switch (ev.do) {
      case 'openModal': this.openModal(String(ev.arg), this.curveForEvent(ev)); break;
      case 'closeModal': this.closeModal(this.curveForEvent(ev)); break;
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
      this.staggerIn(row, idx);
    });
  }
}
