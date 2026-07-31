// FlowBinder.cs — figma2unity 运行时 flow 绑定器(通用引擎,不含任何域内语义)
// 目标 Unity 2022.3+ / UI Toolkit。2026-07-03 于 Unity 6000.4.8f1 batchmode 编译冒烟通过(零错零警告);
// 2026-07-29 复跑仍零错零警告,并**实机核验了 motion**:motion.json 被读成 6 条 AnimationCurve
// (各 17 关键帧),在**非关键帧点** x=0.3 上与 python 求解器、以及 Godot 4.3 侧三方一致
// 到小数点后 6 位。⚠️ 关键帧上对账没有证明力(任何插值模式在关键帧都返回原值);
// 帧间必须显式给**线性**切线,默认平滑切线会在段内拱起来 —— 见 references/mapping.md。
// **视觉/交互链仍未在 Play Mode 点验** —— 曲线的值对了,不等于画面对了。
//
// 语义 1:1 对齐 figma2html/runtime/assemble.js:
//   - 架构 = 底屏常驻 + 弹窗叠加(非 swap):底部 UI 只一份,状态唯一不串;
//   - 弹窗 = 从对应屏的 UXML 实例里按 flow.modals[*].roots 抽子树,叠到 overlay 层,
//     配半透明黑 backdrop(对应 render.js 的 subtreeOf + assemble 的 modal 层);
//   - 事件按 flow.events 声明接线(el = figma node id,':' 换 '_' 即 UXML name;
//     特殊选择器 @any:<modal> / @panelOutside:<modal>);
//   - guard:state 里列出的键全"真"才放行,否则触发 onGuardFail;
//   - 内置 do:openModal / closeModal / toggleFlag / send;其余 do 名查注册的 action;
//   - 列表:RenderRows 克隆容器下模板行 + 回调填充 + 行点击委托(onRowClick);
//   - bindings.checkbox:flag → 双态(选中底色+勾 / 未选底色+空)。
//
// 域内语义(数据→行、回填、状态色)一律走 IAppHook,引擎不写死 —— 见 IAppHook.cs。
//
// Inspector 配置:
//   uiDocument   —— 场景里的 UIDocument(其 PanelSettings 建议 Scale With Screen Size,
//                    参考分辨率 = flow.stage.w × flow.stage.h,见 references/mapping.md)
//   flowJson     —— flow.json 拖成 TextAsset
//   screens      —— capName(flow.caps 里的键,如 "base"/"notice") → 对应屏的 UXML(VisualTreeAsset)
//   appHookBehaviour —— 实现 IAppHook 的 MonoBehaviour(可空;空则 GetComponent 自查)

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.UIElements;

namespace Figma2Unity
{
    public class FlowBinder : MonoBehaviour
    {
        [Serializable]
        public struct ScreenAsset
        {
            public string capName;          // flow.caps 的键名(如 "base"、"serverlist")
            public VisualTreeAsset asset;   // ui_to_unity.py 生成的对应屏 UXML
        }

        public UIDocument uiDocument;
        public TextAsset flowJson;
        /// <summary>可选:ui_to_unity.py 给了 flow.json 时烘出的 motion.json(转场缓动的采样曲线)。
        /// 不配 = 全部瞬时显隐,是**声明在案的降级**(见 references/mapping.md),不是静默丢失。</summary>
        public TextAsset motionJson;
        public ScreenAsset[] screens;
        public MonoBehaviour appHookBehaviour;

        /// <summary>action 签名:arg = flow 事件的 arg(或行点击时的行元素),ev = 原始事件声明(可空)。</summary>
        public delegate void FlowAction(object arg, Dictionary<string, object> ev);

        /// <summary>运行时状态(flow.state 的活副本)。改动请走 SetFlag/SetValue 以触发绑定刷新。</summary>
        public Dictionary<string, object> State { get; private set; } = new Dictionary<string, object>();

        /// <summary>可选:app 在状态刷新后补域内绑定(对应 app.js 的 syncBindings(base))。参数 = 底屏根。</summary>
        public Action<VisualElement> SyncBindingsHook;

        public VisualElement Stage { get { return _stage; } }
        public VisualElement BaseLayer { get { return _baseLayer; } }
        public string CurrentModal { get { return _current; } }

        class ModalInfo
        {
            public VisualElement layer;
            public string panelId;      // "点面板外关闭"判定用(原始 figma id)
            public string capName;      // 行克隆时需重新实例化该 cap
        }

        Dictionary<string, object> _flow;
        readonly Dictionary<string, VisualTreeAsset> _assets = new Dictionary<string, VisualTreeAsset>();
        readonly Dictionary<string, FlowAction> _actions = new Dictionary<string, FlowAction>();
        readonly Dictionary<string, ModalInfo> _modals = new Dictionary<string, ModalInfo>();
        VisualElement _stage, _baseLayer, _modalWrap;
        string _current;
        IAppHook _hook;

        // 行克隆缓存(首次 RenderRows 时从模板行采样)
        class ListInfo { public string templateName; public float baseTop; public float step; public bool sampled; }
        readonly Dictionary<string, ListInfo> _listInfo = new Dictionary<string, ListInfo>();

        /// <summary>figma id → UXML name(':' 换 '_',与 ui_to_unity.py 同一约定)。</summary>
        public static string SafeName(string figmaId) { return figmaId == null ? null : figmaId.Replace(':', '_'); }

