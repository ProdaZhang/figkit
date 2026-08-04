// FigVector.cs — 把 IR v1.2 的矢量路径**真画出来**的 VisualElement。
//
// 为什么不是贴图:figma 里这些东西本来就不是图片(信封、图标、按钮纹理、页签胶囊)。
// 走位图要么去 /v1/images 下载(有渲染配额、真会被打爆),要么编译期光栅化(分辨率写死、
// 改色要重导)。UI Toolkit 从 2022.2 起自带 **Painter2D**,是货真价实的矢量绘制 API,
// 既不用额外的包(com.unity.vectorgraphics 是预览包),也不产任何图片资产。
//
// 路径来自 UXML 属性 `paths`,格式由 ui_to_unity.py 约定(见那边的 encode_paths):
//     <d>|<fill>|<rule>|<clip> ;; <d>|<fill>|<rule>|<clip> ...
// `d` 是 SVG 路径串;`clip` 为 inside/outside 时表示这条是**描边预裁带**,
// 要按填充形状裁一半(figma 的 strokeGeometry 是 ±w 的带子,不裁就两边各多一倍)。
using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.UIElements;

namespace Figkit
{
    public class FigVector : VisualElement
    {
        public new class UxmlFactory : UxmlFactory<FigVector, UxmlTraits> { }

        public new class UxmlTraits : VisualElement.UxmlTraits
        {
            readonly UxmlStringAttributeDescription _paths =
                new UxmlStringAttributeDescription { name = "paths" };
            readonly UxmlStringAttributeDescription _viewBox =
                new UxmlStringAttributeDescription { name = "view-box" };

            public override void Init(VisualElement ve, IUxmlAttributes bag, CreationContext cc)
            {
                base.Init(ve, bag, cc);
                var v = (FigVector)ve;
                v.viewBox = _viewBox.GetValueFromBag(bag, cc);
                v.paths = _paths.GetValueFromBag(bag, cc);
            }
        }

        struct Sub { public List<Vector2[]> segs; public Color fill; public bool evenOdd; public string clip; }

        readonly List<Sub> _subs = new List<Sub>();
        Rect _vb = new Rect(0, 0, 1, 1);

        public string viewBox
        {
            set
            {
                var t = (value ?? "").Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                if (t.Length == 4)
                    _vb = new Rect(F(t[0]), F(t[1]), Mathf.Max(F(t[2]), 0.0001f), Mathf.Max(F(t[3]), 0.0001f));
            }
        }

        public string paths
        {
            set
            {
                _subs.Clear();
                foreach (var entry in (value ?? "").Split(new[] { ";;" }, StringSplitOptions.RemoveEmptyEntries))
                {
                    var f = entry.Split('|');
                    if (f.Length < 3) continue;
                    var s = new Sub
                    {
                        segs = ParsePath(f[0]),
                        fill = ParseColor(f[1]),
                        evenOdd = f[2].Trim().ToLowerInvariant() == "evenodd",
                        clip = f.Length > 3 ? f[3].Trim() : "",
                    };
                    _subs.Add(s);
                }
                generateVisualContent = Draw;
                MarkDirtyRepaint();
            }
        }

        static float F(string s)
        {
            float v;
            float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v);
            return v;
        }

        static Color ParseColor(string s)
        {
            s = (s ?? "").Trim();
            int lp = s.IndexOf('('), rp = s.LastIndexOf(')');
            if (lp < 0 || rp <= lp) return Color.black;
            var p = s.Substring(lp + 1, rp - lp - 1).Split(',');
            if (p.Length < 3) return Color.black;
            float a = p.Length > 3 ? F(p[3]) : 1f;
            return new Color(F(p[0]) / 255f, F(p[1]) / 255f, F(p[2]) / 255f, a);
        }

        // ── SVG 路径 → 折线段(贝塞尔按固定步数采样,确定性) ──────────────────
        // figma 的 fillGeometry / strokeGeometry 只用 M/L/C/Z(偶见 H/V/Q),
        // 圆弧 A 没见过 —— 真碰上会被跳过,那时候画出来会缺一段,不静默假装。
        const int CURVE_STEPS = 16;

