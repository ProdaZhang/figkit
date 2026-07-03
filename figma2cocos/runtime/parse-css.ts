// parse-css.ts — .ui.json 里 CSS 风格样式字符串的解析(纯函数,零 cc 依赖,便于日后 vitest)。
// 来源字段(见 figma2html references/ui.json-schema.md):
//   fill   = "rgba(255,251,242,1)" | "linear-gradient(180deg, rgba(..) 0%, ..)" | ""
//   radius = "37px" | "8px 8px 0px 0px"(CSS 顺序 tl tr br bl,1~4 值)
//   border = "4.0px solid rgba(219,208,184,1)"
//   shadow = "0px 4px 0px rgba(0,0,0,0.6)"(offset-x offset-y blur [spread] color)
//   text.stroke = "2px rgba(0,0,0,1)"(webkitTextStroke 值)

export interface RGBA { r: number; g: number; b: number; a: number } // r/g/b 0~255,a 0~1
export interface Corners { tl: number; tr: number; br: number; bl: number }
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
export function parseRadius(s: string): Corners {
  const zero: Corners = { tl: 0, tr: 0, br: 0, bl: 0 };
  if (!s) return zero;
  const v = s.trim().split(/\s+/).map(p => parseFloat(p) || 0);
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
  const nums = (s.slice(0, cm.index).match(new RegExp(`${NUM}(?=px)`, 'g')) || []).map(Number);
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

/** text.stroke "2px rgba(...)" → { width, color };解析不了返回 null。 */
export function parseTextStroke(s: string): TextStrokeSpec | null {
  if (!s) return null;
  const m = s.trim().match(new RegExp(`^(${NUM})px\\s+(.+)$`));
  if (!m) return null;
  const color = parseColor(m[2]);
  if (!color) return null;
  return { width: +m[1], color };
}