        public void RegisterAction(string name, FlowAction fn) { _actions[name] = fn; }
        public void RegisterActions(Dictionary<string, FlowAction> map)
        {
            foreach (var kv in map) _actions[kv.Key] = kv.Value;
        }

        /// <summary>底屏内按 figma id 找元素(事件/绑定都只在底屏找,同 assemble.baseEl)。</summary>
        public VisualElement BaseQ(string figmaId)
        {
            return _baseLayer != null ? _baseLayer.Q(SafeName(figmaId)) : null;
        }

        /// <summary>某弹窗层内按 figma id 找元素。</summary>
        public VisualElement ModalQ(string modalName, string figmaId)
        {
            ModalInfo m;
            return _modals.TryGetValue(modalName, out m) ? m.layer.Q(SafeName(figmaId)) : null;
        }

        void OnEnable() { Build(); }

        // ── 构建(对应 assemble.build)────────────────────────────────────
        void Build()
        {
            if (uiDocument == null || flowJson == null)
            {
                Debug.LogError("[FlowBinder] uiDocument / flowJson 未配置");
                return;
            }
            // ⚠️ **MiniJson 是会 throw 的**(FormatException),所以下面那句 `== null` 判断
            // 在真·畸形输入上**永远轮不到执行** —— 抛出去就是一个未捕获异常。
            // 而本仓的规矩是"畸形 IR 给一句话,不给 traceback"(v0.2.0 立的),
            // 另外三家运行时都守住了:godot 的 parse_string 返回 null 后 push_error、
            // unreal 判 Deserialize 的返回值、cocos 吃的是 Creator 导入期已解析好的 JsonAsset。
            // 只有这里破了口 —— 自家规矩的反例最不该出现在自家代码里。
            try
            {
                _flow = MiniJson.Parse(flowJson.text) as Dictionary<string, object>;
            }
            catch (Exception e)
            {
                Debug.LogError("[FlowBinder] flow.json 解析失败(不是合法 JSON): " + e.Message);
                return;
            }
            if (_flow == null) { Debug.LogError("[FlowBinder] flow.json 解析失败:顶层不是对象"); return; }

            _assets.Clear();
            if (screens != null)
                foreach (var s in screens)
                    if (!string.IsNullOrEmpty(s.capName) && s.asset != null) _assets[s.capName] = s.asset;

            State = new Dictionary<string, object>();
            var st = Get(_flow, "state") as Dictionary<string, object>;
            if (st != null) foreach (var kv in st) State[kv.Key] = kv.Value;

            _hook = appHookBehaviour as IAppHook;
            if (_hook == null) _hook = GetComponent<IAppHook>();
            if (_hook != null) _hook.RegisterActions(this);   // 事件接线前注册,同 app.js register

            // stage:固定 flow.stage 尺寸;视口适配交给 PanelSettings(Scale With Screen Size)
            float w = GetNum(Get(_flow, "stage", "w"), 1080f);
            float h = GetNum(Get(_flow, "stage", "h"), 1920f);
            var root = uiDocument.rootVisualElement;
            root.Clear();
            _stage = new VisualElement { name = "flow-stage" };
            _stage.style.position = Position.Absolute;
            _stage.style.left = 0; _stage.style.top = 0;
            _stage.style.width = w; _stage.style.height = h;
            _stage.style.overflow = Overflow.Hidden;
            root.Add(_stage);

            // 底屏(常驻)
            _baseLayer = MakeLayer("flow-base", w, h);
            _stage.Add(_baseLayer);
            var baseCap = Get(_flow, "base") as string;
            if (baseCap != null && _assets.ContainsKey(baseCap))
                _baseLayer.Add(InstantiateScreen(baseCap));
            else
                Debug.LogWarning("[FlowBinder] 底屏 cap 未配置资产: " + baseCap);

            // 弹窗层容器
            _modalWrap = MakeLayer("flow-modals", w, h);
            _stage.Add(_modalWrap);

            // 弹窗 = backdrop + 按 roots 抽子树叠加(对应 subtreeOf:roots 是帧顶层节点,
            // 其 USS 坐标本就是相对帧原点的绝对 px,抽出来放进同尺寸层位置天然正确)
            var modals = Get(_flow, "modals") as Dictionary<string, object>;
            _modals.Clear();
            if (modals != null)
            {
                foreach (var kv in modals)
                {
                    var decl = kv.Value as Dictionary<string, object>;
                    if (decl == null) continue;
                    var layer = MakeLayer("flow-modal-" + kv.Key, w, h);
                    layer.style.display = DisplayStyle.None;

                    var backdrop = new VisualElement { name = "flow-backdrop" };
                    backdrop.style.position = Position.Absolute;
                    backdrop.style.left = 0; backdrop.style.top = 0;
                    backdrop.style.width = w; backdrop.style.height = h;
                    backdrop.style.backgroundColor = new Color(0f, 0f, 0f, 0.5f);
                    layer.Add(backdrop);

                    var capName = Get(decl, "cap") as string;
                    var rootIds = Get(decl, "roots") as List<object>;
                    if (capName != null && _assets.ContainsKey(capName) && rootIds != null)
                    {
                        var tc = InstantiateScreen(capName);           // 完整屏实例(带样式表)
                        var sheets = CollectStyleSheets(tc);
                        foreach (var rid in rootIds)
                        {
                            var el = tc.Q(SafeName(rid as string));
                            if (el == null) { Debug.LogWarning("[FlowBinder] 弹窗根未找到: " + rid); continue; }
                            el.RemoveFromHierarchy();
                            foreach (var ss in sheets) el.styleSheets.Add(ss);   // 抽离后样式表跟着走
                            layer.Add(el);
                        }
                        // 其余(screen-root 等)丢弃 —— 等价 subtreeOf 只保留根子树、stageBg 置空
                    }

                    _modalWrap.Add(layer);
                    _modals[kv.Key] = new ModalInfo
                    {
                        layer = layer,
                        panelId = Get(decl, "panel") as string,
                        capName = capName
                    };
                }
            }

            LoadMotion();       // 必须在 WireEvents 之前:按压要在接线时挂上
            WireEvents();
            SyncBindings();
            if (_hook != null) _hook.Init(this);   // 对应 onReady / APPHOOK.init
        }