        static List<Vector2[]> ParsePath(string d)
        {
            var subs = new List<Vector2[]>();
            var cur = new List<Vector2>();
            var toks = Tokenize(d);
            Vector2 p = Vector2.zero, start = Vector2.zero, lastC = Vector2.zero;
            char cmd = ' ';
            int i = 0;
            while (i < toks.Count)
            {
                if (toks[i].Length == 1 && char.IsLetter(toks[i][0])) { cmd = toks[i][0]; i++; }
                bool rel = char.IsLower(cmd);
                char c = char.ToUpperInvariant(cmd);
                Func<int, float> n = k => F(toks[i + k]);
                switch (c)
                {
                    case 'M':
                        if (cur.Count > 1) subs.Add(cur.ToArray());
                        cur = new List<Vector2>();
                        p = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                        start = p; cur.Add(p); i += 2; cmd = rel ? 'l' : 'L';
                        break;
                    case 'L':
                        p = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                        cur.Add(p); i += 2;
                        break;
                    case 'H':
                        p = new Vector2(rel ? p.x + n(0) : n(0), p.y); cur.Add(p); i += 1;
                        break;
                    case 'V':
                        p = new Vector2(p.x, rel ? p.y + n(0) : n(0)); cur.Add(p); i += 1;
                        break;
                    case 'C':
                    case 'S':
                        {
                            Vector2 c1, c2, to;
                            if (c == 'C')
                            {
                                c1 = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                                c2 = rel ? p + new Vector2(n(2), n(3)) : new Vector2(n(2), n(3));
                                to = rel ? p + new Vector2(n(4), n(5)) : new Vector2(n(4), n(5));
                                i += 6;
                            }
                            else
                            {
                                c1 = 2f * p - lastC;
                                c2 = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                                to = rel ? p + new Vector2(n(2), n(3)) : new Vector2(n(2), n(3));
                                i += 4;
                            }
                            for (int k = 1; k <= CURVE_STEPS; k++)
                                cur.Add(Cubic(p, c1, c2, to, (float)k / CURVE_STEPS));
                            lastC = c2; p = to;
                            break;
                        }
                    case 'Q':
                    case 'T':
                        {
                            Vector2 q, to;
                            if (c == 'Q')
                            {
                                q = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                                to = rel ? p + new Vector2(n(2), n(3)) : new Vector2(n(2), n(3));
                                i += 4;
                            }
                            else
                            {
                                q = 2f * p - lastC;
                                to = rel ? p + new Vector2(n(0), n(1)) : new Vector2(n(0), n(1));
                                i += 2;
                            }
                            for (int k = 1; k <= CURVE_STEPS; k++)
                            {
                                float t = (float)k / CURVE_STEPS, u = 1 - t;
                                cur.Add(u * u * p + 2 * u * t * q + t * t * to);
                            }
                            lastC = q; p = to;
                            break;
                        }
                    case 'Z':
                        if (cur.Count > 1) { cur.Add(start); subs.Add(cur.ToArray()); }
                        cur = new List<Vector2>(); p = start;
                        break;
                    default:
                        i++;   // 认不出来的命令(如圆弧 A):跳过这个数,别死循环
                        break;
                }
            }
            if (cur.Count > 1) subs.Add(cur.ToArray());
            return subs;
        }

        static Vector2 Cubic(Vector2 a, Vector2 b, Vector2 c, Vector2 d, float t)
        {
            float u = 1 - t;
            return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
        }

        static List<string> Tokenize(string d)
        {
            var outp = new List<string>();
            int i = 0;
            while (i < d.Length)
            {
                char ch = d[i];
                if (char.IsLetter(ch)) { outp.Add(ch.ToString()); i++; }
                else if (ch == '-' || ch == '+' || ch == '.' || char.IsDigit(ch))
                {
                    int j = i + 1;
                    while (j < d.Length && (char.IsDigit(d[j]) || d[j] == '.' ||
                           ((d[j] == '-' || d[j] == '+') && (d[j - 1] == 'e' || d[j - 1] == 'E')) ||
                           d[j] == 'e' || d[j] == 'E')) j++;
                    outp.Add(d.Substring(i, j - i)); i = j;
                }
                else i++;   // 逗号 / 空白
            }
            return outp;
        }

