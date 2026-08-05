# -*- coding: utf-8 -*-
"""runtime/*.ts 的**源码级**守卫。

诚实边界:这不是行为验证 —— TS 运行时要 Creator 或 tsc + @cocos/creator-types 才跑得起来,
本套是纯标准库,跑不了。这里只钉住几条曾经出过事、且能在源码层确定性检出的规约。
真行为验证见 README 状态矩阵里 cocos 那格(TS 严格类型检查),以及将来在 Creator 里的实跑。

守的第一条 = 百分比圆角:capture 对**每个 figma ELLIPSE** 都产 `radius: "50%"`
(figma_capture.py 的 ELLIPSE 分支),而 JS 的 `parseFloat("50%")` 返回 **50** 不报错,
于是百分比会被静默当成 50px —— 错得还随元素尺寸变。修法是按 min(w,h) 折算,
口径与 figma2godot 一致。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(os.path.dirname(os.path.dirname(HERE)), "runtime")


def _src(name):
    with open(os.path.join(RUNTIME, name), encoding="utf-8") as f:
        return f.read()


def test_parse_radius_takes_element_size():
    """签名必须能拿到 w/h,否则百分比无从折算。"""
    m = re.search(r"export function parseRadius\(([^)]*)\)", _src("parse-css.ts"))
    assert m, "parse-css.ts 里找不到 parseRadius 的导出签名"
    args = m.group(1)
    assert "w" in args and "h" in args, "parseRadius 没有接收元素尺寸: %r" % args


def test_parse_radius_handles_percent_per_axis():
    """百分比必须**分轴**折算:水平半径按 w、垂直半径按 h(CSS Backgrounds §5.1)。

    只靠 parseFloat 会把 '50%' 静默读成 50px;而折成 `min(w,h)×50%` 的**单一圆半径**
    同样是错的 —— 邮件面板底部那条弧是个 2143×680、`radius:50%` 的真椭圆,
    按 min 折算会画成胶囊,顶弧被削平 38px(实机比对量出来的)。
    这条曾经写成"与 godot 同口径",但那个口径与 HTML 基准不一致:HTML 走 CSS,
    Unity 的 UI Toolkit 也按轴算,所以对齐对象应该是 CSS,不是另外两个后端的将就实现。
    """
    body = _src("parse-css.ts")
    m = re.search(r"export function parseRadius\(.*?\n\}", body, re.S)
    assert m, "抓不到 parseRadius 函数体"
    fn = m.group(0)
    assert "%" in fn and "endsWith" in fn, "parseRadius 没有处理百分比的分支"
    assert "Math.min" not in fn, "百分比不能折成 min(w,h) 的单一圆半径,CSS 是分轴的椭圆角"
    assert re.search(r"w\s*\*\s*n", fn) and re.search(r"h\s*\*\s*n", fn), \
        "百分比分支没有分别按 w 和 h 折算"


def test_call_site_passes_size():
    """改了签名却没改调用点,等于没修。"""
    calls = re.findall(r"parseRadius\(([^)]*)\)", _src("figma-ui.ts"))
    assert calls, "figma-ui.ts 里没有 parseRadius 调用"
    for c in calls:
        assert c.count(",") >= 2, "调用点没把尺寸传进去: parseRadius(%s)" % c


def test_motion_is_interpolated_not_re_solved():
    """引擎侧只做**线性**插值,一条曲线都不许自己算。

    Creator 的 `easing.quadOut` 之流与 figma 给的曲线**同名不同形**;各后端各挑"最像的",
    同一份 IR 就是六种手感,而每家测试照样绿(实测 easeOutCubic 与 cubic-bezier(.23,1,.32,1)
    最大差 19.8 个百分点)。曲线在 scripts/bake_motion.py 里解算,这里只插值。
    另:采样点一致只保证**关键帧上**一致,帧间插值模式必须也是线性 —— godot/unity 都在这儿栽过。
    """
    body = _src("flow-binder.ts")
    assert "function sampleCurve" in body, "flow-binder.ts 没有采样点插值函数"
    m = re.search(r"function sampleCurve\(.*?\n\}", body, re.S)
    assert m and "/" in m.group(0) and "-" in m.group(0), "sampleCurve 看着不像在做线性插值"
    imported = re.search(r"import\s*\{(.*?)\}\s*from\s*'cc'", body, re.S)
    names = [n.strip() for n in (imported.group(1) if imported else "").split(",")]
    for banned in ("easing", "tween", "Tween"):
        assert banned not in names, "从 cc 导入了 %s —— 内置缓动会与别家分叉" % banned


def test_transform_goes_on_the_panel_not_the_layer():
    """★ 位移/缩放只贴面板本体,遮罩只跟着淡。

    早先 html/godot/unity 三端同构同病:transform 贴在弹窗**层**上,而 backdrop 是层的子节点,
    于是遮罩跟着面板一起滑/缩 —— 顶部不变暗、四边缩进露出底屏。曲线取值一个不差,
    是实机截图才抓到的。这条守着 cocos 别再犯一遍。
    """
    body = _src("flow-binder.ts")
    m = re.search(r"private applyProgress\(.*?\n  \}", body, re.S)
    assert m, "抓不到 applyProgress 函数体"
    fn = m.group(0)
    assert "setOpacity(layer" in fn, "层上没有做整体淡入淡出"
    for bad in ("setScale(layer", "layer.setPosition"):
        assert bad not in fn, "%s:位移/缩放贴到层上了,遮罩会跟着动" % bad
    assert "scaleAboutCenter(panel" in fn and "panel.setPosition" in fn, \
        "面板本体没有承接位移/缩放"


def test_scaling_compensates_for_the_top_left_anchor():
    """锚点是 (0,1),node.scale 以左上角为基准 —— 不补位置,面板会往右下角坍缩。"""
    body = _src("flow-binder.ts")
    m = re.search(r"private scaleAboutCenter\(.*?\n  \}", body, re.S)
    assert m, "抓不到 scaleAboutCenter 函数体"
    fn = m.group(0)
    assert "setScale" in fn and "setPosition" in fn, "只设了 scale 没补位置"
    assert "(1 - s) / 2" in fn, "位置补偿不是 (1−s)/2 的形状"


def test_known_loss_paths_still_log():
    """known-loss 必须留痕,不许静默丢失(仓库通用原则)。"""
    body = _src("figma-ui.ts")
    assert "console.warn" in body, "figma-ui.ts 里一条 known-loss 告警都没有"


def test_no_array_literal_inside_a_conditional():
    """**数组字面量不能当三目/逻辑表达式的一支** —— Cocos 的构建器编不过。

    Creator 3.8.8 的 buildScriptCommand 走 Babel。`x ? a : [b]` / `f() || [b]` 这类写法,
    @babel/traverse 给数组字面量那一支推出 **Flow 的 GenericTypeAnnotation**,
    再拿去建 TSUnionType 就抛
    `Property types[1] of TSUnionType expected node to be of a type ["TSType"]`,
    **整份脚本编译失败**(不是这一行失败,是这个文件一行都进不去包)。

    tsc 那道类型门看不见它 —— 它根本不走 Babel。这条是 2026-08-05 第一次把 runtime
    真喂进 Cocos 构建器时才炸出来的,和 godot 的 sub_resource id、unity 的 USS 选择器
    同一类:静态检查全绿、真管线一跑就废。写成 if 就没事。
    """
    bad = []
    for name in ("figma-ui.ts", "flow-binder.ts", "parse-css.ts"):
        for i, line in enumerate(_src(name).splitlines(), 1):
            # 先剥注释和字符串/模板/正则字面量 —— 里头的 `?[` 是正则语法,不是三目
            code = re.sub(r"//.*$", "", line)
            code = re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", "S", code)
            code = re.sub(r"/(?:[^/\\\n]|\\.)+/[gimsuy]*", "S", code)
            if re.search(r"(\?\?|\?|\|\|)\s*\[\s*[\]\w'\"-]", code):
                bad.append("%s:%d %s" % (name, i, line.strip()))
    assert not bad, "三目/逻辑表达式里出现数组字面量(Cocos 构建器的 Babel 会崩):\n  " + "\n  ".join(bad)


def test_corners_never_use_graphics_arc():
    """**圆角不许用 `Graphics.arc`** —— 引擎那个 arc 有两处会咬人,画出来是撕碎的形状。

    引擎实现(`cocos/2d/utils/graphics.ts` 的 `arc`)里:
      ① 第一个点走 `ctx.moveTo(x, y)` —— **永远另起一条子路径**,不从当前点接上。
         于是"直边 lineTo + 四个角 arc"变成四段互不相连的子路径,fill 把它们并成
         一坨 → 圆角矩形被撕成斜楔(实机第一次跑出来的就是这个)。
      ② 方向约定与 canvas **相反**:`counterclockwise=false` 时它 `while (da > 0) da -= 2π`,
         按 canvas 语义传的 (-90°→0°, false) 被理解成 -270°,绕大圈 → 画出巨大的环。

    改用 `bezierCurveTo` + KAPPA:从当前点接着走,也没有方向歧义。
    这条和上面那条 Babel 一样,是**静态检查全绿、真引擎一跑才现形**的坑,所以钉在源码层。
    """
    bad = []
    for name in ("figma-ui.ts", "flow-binder.ts"):
        for i, line in enumerate(_src(name).splitlines(), 1):
            code = re.sub(r"//.*$", "", line)
            if re.search(r"\bg\w*\.arc\s*\(", code):
                bad.append("%s:%d %s" % (name, i, line.strip()))
    assert not bad, "用了 Graphics.arc(会另起子路径 + 方向相反,形状会碎):\n  " + "\n  ".join(bad)


def test_blurred_shadows_are_baked_not_dropped():
    """**带模糊的阴影不许再当 known-loss 丢掉。**

    Graphics 画不出模糊,所以这条曾经是"警告一声然后跳过" —— 而卡片式 UI 的投影
    几乎全是带模糊的,整片消失。现在与渐变同路:加载期烘一张纹理挂 `Sprite`。
    这里钉三件在真引擎里咬过人的细节:
      · 走 `uploadData` 的裸数据路径(`ImageAsset` 那条会每帧抛 texSubImage2D);
      · `trim = false` —— Creator 会裁掉 PNG 的透明边,而阴影几乎全是透明边,
        裁完再按 CUSTOM 拉满,投影就会被放大、错位;
      · 模糊用三次盒滤波近似高斯(σ = blur/2 是 CSS 自己的定义)。
    """
    body = _src("figma-ui.ts")
    assert "softShadowFrame" in body, "带模糊的阴影没有烘图那条路"
    m = re.search(r"function softShadowFrame[\s\S]*?\n}", body)
    assert m, "抓不到 softShadowFrame 函数体"
    fn = m.group(0)
    assert "uploadData" in fn, "纹理没走 uploadData 的裸数据路径"
    assert "boxSizes" in fn and "boxBlur" in fn, "模糊不是三次盒滤波近似高斯"
    assert "u.blur / 2" in fn, "σ 不是 blur/2(CSS 的口径)"
    ub = re.search(r"function buildUnderlay[\s\S]*?\n}", body)
    assert ub and "trim = false" in ub.group(0), "阴影 Sprite 没关 trim,透明边会被裁掉"
    assert "带模糊的阴影丢弃" not in body, "还留着'带模糊的阴影丢弃'的 known-loss 告警"


def test_zero_length_edges_are_never_emitted():
    """**胶囊的零长度直边不许发。**

    `radius = h/2` 时相邻两个圆角首尾相接,中间那条直边长度正好 0。照发就是一个
    **重复点**,而 Graphics 描边默认 MITER 接头,在重复点上算出的方向是退化的 ——
    沿边线支出一根尖刺。实测:绿色胶囊按钮左端只有中线那 5 行(y 1643–1647)向外
    鼓了 3px,其余每行都与设计稿逐像素重合。填充看不出来(重复点对三角化无所谓),
    **只有描边会炸**,所以这类 bug 只在"有 border 的胶囊"上现形。
    """
    body = _src("figma-ui.ts")
    m = re.search(r"function roundRectPath[\s\S]*?\n}", body)
    assert m, "抓不到 roundRectPath 函数体"
    fn = m.group(0)
    assert "g.lineTo(" not in fn.replace("if (Math.abs(nx - cx) > 1e-4 || Math.abs(ny - cy) > 1e-4) g.lineTo(nx, ny);", ""), \
        "roundRectPath 里还有裸 g.lineTo —— 零长度直边会被原样发出去"
    assert "1e-4" in fn, "没有零长度判据"


def test_text_stroke_is_halved():
    """IR 的描边宽度是 CSS `-webkit-text-stroke` 的口径:骑线、内外各半,里侧被字身盖住。
    `LabelOutline.width` 是往外画的,照抄整数就粗一倍(实测底栏页签墨量比 3.00,
    HTML 参照 1.90;取一半后 1.79)。"""
    body = _src("figma-ui.ts")
    assert re.search(r"outline\.width\s*=\s*st\.width\s*/\s*2", body), \
        "LabelOutline 宽度没取一半"


def _run():
    ok = True
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:
                ok = False; print("FAIL", n, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
