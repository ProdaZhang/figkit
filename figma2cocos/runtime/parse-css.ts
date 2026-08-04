// parse-css.ts — .ui.json 里 CSS 风格样式字符串的解析(纯函数,零 cc 依赖,便于日后 vitest)。
// 来源字段(见 figma2html references/ui.json-schema.md):
//   fill   = "rgba(255,251,242,1)" | "linear-gradient(180deg, rgba(..) 0%, ..)" | ""
//   radius = "37px" | "8px 8px 0px 0px"(CSS 顺序 tl tr br bl,1~4 值)
//   border = "4.0px solid rgba(219,208,184,1)"
//   shadow = "0px 4px 0px rgba(0,0,0,0.6)"(offset-x offset-y blur [spread] color)
//   text.stroke = "2px rgba(0,0,0,1)"(webkitTextStroke 值)

export interface RGBA { r: number; g: number; b: number; a: number } // r/g/b 0~255,a 0~1
/**
 * 一个角的两个半径。CSS 的 border-radius **每个角都是椭圆**:水平半径按宽算、垂直半径按高算,
 * 百分比更是分轴计算的。曾经把 `50%` 折成 `min(w,h)×50%` 的单一圆半径,
 * 于是一个 2143×680、`radius:50%` 的真椭圆(邮件面板底部那条弧)被画成胶囊,
 * 顶弧被削平 38px —— 所以这里必须留两个数。
 */
export interface Corner { x: number; y: number }
export interface Corners { tl: Corner; tr: Corner; br: Corner; bl: Corner }
export interface BorderSpec { width: number; color: RGBA }
export interface ShadowSpec { x: number; y: number; blur: number; spread: number; color: RGBA }
export interface GradientStop { color: RGBA; pos: number }            // pos 0~1
export interface GradientSpec { angleDeg: number; stops: GradientStop[] }
export interface TextStrokeSpec { width: number; color: RGBA }

const NUM = '[-+]?[0-9]*\\.?[0-9]+';

/** rgba()/rgb()/#hex → RGBA;解析不了返回 null。 */
export function parseColor(s: string): RGBA | null {
  if (!s) return null;
  const t = s.trim();
  let m = t.match(new RegExp(`^rgba?\\(\\s*(${NUM})\\s*,\\s*(${NUM})\\s*,\\s*(${NUM})\\s*(?:,\\s*(${NUM})\\s*)?\\)$`));
  if (m) {
    return { r: Math.round(+m[1]), g: Math.round(+m[2]), b: Math.round(+m[3]), a: m[4] === undefined ? 1 : +m[4] };
  }
  m = t.match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/);
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return { r, g, b, a };
  }
  return null;
}

/** radius 字符串 → 四角 px。CSS 1~4 值展开规则:1→全部;2→tl/br, tr/bl;3→tl, tr/bl, br;4→tl tr br bl。 */
/**
 * CSS border-radius 简写 → 四角像素值。
 *
 * `w`/`h` 是元素尺寸,百分比要用:capture 对**每个 figma ELLIPSE** 都产 `radius: "50%"`
 * (头像/圆点/徽章/胶囊按钮全走这条)。JS 的 `parseFloat("50%")` 返回 **50** 而不是报错,
 * 于是百分比会被静默当成 50px —— 比丢弃更坏,错得还随元素尺寸变。
 * 口径与 figma2unreal / figma2godot 对齐:百分比取 min(w,h) 的比例。
 */
export function parseRadius(s: string, w = 0, h = 0): Corners {
  const zero: Corners = { tl: { x: 0, y: 0 }, tr: { x: 0, y: 0 }, br: { x: 0, y: 0 }, bl: { x: 0, y: 0 } };
  if (!s) return zero;
  // 百分比分轴算(CSS Backgrounds §5.1):水平半径按宽、垂直半径按高。
  const v = s.trim().split(/\s+/).map(p => {
    const n = parseFloat(p);
    if (!isFinite(n)) return { x: 0, y: 0 };
    if (!p.trim().endsWith('%')) return { x: n, y: n };
    return { x: (w * n) / 100, y: (h * n) / 100 };
  });
  if (v.length === 1) return { tl: v[0], tr: v[0], br: v[0], bl: v[0] };
  if (v.length === 2) return { tl: v[0], tr: v[1], br: v[0], bl: v[1] };
  if (v.length === 3) return { tl: v[0], tr: v[1], br: v[2], bl: v[1] };
  if (v.length >= 4) return { tl: v[0], tr: v[1], br: v[2], bl: v[3] };
  return zero;
}

/** "4.0px solid rgba(...)" → { width, color };解析不了返回 null。 */
export function parseBorder(s: string): BorderSpec | null {
  if (!s) return null;
  const m = s.trim().match(new RegExp(`^(${NUM})px\\s+\\S+\\s+(.+)$`));
  if (!m) return null;
  const color = parseColor(m[2]);
  if (!color) return null;
  return { width: +m[1], color };
}