        VisualElement MakeLayer(string name, float w, float h)
        {
            var v = new VisualElement { name = name };
            v.style.position = Position.Absolute;
            v.style.left = 0; v.style.top = 0;
            v.style.width = w; v.style.height = h;
            return v;
        }

        VisualElement InstantiateScreen(string capName)
        {
            var tc = _assets[capName].Instantiate();
            tc.style.position = Position.Absolute;
            tc.style.left = 0; tc.style.top = 0;
            return tc;
        }

        /// <summary>收集实例树上挂的全部样式表(UXML &lt;Style&gt; 落点因版本而异,树上扫一遍最稳)。</summary>
        static List<StyleSheet> CollectStyleSheets(VisualElement treeRoot)
        {
            var found = new List<StyleSheet>();
            Collect(treeRoot, found);
            return found;
        }
        static void Collect(VisualElement el, List<StyleSheet> into)
        {
            for (int i = 0; i < el.styleSheets.count; i++)
                if (!into.Contains(el.styleSheets[i])) into.Add(el.styleSheets[i]);
            foreach (var c in el.Children()) Collect(c, into);
        }

        // ── 动效(motion.json,同 assemble.js 的 flow.motion / events[].transition)────────
        //
        // **C# 这边一条曲线都不算。** figma 给的是具体曲线(cubic-bezier / 弹簧三参),
        // 而 Unity 自带的缓动枚举同名不同形 —— 各引擎各挑"最像的"就是同一份 IR 六种手感,
        // 而每家测试照样绿。所以曲线在 python 侧解算成 17 个关键帧,这里只做插值。
        // 这条分工与 figma2unreal 的"python 段做完全部数值解算、引擎侧零解析"一致。
        class Curve
        {
            public AnimationCurve curve;
            public float durationSec;
            public string type;          // DISSOLVE / MOVE_IN / SCALE_IN / SCALE_OUT / …
            public string direction;     // LEFT / RIGHT / TOP / BOTTOM(方向类才有)
            public float fromScale = 0.95f;
        }

        readonly Dictionary<string, Curve> _curves = new Dictionary<string, Curve>();
        Dictionary<string, object> _motionCfg;

        void LoadMotion()
        {
            if (motionJson == null) return;
            Dictionary<string, object> root;
            try
            {
                root = MiniJson.Parse(motionJson.text) as Dictionary<string, object>;
            }
            catch (Exception e)
            {
                // 动效解析不了不该带塌整个界面:登记一句,退回瞬时显隐(mapping.md 里
                // "没有 motion.json = 全部瞬时"本来就是声明在案的降级)。
                Debug.LogWarning("[FlowBinder] motion.json 解析失败,转场退回瞬时: " + e.Message);
                return;
            }
            var curves = root != null ? Get(root, "curves") as Dictionary<string, object> : null;
            if (curves == null) return;
            foreach (var kv in curves)
            {
                var c = kv.Value as Dictionary<string, object>;
                var pts = c != null ? Get(c, "points") as List<object> : null;
                if (pts == null || pts.Count < 2) continue;      // unresolved 的曲线没有点,跳过
                var ac = new AnimationCurve();
                foreach (var po in pts)
                {
                    var p = po as List<object>;
                    if (p != null && p.Count >= 2) ac.AddKey(Num(p[0]), Num(p[1]));
                }
                // 关键帧之间必须是**线性**插值。采样点一致只保证关键帧上一致,帧间插值模式
                // 不对齐,各引擎照样各算各的(AnimationCurve 默认是平滑切线,会在段内拱起来)。
                for (int i = 0; i < ac.length; i++)
                {
                    var k = ac[i];
                    if (i > 0) k.inTangent = (k.value - ac[i - 1].value) / (k.time - ac[i - 1].time);
                    if (i < ac.length - 1) k.outTangent = (ac[i + 1].value - k.value) / (ac[i + 1].time - k.time);
                    ac.MoveKey(i, k);
                }
                _curves[kv.Key] = new Curve
                {
                    curve = ac,
                    durationSec = Num(Get(c, "duration")) / 1000f,
                    type = Get(c, "type") as string,
                    direction = Get(c, "direction") as string,
                    fromScale = c.ContainsKey("fromScale") ? Num(Get(c, "fromScale"))
                              : (c.ContainsKey("toScale") ? Num(Get(c, "toScale")) : 0.95f),
                };
            }
            _motionCfg = Get(_flow, "motion") as Dictionary<string, object>;
        }