        void Draw(MeshGenerationContext ctx)
        {
            var r = contentRect;
            if (r.width <= 0 || r.height <= 0 || _subs.Count == 0) return;
            float sx = r.width / _vb.width, sy = r.height / _vb.height;

            // figma 的 strokeGeometry 是**预裁带**:骑在形状边线上、总宽 2w,
            // 指望消费方按 strokeAlign 裁掉一半。Painter2D 没有布尔裁剪,
            // 但 **OUTSIDE 那半可以靠绘制顺序精确做掉** —— 先画带子、再用不透明的
            // 填充形状盖上去,盖住的正好是骑在里面的那一半,剩下的就是外侧描边。
            //
            // (试过用 EvenOdd 把带子和形状并进同一条路径"抵消重叠" —— **那是错的**:
            //  band XOR shape 会把形状**内部**也填上,渲染出来是一团毛笔刷似的色块。)
            //
            // INSIDE 那半没有等价技巧,只能全宽画 —— 会比设计稿粗一倍,记 known-loss。
            var p = ctx.painter2D;
            foreach (var s in _subs) if (s.clip == "outside") FillSub(p, s, r, sx, sy);
            foreach (var s in _subs) if (string.IsNullOrEmpty(s.clip)) FillSub(p, s, r, sx, sy);
            foreach (var s in _subs) if (s.clip == "inside" || s.clip == "center") FillSub(p, s, r, sx, sy);
        }

        // 一条路径里的多个闭合轮廓,能不能一次 Fill 掉?**看它们相不相交**。
        //
        // 实测(2022.3.62f3 真播放器):把互不相交的多个轮廓塞进同一次 Fill,
        // Painter2D 会在轮廓之间连出边来,tessellate 成一堆穿帮的细长三角
        // —— 页签胶囊的描边带(逐段闭合的四边形)整块糊成一片,边角拉出斜条。
        // 逐个轮廓各 Fill 一次就干净了。
        //
        // 但**不能一律逐个填**:带洞的形状(外圈 + 反向缠绕的内圈)正是靠同一次 Fill
        // 里的填充规则把洞挖出来的,拆开填等于把洞填死。
        // 判据用包围盒相不相交:洞一定落在外圈盒子里(相交 → 一次填),
        // 描边带的各段则互不相交、最多在端点相接(→ 逐个填)。相接不算相交。
        static bool ContoursAreDisjoint(List<Vector2[]> segs)
        {
            if (segs.Count < 2) return true;
            var bb = new List<Rect>();
            foreach (var s in segs)
            {
                float x0 = s[0].x, y0 = s[0].y, x1 = x0, y1 = y0;
                foreach (var v in s)
                {
                    if (v.x < x0) x0 = v.x; if (v.x > x1) x1 = v.x;
                    if (v.y < y0) y0 = v.y; if (v.y > y1) y1 = v.y;
                }
                bb.Add(new Rect(x0, y0, x1 - x0, y1 - y0));
            }
            const float EPS = 0.01f;      // 端点相接(重叠 0)不算相交
            for (int i = 0; i < bb.Count; i++)
                for (int j = i + 1; j < bb.Count; j++)
                {
                    float ox = Mathf.Min(bb[i].xMax, bb[j].xMax) - Mathf.Max(bb[i].xMin, bb[j].xMin);
                    float oy = Mathf.Min(bb[i].yMax, bb[j].yMax) - Mathf.Max(bb[i].yMin, bb[j].yMin);
                    if (ox > EPS && oy > EPS) return false;
                }
            return true;
        }

        void FillSub(Painter2D p, Sub s, Rect r, float sx, float sy)
        {
            p.fillColor = s.fill;
            var rule = s.evenOdd ? FillRule.OddEven : FillRule.NonZero;
            if (ContoursAreDisjoint(s.segs))
            {
                foreach (var seg in s.segs)
                {
                    p.BeginPath();
                    Emit(p, seg, r, sx, sy);
                    p.Fill(rule);
                }
                return;
            }
            p.BeginPath();
            foreach (var seg in s.segs) Emit(p, seg, r, sx, sy);
            p.Fill(rule);
        }

        void Emit(Painter2D p, Vector2[] seg, Rect r, float sx, float sy)
        {
            p.MoveTo(new Vector2(r.x + (seg[0].x - _vb.x) * sx, r.y + (seg[0].y - _vb.y) * sy));
            for (int k = 1; k < seg.Length; k++)
                p.LineTo(new Vector2(r.x + (seg[k].x - _vb.x) * sx, r.y + (seg[k].y - _vb.y) * sy));
            p.ClosePath();
        }
    }
}