/** "0px 4px 0px [2px] rgba(...)" → { x, y, blur, spread, color };解析不了返回 null。 */
export function parseShadow(s: string): ShadowSpec | null {
  if (!s) return null;
  const cm = s.match(/(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})/);
  if (!cm) return null;
  const color = parseColor(cm[1]);
  if (!color) return null;
  const raw = s.slice(0, cm.index).match(new RegExp(`${NUM}(?=px)`, 'g'));
  const nums: number[] = [];  // 数组字面量不能当三目/逻辑的一支:Cocos 构建器里的 Babel 推断会崩(见 mapping.md)
  if (raw) for (const x of raw) nums.push(Number(x));
  if (nums.length < 2) return null;
  return { x: nums[0], y: nums[1], blur: nums[2] || 0, spread: nums[3] || 0, color };
}

/** 顶层逗号切分(不拆 rgba(..) 内部的逗号)。 */
function splitTop(s: string): string[] {
  const out: string[] = [];
  let depth = 0, cur = '';
  for (const ch of s) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

/** "linear-gradient(180deg, rgba(..) 0%, rgba(..) 100%)" → { angleDeg, stops };非线性渐变返回 null。 */
export function parseLinearGradient(s: string): GradientSpec | null {
  if (!s) return null;
  const m = s.trim().match(/^linear-gradient\((.*)\)$/s);
  if (!m) return null;
  const parts = splitTop(m[1]);
  if (!parts.length) return null;
  let angleDeg = 180;                       // CSS 默认 to bottom = 180deg
  let i = 0;
  const am = parts[0].match(new RegExp(`^(${NUM})deg$`));
  if (am) { angleDeg = +am[1]; i = 1; }
  else if (/^to\s+/.test(parts[0])) {       // 方向关键字,粗映射
    const dir = parts[0].replace(/^to\s+/, '').trim();
    angleDeg = ({ top: 0, right: 90, bottom: 180, left: 270 } as Record<string, number>)[dir] ?? 180;
    i = 1;
  }
  const stops: GradientStop[] = [];
  const raw = parts.slice(i);
  for (let k = 0; k < raw.length; k++) {
    const sm = raw[k].match(/^(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})(?:\s+([\d.]+)%)?$/);
    if (!sm) return null;
    const color = parseColor(sm[1]);
    if (!color) return null;
    const pos = sm[2] !== undefined ? +sm[2] / 100
      : (raw.length === 1 ? 0 : k / (raw.length - 1));   // 缺位置 → 均匀分布
    stops.push({ color, pos });
  }
  return stops.length ? { angleDeg, stops } : null;
}

/** fill 字符串取一个可用纯色:纯色→本色;线性渐变→首个 stop 色(known-loss,见 references/mapping.md);其余 null。 */
export function fillFirstColor(fill: string): RGBA | null {
  const c = parseColor(fill);
  if (c) return c;
  const g = parseLinearGradient(fill);
  if (g) return g.stops[0].color;
  return null;
}

// ── v1.2 矢量路径 ────────────────────────────────────────────────────────
// Graphics 有 moveTo / lineTo / bezierCurveTo / quadraticCurveTo / close,
// 所以矢量可以**照着画**,不必退成位图。这里只做解析(纯函数),replay 在 figma-ui.ts。

export type PathCmd =
  | { op: 'M'; x: number; y: number }
  | { op: 'L'; x: number; y: number }
  | { op: 'C'; x1: number; y1: number; x2: number; y2: number; x: number; y: number }
  | { op: 'Q'; op1x: number; op1y: number; x: number; y: number }
  | { op: 'Z' };

const PATH_TOK = /[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?/g;
const PATH_NARG: Record<string, number> = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2, Z: 0 };

/**
 * SVG path `d` → **绝对坐标**的命令序列(H/V 展成 L,S/T 展成 C/Q)。
 *
 * 认不出的命令(圆弧 A 等)返回 **null**,让调用方吭一声并整条跳过 ——
 * 比"跳过这一段照画其余"强:少一段的形状看着像画对了,其实是错的。
 */