        static float Num(object o)
        {
            if (o is double) return (float)(double)o;
            if (o is float) return (float)o;
            if (o is int) return (int)o;
            return 0f;
        }

        /// <summary>按采样曲线驱动一段动画。t 归一化 0..1,回调自己决定往哪儿贴。
        ///
        /// ⚠️ **进度读的是时钟,不是"回调被叫了几次"。** 这里一度写的是 `elapsed += 0.016f`
        /// —— 把 `.Every(16)` 的**期望**间隔当成实际间隔。主线程一卡,回调照样一次加 16ms,
        /// 于是 300ms 的转场在墙钟上跑成 400ms;别家(Godot 的 tween、Cocos 的 `schedule(dt)`、
        /// html 的 CSS transition)全是跟真实时间走的,只有这里会随帧率变长。
        /// `TimerState.now` 是引擎给的毫秒时钟,拿它减起点既对齐了三端,也不会累积漂移。</summary>
        void Play(VisualElement el, Curve c, bool reverse, Action<VisualElement, float> apply, Action done)
        {
            if (el == null || c == null || c.durationSec <= 0f) { if (apply != null) apply(el, reverse ? 0f : 1f); if (done != null) done(); return; }
            long t0 = -1L;
            apply(el, reverse ? 1f : 0f);
            IVisualElementScheduledItem item = null;
            item = el.schedule.Execute((TimerState ts) =>
            {
                if (t0 < 0L) t0 = ts.now;
                float x = Mathf.Clamp01((ts.now - t0) / 1000f / c.durationSec);
                float v = c.curve.Evaluate(x);
                apply(el, reverse ? 1f - v : v);
                if (x >= 1f)
                {
                    item.Pause();
                    if (done != null) done();
                }
            }).Every(16);
        }

        /// <summary>把进度贴到画面上。
        ///
        /// ⚠️ **位移/缩放只贴面板本体,遮罩只跟着淡。** 早先把 transform 贴在弹窗**层**上,
        /// 而 backdrop 是层的子元素 —— 于是遮罩跟着面板一起滑/缩:顶部不变暗、四边缩进
        /// 露出底屏。数值层面完全看不出来(曲线取值一个不差),是 Godot 实机截图抓到的,
        /// 三端同构同病。</summary>
        void ApplyProgress(string modalName, Curve c, float v)
        {
            ModalInfo m;
            if (!_modals.TryGetValue(modalName, out m)) return;
            m.layer.style.opacity = v;                       // 遮罩 + 面板整体淡
            var panel = m.panelId != null ? m.layer.Q(SafeName(m.panelId)) : null;
            if (panel == null) return;                        // 没声明 panel 就只淡,不猜该动谁
            string type = c.type ?? "DISSOLVE";
            if (type == "SCALE_IN" || type == "SCALE_OUT")
            {
                float s = Mathf.Lerp(c.fromScale, 1f, v);
                panel.style.transformOrigin = new TransformOrigin(Length.Percent(50), Length.Percent(50));
                panel.style.scale = new Scale(new Vector2(s, s));
            }
            else if (type == "MOVE_IN" || type == "SLIDE_IN" || type == "MOVE_OUT" || type == "SLIDE_OUT")
            {
                float sx = 0f, sy = 1f;
                switch (c.direction)
                {
                    case "LEFT": sx = -1f; sy = 0f; break;
                    case "RIGHT": sx = 1f; sy = 0f; break;
                    case "TOP": sx = 0f; sy = -1f; break;
                    default: sx = 0f; sy = 1f; break;         // BOTTOM 及缺省
                }
                float w = m.layer.resolvedStyle.width, h = m.layer.resolvedStyle.height;
                panel.style.translate = new Translate(sx * w * (1f - v), sy * h * (1f - v));
            }
        }

        void ResetModal(string modalName)
        {
            ModalInfo m;
            if (!_modals.TryGetValue(modalName, out m)) return;
            m.layer.style.opacity = 1f;
            var panel = m.panelId != null ? m.layer.Q(SafeName(m.panelId)) : null;
            if (panel == null) return;
            panel.style.scale = new Scale(Vector2.one);
            panel.style.translate = new Translate(0f, 0f);
        }

        Curve CurveForEvent(Dictionary<string, object> ev)
        {
            // motion.json 的 key 是 flow.events 的下标(ev<i>) —— 与 bake_flow 同一约定。
            var events = Get(_flow, "events") as List<object>;
            if (events == null) return null;
            for (int i = 0; i < events.Count; i++)
            {
                if (!ReferenceEquals(events[i], ev)) continue;
                Curve c;
                return _curves.TryGetValue("ev" + i, out c) ? c : null;
            }
            return null;
        }

        // ── 弹窗显隐(底屏常驻,同 assemble.openModal/closeModal)────────
        public void OpenModal(string name) { OpenModal(name, null); }

        // 带曲线的重载是**内部**的:Curve 是私有嵌套类型,放进 public 签名会 CS0051
        // (可访问性不一致)。对外 API 仍是无参那两个,保持向后兼容。
        void OpenModal(string name, Curve c)
        {
            foreach (var kv in _modals) kv.Value.layer.style.display = DisplayStyle.None;
            ModalInfo m;
            if (!_modals.TryGetValue(name, out m)) { _current = name; return; }
            m.layer.style.display = DisplayStyle.Flex;
            _current = name;
            if (c != null) Play(m.layer, c, false, (e, v) => ApplyProgress(name, c, v), null);
            else ResetModal(name);
        }

        public void CloseModal() { CloseModal(null); }

        /// <summary>**有入场必有出场** —— 只做入场 = 消失时硬闪。没有转场声明就保持瞬时,不自作主张。</summary>
        void CloseModal(Curve c)
        {
            string cur = _current;
            ModalInfo m;
            _current = null;
            if (c == null || cur == null || !_modals.TryGetValue(cur, out m))
            {
                foreach (var kv in _modals) kv.Value.layer.style.display = DisplayStyle.None;
                return;
            }
            var layer = m.layer;
            Play(layer, c, true, (e, v) => ApplyProgress(cur, c, v), () =>
            {
                if (_current == null) { layer.style.display = DisplayStyle.None; ResetModal(cur); }
            });
        }

        // ── 状态与守卫 ────────────────────────────────────────────────
        public void SetFlag(string name, object val) { State[name] = val; SyncBindings(); }
        public void SetValue(string name, object val) { State[name] = val; SyncBindings(); }

        /// <summary>guard 判定:null/false/0/"" 皆为假(同 assemble.guardOk)。</summary>
        public static bool Truthy(object v)
        {
            if (v == null) return false;
            if (v is bool) return (bool)v;
            if (v is double) return Math.Abs((double)v) > double.Epsilon;
            if (v is string) return ((string)v).Length > 0;
            return true;
        }

        bool GuardOk(List<object> guards)
        {
            if (guards == null) return true;
            foreach (var g in guards)
            {
                object v;
                if (!(g is string) || !State.TryGetValue((string)g, out v) || !Truthy(v)) return false;
            }
            return true;
        }

        // ── 事件接线(对应 assemble.wireEvents)──────────────────────────
        void WireEvents()
        {
            var events = Get(_flow, "events") as List<object>;
            if (events != null)
            {
                foreach (var evo in events)
                {
                    var ev = evo as Dictionary<string, object>;
                    if (ev == null) continue;
                    var elDecl = Get(ev, "el");
                    var sels = elDecl is List<object> ? (List<object>)elDecl : new List<object> { elDecl };
                    foreach (var selo in sels)
                    {
                        var sel = selo as string;
                        if (sel == null) continue;
                        WireOne(sel, ev);
                    }
                }
            }

            // 列表行点击委托(行由 RenderRows 打上 flow-row 类,同 data-row)
            var list = Get(_flow, "list") as Dictionary<string, object>;
            if (list != null)
            {
                var modalName = Get(list, "modal") as string;
                var onRowClick = Get(list, "onRowClick") as string;
                ModalInfo m;
                if (modalName != null && _modals.TryGetValue(modalName, out m) && onRowClick != null)
                {
                    var mi = m;
                    m.layer.RegisterCallback<ClickEvent>(e =>
                    {
                        var row = FindAncestorWithClass(e.target as VisualElement, "flow-row", mi.layer);
                        FlowAction fn;
                        if (row != null && _actions.TryGetValue(onRowClick, out fn)) fn(row, null);
                    });
                }
            }
        }

        void WireOne(string sel, Dictionary<string, object> ev)
        {
            // @in:<modal>:<nodeId> —— 弹窗**内部**的元素(v1.1),真实 figma 文件里最常见的
            // 那条连线(弹窗里的 ✗)。节点 id 自带冒号("4:99"),所以 @in: 之后只有第一段是
            // 弹窗名,其余整段都是 id —— 下面那条按第一个冒号切的通用分支会把它切错。
            if (sel.StartsWith("@in:"))
            {
                string rest = sel.Substring(4);
                int cut = rest.IndexOf(':');
                if (cut < 0) { Debug.LogWarning("[FlowBinder] 选择器无效: " + sel); return; }
                ModalInfo host;
                if (!_modals.TryGetValue(rest.Substring(0, cut), out host))
                {
                    Debug.LogWarning("[FlowBinder] 选择器指向不存在的弹窗: " + sel);
                    return;
                }
                var inner = host.layer.Q(SafeName(rest.Substring(cut + 1)));
                if (inner == null) { Debug.LogWarning("[FlowBinder] 弹窗内事件元素未找到: " + sel); return; }
                inner.pickingMode = PickingMode.Position;
                WirePress(inner);
                // StopPropagation 不能省:同一层上多半还挂着 @any/@panelOutside,
                // 冒泡上去就成了"按了 ✗,顺手又触发一次点外面关闭"。
                inner.RegisterCallback<ClickEvent>(e => { e.StopPropagation(); Dispatch(ev); });
                return;
            }

            // 特殊选择器 @any:<modal> / @panelOutside:<modal>
            if (sel.Length > 0 && sel[0] == '@')
            {
                int colon = sel.IndexOf(':');
                if (colon < 0) return;
                string kind = sel.Substring(1, colon - 1), modal = sel.Substring(colon + 1);
                ModalInfo m;
                if (!_modals.TryGetValue(modal, out m)) return;
                var mi = m;
                m.layer.RegisterCallback<ClickEvent>(e =>
                {
                    if (kind == "any") { Dispatch(ev); return; }
                    if (kind == "panelOutside")
                    {
                        var panel = mi.panelId != null ? mi.layer.Q(SafeName(mi.panelId)) : null;
                        if (panel == null || !IsInside(e.target as VisualElement, panel)) Dispatch(ev);
                    }
                });
                return;
            }

            var el = BaseQ(sel);
            if (el == null) { Debug.LogWarning("[FlowBinder] 事件元素未找到: " + sel); return; }
            el.pickingMode = PickingMode.Position;
            WirePress(el);
            el.RegisterCallback<ClickEvent>(e => { e.StopPropagation(); Dispatch(ev); });
        }