export function parsePathCmds(d: string): PathCmd[] | null {
  if (!d) return null;
  const toks = d.match(PATH_TOK);
  if (!toks) return null;
  const out: PathCmd[] = [];
  let i = 0, cmd = '', px = 0, py = 0, sx = 0, sy = 0;
  let lastC: [number, number] | null = null, lastQ: [number, number] | null = null;
  const n = (k: number): number => +toks[i + k];
  while (i < toks.length) {
    if (/^[A-Za-z]$/.test(toks[i])) {
      cmd = toks[i]; i++;
      if (cmd.toUpperCase() === 'Z') { out.push({ op: 'Z' }); px = sx; py = sy; cmd = ''; continue; }
    }
    if (!cmd) return null;
    const up = cmd.toUpperCase();
    const rel = cmd !== up;
    const need = PATH_NARG[up];
    if (need === undefined || i + need > toks.length) return null;
    const bx = rel ? px : 0, by = rel ? py : 0;
    switch (up) {
      case 'M': {
        px = bx + n(0); py = by + n(1); sx = px; sy = py;
        out.push({ op: 'M', x: px, y: py }); i += 2;
        cmd = rel ? 'l' : 'L';                       // M 之后重复的数值组按 L 解释
        lastC = lastQ = null; break;
      }
      case 'L': { px = bx + n(0); py = by + n(1); out.push({ op: 'L', x: px, y: py }); i += 2; lastC = lastQ = null; break; }
      case 'H': { px = bx + n(0); out.push({ op: 'L', x: px, y: py }); i += 1; lastC = lastQ = null; break; }
      case 'V': { py = by + n(0); out.push({ op: 'L', x: px, y: py }); i += 1; lastC = lastQ = null; break; }
      case 'C': {
        const c1: [number, number] = [bx + n(0), by + n(1)];
        const c2: [number, number] = [bx + n(2), by + n(3)];
        px = bx + n(4); py = by + n(5);
        out.push({ op: 'C', x1: c1[0], y1: c1[1], x2: c2[0], y2: c2[1], x: px, y: py });
        i += 6; lastC = c2; lastQ = null; break;
      }
      case 'S': {
        const c1: [number, number] = [px, py];      // 不写三目:Babel 推断会崩(见上)
        if (lastC) { c1[0] = 2 * px - lastC[0]; c1[1] = 2 * py - lastC[1]; }
        const c2: [number, number] = [bx + n(0), by + n(1)];
        px = bx + n(2); py = by + n(3);
        out.push({ op: 'C', x1: c1[0], y1: c1[1], x2: c2[0], y2: c2[1], x: px, y: py });
        i += 4; lastC = c2; lastQ = null; break;
      }
      case 'Q': {
        const q: [number, number] = [bx + n(0), by + n(1)];
        px = bx + n(2); py = by + n(3);
        out.push({ op: 'Q', op1x: q[0], op1y: q[1], x: px, y: py });
        i += 4; lastQ = q; lastC = null; break;
      }
      case 'T': {
        const q: [number, number] = [px, py];      // 不写三目:Babel 推断会崩(见上)
        if (lastQ) { q[0] = 2 * px - lastQ[0]; q[1] = 2 * py - lastQ[1]; }
        px = bx + n(0); py = by + n(1);
        out.push({ op: 'Q', op1x: q[0], op1y: q[1], x: px, y: py });
        i += 2; lastQ = q; lastC = null; break;
      }
      default: return null;
    }
  }
  return out.length ? out : null;
}

/** "0 0 W H" → [minX, minY, w, h];解析不了返回 null。 */
export function parseViewBox(s: string): [number, number, number, number] | null {
  if (!s) return null;
  const v = s.trim().split(/[\s,]+/).map(Number);
  if (v.length !== 4 || v.some(x => !isFinite(x)) || v[2] <= 0 || v[3] <= 0) return null;
  return [v[0], v[1], v[2], v[3]];
}

/**
 * shadow 串里 `borderAlign: outside/center` 塞在**头部**的描边环 → [{width,color}, 剩下的 shadow]。
 * 捕获层把外扩描边写成 `0 0 0 Npx <color>`(box-shadow 跟随圆角,outline 不跟),
 * 与真投影同挂 shadow 字段,靠这个位置区分。
 */
export function splitRing(shadow: string, align: string): [BorderSpec | null, string] {
  if (!shadow || (align !== 'outside' && align !== 'center')) return [null, shadow];
  const parts = splitTop(shadow);
  const m = parts.length
    ? parts[0].match(new RegExp(`^0(?:px)?\\s+0(?:px)?\\s+0(?:px)?\\s+(${NUM})px\\s+(rgba?\\([^)]*\\))$`))
    : null;
  if (!m) return [null, shadow];
  const color = parseColor(m[2]);
  if (!color) return [null, shadow];
  return [{ width: +m[1], color }, parts.slice(1).join(',')];
}

/** text.stroke "2px rgba(...)" → { width, color };解析不了返回 null。 */
export function parseTextStroke(s: string): TextStrokeSpec | null {
  if (!s) return null;
  const m = s.trim().match(new RegExp(`^(${NUM})px\\s+(.+)$`));
  if (!m) return null;
  const color = parseColor(m[2]);
  if (!color) return null;
  return { width: +m[1], color };
}