        // ── 按压 / 抖动(flow.motion,同 assemble.wirePress / wiggle)────────────────
        VisualElement _lastPressed;

        /// <summary>可点元素没有按下态是**缺陷不是风格**:点下去毫无反应,玩家读到的是"卡了"。</summary>
        void WirePress(VisualElement el)
        {
            var cfg = _motionCfg != null ? Get(_motionCfg, "press") as Dictionary<string, object> : null;
            if (cfg == null) return;
            Curve c;
            _curves.TryGetValue("press", out c);
            float target = cfg.ContainsKey("scale") ? Num(Get(cfg, "scale")) : 0.96f;
            el.RegisterCallback<PointerDownEvent>(e =>
            {
                _lastPressed = el;
                if (c != null) Play(el, c, false, (x, v) => { float s = Mathf.Lerp(1f, target, v); x.style.scale = new Scale(new Vector2(s, s)); }, null);
                else el.style.scale = new Scale(new Vector2(target, target));
            });
            EventCallback<PointerUpEvent> up = e => { el.style.scale = new Scale(Vector2.one); };
            el.RegisterCallback(up);
            el.RegisterCallback<PointerLeaveEvent>(e => { el.style.scale = new Scale(Vector2.one); });
        }

        /// <summary>一个元素说「错了」。guard 拒绝时抖一下 —— 参数来自 flow.motion.guardFail。</summary>
        public void Wiggle(VisualElement el)
        {
            var cfg = _motionCfg != null ? Get(_motionCfg, "guardFail") as Dictionary<string, object> : null;
            if (el == null || cfg == null) return;
            float amp = cfg.ContainsKey("amp") ? Num(Get(cfg, "amp")) : 6f;
            float dur = (cfg.ContainsKey("duration") ? Num(Get(cfg, "duration")) : 120f) / 1000f;
            long t0 = -1L;                                   // 真实时钟,理由同 Play
            IVisualElementScheduledItem item = null;
            item = el.schedule.Execute((TimerState ts) =>
            {
                if (t0 < 0L) t0 = ts.now;
                float x = Mathf.Clamp01((ts.now - t0) / 1000f / dur);
                // 一去一回一归零。抖动是**一次性、播完即弃**的,所以直接按相位算,不复用转场曲线。
                float off = Mathf.Sin(x * Mathf.PI * 2f) * amp * (1f - x);
                el.style.translate = new Translate(off, 0f);
                if (x >= 1f) { el.style.translate = new Translate(0f, 0f); item.Pause(); }
            }).Every(16);
        }

        static bool IsInside(VisualElement el, VisualElement ancestor)
        {
            while (el != null) { if (el == ancestor) return true; el = el.parent; }
            return false;
        }

        static VisualElement FindAncestorWithClass(VisualElement el, string cls, VisualElement stopAt)
        {
            while (el != null && el != stopAt)
            {
                if (el.ClassListContains(cls)) return el;
                el = el.parent;
            }
            return null;
        }

        // ── 派发(对应 assemble.dispatch)────────────────────────────────
        public void Dispatch(Dictionary<string, object> ev)
        {
            var guards = Get(ev, "guard") as List<object>;
            if (!GuardOk(guards))
            {
                // 以前这里对玩家是**彻底的沉默**:协议没勾就点"开始",界面毫无反应。
                Wiggle(_lastPressed);
                FlowAction gf;
                if (_actions.TryGetValue("onGuardFail", out gf)) gf(null, ev);
                return;
            }
            var doName = Get(ev, "do") as string;
            var arg = Get(ev, "arg");
            switch (doName)
            {
                case "openModal": OpenModal(arg as string, CurveForEvent(ev)); break;
                case "closeModal": CloseModal(CurveForEvent(ev)); break;
                case "toggleFlag":
                    var flag = arg as string;
                    if (flag != null)
                    {
                        object cur; State.TryGetValue(flag, out cur);
                        SetFlag(flag, !Truthy(cur));
                    }
                    break;
                case "send":
                    FlowAction send;
                    if (_actions.TryGetValue("send", out send)) send(arg, ev);
                    else Debug.LogWarning("[FlowBinder] send 未注册(IAppHook.RegisterActions 里注册)");
                    break;
                default:
                    FlowAction fn;
                    if (doName != null && _actions.TryGetValue(doName, out fn)) fn(arg, ev);
                    else Debug.LogWarning("[FlowBinder] 未知 action: " + doName);
                    break;
            }
        }

        // ── 通用绑定:checkbox 双态(对应 assemble.syncBindings)──────────
        public void SyncBindings()
        {
            var bindings = Get(_flow, "bindings") as Dictionary<string, object>;
            var cb = bindings != null ? Get(bindings, "checkbox") as Dictionary<string, object> : null;
            if (cb != null && _baseLayer != null)
            {
                var box = BaseQ(Get(cb, "el") as string);
                if (box != null)
                {
                    object fv; State.TryGetValue(Get(cb, "flag") as string ?? "", out fv);
                    bool on = Truthy(fv);
                    box.style.backgroundColor = ParseCssColor(
                        (on ? Get(cb, "checkedBg") : Get(cb, "uncheckedBg")) as string,
                        on ? Color.white : new Color(1f, 1f, 1f, 0.2f));

                    // VisualElement 没有 text:勾号用子 Label(首次补建,居中铺满)
                    var mark = box.Q<Label>("flow-check-mark");
                    if (mark == null)
                    {
                        mark = new Label { name = "flow-check-mark" };
                        mark.style.position = Position.Absolute;
                        mark.style.left = 0; mark.style.top = 0;
                        mark.style.right = 0; mark.style.bottom = 0;
                        mark.style.unityTextAlign = TextAnchor.MiddleCenter;
                        mark.style.fontSize = 24;
                        mark.style.unityFontStyleAndWeight = FontStyle.Bold;
                        mark.pickingMode = PickingMode.Ignore;   // 点击穿透给 box(box 上绑 toggleFlag)
                        box.Add(mark);
                    }
                    mark.style.color = ParseCssColor(Get(cb, "markColor") as string, new Color(0.106f, 0.298f, 0.341f));
                    mark.text = on ? ((Get(cb, "mark") as string) ?? "✓") : "";
                }
            }
            if (SyncBindingsHook != null) SyncBindingsHook(_baseLayer);
        }

        // ── 列表:模板行克隆 + 回调填充(对应 assemble.renderRows)──────────
        // 注意:UI Toolkit 无 VisualElement 深克隆,这里"克隆"=重新实例化该 cap 的
        // VisualTreeAsset、抽出模板行(带样式表)。请在布局完成后调用(IAppHook.Init
        // 中可用 schedule.Execute 延一帧),因为行距采样读 resolvedStyle。
        public void RenderRows(string modalName, string containerId, int count, Action<VisualElement, int> fillRow)
        {
            ModalInfo m;
            if (!_modals.TryGetValue(modalName, out m)) { Debug.LogWarning("[FlowBinder] 弹窗未找到: " + modalName); return; }
            var container = m.layer.Q(SafeName(containerId));
            if (container == null) { Debug.LogWarning("[FlowBinder] 列表容器未找到: " + containerId); return; }

            var key = modalName + "/" + containerId;
            ListInfo info;
            if (!_listInfo.TryGetValue(key, out info) || !info.sampled)
            {
                var rows = new List<VisualElement>(container.Children());
                if (rows.Count == 0) { Debug.LogWarning("[FlowBinder] 无模板行: " + containerId); return; }
                info = new ListInfo { templateName = rows[0].name, sampled = true };
                info.baseTop = rows[0].resolvedStyle.top;
                info.step = rows.Count > 1
                    ? rows[1].resolvedStyle.top - info.baseTop
                    : Math.Max(1f, rows[0].resolvedStyle.height);
                _listInfo[key] = info;
            }

            container.Clear();
            container.style.overflow = Overflow.Hidden;   // USS 无滚动,溢出裁切;滚动可由 hook 换 ScrollView
            for (int i = 0; i < count; i++)
            {
                var row = CloneRow(m.capName, info.templateName);
                if (row == null) return;
                row.style.top = info.baseTop + i * info.step;
                row.AddToClassList("flow-row");           // 等价 data-row,行点击委托靠它识别
                if (fillRow != null) fillRow(row, i);
                container.Add(row);
                StaggerIn(row, i);
            }
        }

        /// <summary>逐项入场:全部同时出现 = 一整块东西闪进来,量感全无;错开一点才读得出"有几条"。</summary>
        void StaggerIn(VisualElement row, int index)
        {
            var cfg = _motionCfg != null ? Get(_motionCfg, "stagger") as Dictionary<string, object> : null;
            Curve c;
            if (cfg == null || !_curves.TryGetValue("stagger", out c)) return;
            float step = (cfg.ContainsKey("step") ? Num(Get(cfg, "step")) : 45f) / 1000f;
            float from = cfg.ContainsKey("from") ? Num(Get(cfg, "from")) : 24f;
            row.style.opacity = 0f;
            row.schedule.Execute(() =>
                Play(row, c, false, (e, v) =>
                {
                    e.style.opacity = v;
                    e.style.translate = new Translate(0f, from * (1f - v));
                }, null)
            ).StartingIn((long)(index * step * 1000));
        }

        VisualElement CloneRow(string capName, string templateName)
        {
            if (capName == null || !_assets.ContainsKey(capName)) return null;
            var tc = _assets[capName].Instantiate();
            var row = tc.Q(templateName);
            if (row == null) { Debug.LogWarning("[FlowBinder] 模板行未找到: " + templateName); return null; }
            var sheets = CollectStyleSheets(tc);
            row.RemoveFromHierarchy();
            foreach (var ss in sheets) row.styleSheets.Add(ss);
            return row;
        }

        // ── 辅助:flow dict 取值 / CSS 颜色解析 ──────────────────────────
        static object Get(Dictionary<string, object> d, string key)
        {
            object v; return d != null && d.TryGetValue(key, out v) ? v : null;
        }
        static object Get(Dictionary<string, object> d, string k1, string k2)
        {
            return Get(Get(d, k1) as Dictionary<string, object>, k2);
        }
        static float GetNum(object v, float dft) { return v is double ? (float)(double)v : dft; }

        /// <summary>解析 IR 里的 CSS 颜色字符串:rgba(r,g,b,a) / rgb(r,g,b) / #rrggbb[aa]。</summary>
        public static Color ParseCssColor(string s, Color fallback)
        {
            if (string.IsNullOrEmpty(s)) return fallback;
            s = s.Trim();
            try
            {
                if (s.StartsWith("rgb"))
                {
                    int lp = s.IndexOf('('), rp = s.LastIndexOf(')');
                    if (lp < 0 || rp <= lp) return fallback;
                    var parts = s.Substring(lp + 1, rp - lp - 1).Split(',');
                    if (parts.Length < 3) return fallback;
                    float r = float.Parse(parts[0], CultureInfo.InvariantCulture) / 255f;
                    float g = float.Parse(parts[1], CultureInfo.InvariantCulture) / 255f;
                    float b = float.Parse(parts[2], CultureInfo.InvariantCulture) / 255f;
                    float a = parts.Length > 3 ? float.Parse(parts[3], CultureInfo.InvariantCulture) : 1f;
                    return new Color(r, g, b, a);
                }
                if (s.StartsWith("#"))
                {
                    Color c;
                    if (ColorUtility.TryParseHtmlString(s, out c)) return c;
                }
            }
            catch (FormatException) { /* 落到 fallback */ }
            return fallback;
        }

        // ── MiniJson:极简 JSON 解析器(JsonUtility 不支持字典/异构数组,flow.json 需要)──
        // object → Dictionary<string,object>;array → List<object>;
        // number → double;其余 → string / bool / null。只解析,不序列化。
        static class MiniJson
        {
            public static object Parse(string json)
            {
                int i = 0;
                var v = ParseValue(json, ref i);
                SkipWs(json, ref i);
                return v;
            }

            static void SkipWs(string s, ref int i)
            {
                while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++;
            }

            static object ParseValue(string s, ref int i)
            {
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("JSON 意外结束");
                char c = s[i];
                if (c == '{') return ParseObject(s, ref i);
                if (c == '[') return ParseArray(s, ref i);
                if (c == '"') return ParseString(s, ref i);
                if (c == 't') { Expect(s, ref i, "true"); return true; }
                if (c == 'f') { Expect(s, ref i, "false"); return false; }
                if (c == 'n') { Expect(s, ref i, "null"); return null; }
                return ParseNumber(s, ref i);
            }

            static void Expect(string s, ref int i, string word)
            {
                if (i + word.Length > s.Length || s.Substring(i, word.Length) != word)
                    throw new FormatException("JSON 非法字面量 @" + i);
                i += word.Length;
            }

            static Dictionary<string, object> ParseObject(string s, ref int i)
            {
                var d = new Dictionary<string, object>();
                i++; // {
                SkipWs(s, ref i);
                if (i < s.Length && s[i] == '}') { i++; return d; }
                while (true)
                {
                    SkipWs(s, ref i);
                    string key = ParseString(s, ref i);
                    SkipWs(s, ref i);
                    if (i >= s.Length || s[i] != ':') throw new FormatException("JSON 缺 ':' @" + i);
                    i++;
                    d[key] = ParseValue(s, ref i);
                    SkipWs(s, ref i);
                    if (i < s.Length && s[i] == ',') { i++; continue; }
                    if (i < s.Length && s[i] == '}') { i++; return d; }
                    throw new FormatException("JSON 对象未闭合 @" + i);
                }
            }

            static List<object> ParseArray(string s, ref int i)
            {
                var a = new List<object>();
                i++; // [
                SkipWs(s, ref i);
                if (i < s.Length && s[i] == ']') { i++; return a; }
                while (true)
                {
                    a.Add(ParseValue(s, ref i));
                    SkipWs(s, ref i);
                    if (i < s.Length && s[i] == ',') { i++; continue; }
                    if (i < s.Length && s[i] == ']') { i++; return a; }
                    throw new FormatException("JSON 数组未闭合 @" + i);
                }
            }

            static string ParseString(string s, ref int i)
            {
                if (s[i] != '"') throw new FormatException("JSON 期望字符串 @" + i);
                i++;
                var sb = new StringBuilder();
                while (i < s.Length)
                {
                    char c = s[i++];
                    if (c == '"') return sb.ToString();
                    if (c == '\\' && i < s.Length)
                    {
                        char e = s[i++];
                        switch (e)
                        {
                            case '"': sb.Append('"'); break;
                            case '\\': sb.Append('\\'); break;
                            case '/': sb.Append('/'); break;
                            case 'b': sb.Append('\b'); break;
                            case 'f': sb.Append('\f'); break;
                            case 'n': sb.Append('\n'); break;
                            case 'r': sb.Append('\r'); break;
                            case 't': sb.Append('\t'); break;
                            case 'u':
                                if (i + 4 > s.Length) throw new FormatException("JSON \\u 不完整");
                                sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                                i += 4;
                                break;
                            default: throw new FormatException("JSON 非法转义 \\" + e);
                        }
                    }
                    else sb.Append(c);
                }
                throw new FormatException("JSON 字符串未闭合");
            }

            static object ParseNumber(string s, ref int i)
            {
                int start = i;
                while (i < s.Length && ("+-0123456789.eE".IndexOf(s[i]) >= 0)) i++;
                if (i == start) throw new FormatException("JSON 非法字符 @" + i);
                return double.Parse(s.Substring(start, i - start), CultureInfo.InvariantCulture);
            }
        }
    }
}
