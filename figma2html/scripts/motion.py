# -*- coding: utf-8 -*-
"""motion.py — 把 IR 里的转场缓动解成**引擎能吃的采样曲线**。纯标准库,零依赖。

**为什么不能各后端各自映射到引擎内置枚举。** figma 给的是一条具体曲线
(`cubic-bezier(.32,.72,0,1)`)或一组弹簧参数;DOTween / Godot 的 `Tween.EASE_*` /
USS 的 easing 关键字给的是**另一套曲线**,同名不同形。各后端各挑一个"最像的枚举",
结果就是同一份 IR 在六个引擎里手感不同 —— 而所有测试都是绿的(这正是 v0.2.0 抓到
`radius:"50%"` 那个 bug 的形状:每家跟自己的期望比,没人跟别家比)。
所以这里只做一件事:**把曲线采成点**,各后端喂给自己的曲线资源,
再由 tools/conformance 断言各家采出来的数**逐点一致**。

lineage:算法取自我自己那份动效规范的「§四-1 cubic-bezier 求解器 / §四-2 弹簧解析解」。
两处**有意的改动**,原因都在下面对应函数里:
  1. 牛顿迭代改成**固定步数**(不提前退出)—— 提前退出的步数依赖 libm 的最后一位,
     三平台 CI 会各走各的步数,而 golden 是逐字节比对的。
  2. figma 给的弹簧是 {mass, stiffness, damping} 三元组,先换算成解耦的(阻尼比, response)
     再解 —— 三元组互相纠缠,调一个会同时改快慢和弹性,不适合当设计层旋钮。
"""
import math

# figma 的具名缓动 → cubic-bezier 控制点。
# **只列 CSS 规范里有normative 定义的那四条**(figma 这四个名字与 CSS 同义):
# 其余(*_BACK 的过冲曲线、GENTLE/QUICK/BOUNCY/SLOW 这几个弹簧预设)figma 没有公开
# 控制点,**这里就不编**。编一组"差不多的"数进来,产物会看起来完全正常而手感是错的 ——
# 那比解不出来贵得多。解不出来时走 UNRESOLVED,由调用方登记成 known-loss。
# (真拿到 figma 文件核出来的话,补进这张表即可,别改别处。)
CSS_EQUIV = {
    "LINEAR":          (0.0,  0.0, 1.0,  1.0),
    "EASE_IN":         (0.42, 0.0, 1.0,  1.0),
    "EASE_OUT":        (0.0,  0.0, 0.58, 1.0),
    "EASE_IN_AND_OUT": (0.42, 0.0, 0.58, 1.0),
}

BEZIER, SPRING, UNRESOLVED = "bezier", "spring", "unresolved"

# 采样点数。曲线资源用等距采样重建,点太少还原不出过冲的峰。
# 16 段(17 个点)对 easeOutBack 量级的过冲已经足够,且 golden 不会大到没法读。
SAMPLES = 17

NEWTON_STEPS = 12        # 见模块 docstring 第 1 条:固定步数 = 跨平台可复现


def resolve_easing(easing):
    """IR 的 easing dict → (kind, payload)。不猜、不回退到"差不多的那条"。"""
    e = easing or {}
    cb = e.get("bezier")
    if cb and len(cb) == 4:
        return BEZIER, tuple(float(v) for v in cb)
    sp = e.get("spring")
    if sp:
        return SPRING, (float(sp.get("mass", 1)), float(sp.get("stiffness", 100)),
                        float(sp.get("damping", 10)))
    name = e.get("type", "LINEAR")
    if name in CSS_EQUIV:
        return BEZIER, CSS_EQUIV[name]
    return UNRESOLVED, name


def bezier_solver(x1, y1, x2, y2):
    """cubic-bezier(x1,y1,x2,y2) → f(时间进度 0..1) = 动画进度。

    ⚠️ `t` 是曲线参数,不是时间:必须先由时间进度 x **反解** t,再算 y。这步没有闭式解。
    ❌ 别拿"差不多的近似式"凑合 —— easeOutCubic 与 cubic-bezier(.23,1,.32,1) 最大差
       19.8 个百分点,且差在 x≈0.23(起步、玩家盯得最紧的那段)。
    """
    cx = 3.0 * x1
    bx = 3.0 * (x2 - x1) - cx
    ax = 1.0 - cx - bx
    cy = 3.0 * y1
    by = 3.0 * (y2 - y1) - cy
    ay = 1.0 - cy - by

    def sample_x(t):
        return ((ax * t + bx) * t + cx) * t

    def sample_y(t):
        return ((ay * t + by) * t + cy) * t

    def slope_x(t):
        return (3.0 * ax * t + 2.0 * bx) * t + cx

    def f(x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        t = x
        for _ in range(NEWTON_STEPS):          # 固定步数,不提前退出(见 docstring)
            d = slope_x(t)
            if abs(d) < 1e-9:                  # 斜率塌了,牛顿不可用 → 二分兜底
                lo, hi, t = 0.0, 1.0, x
                for _ in range(48):
                    if sample_x(t) > x:
                        hi = t
                    else:
                        lo = t
                    t = (lo + hi) / 2.0
                break
            t -= (sample_x(t) - x) / d
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        return sample_y(t)

    return f


def spring_params(mass, stiffness, damping):
    """figma 的 {mass, stiffness, damping} → (阻尼比 zeta, 固有频率 omega0, response 秒)。

    为什么要换:三元组**互相纠缠** —— 调大 stiffness 会同时变快又变弹,想只改一样得同时
    动两个。设计层该用解耦的两参:`zeta` 只管弹不弹,`response` 只管多快到位。
        omega0 = sqrt(k/m)          zeta = c / (2·sqrt(k·m))        response = 2π/omega0
    ⚠️ `response` 不是 duration —— 弹簧没有固定时长,停下来的时刻是参数涌现出来的。
    """
    mass = max(float(mass), 1e-9)
    stiffness = max(float(stiffness), 1e-9)
    omega0 = math.sqrt(stiffness / mass)
    zeta = float(damping) / (2.0 * math.sqrt(stiffness * mass))
    return zeta, omega0, (2.0 * math.pi / omega0)


def spring_solver(mass, stiffness, damping):
    """→ f(t 秒) = 位移进度(0 起、1 为目标)。解析解,分三种阻尼情形。

    ⚠️ **别用半隐式欧拉**。在 w0·dt ≈ 0.35 量级(response 0.3 / 60fps)它的数值阻尼会把
    zeta=0.8 该有的过冲整个吃掉,而你从产物上看不出来 —— "带弹性"变成"不带弹性",静默。
    """
    zeta, w0, _ = spring_params(mass, stiffness, damping)

    def f(t):
        if t <= 0.0:
            return 0.0
        if zeta < 1.0 - 1e-9:                                   # 欠阻尼:会过冲、会振荡
            wd = w0 * math.sqrt(1.0 - zeta * zeta)
            return 1.0 - math.exp(-zeta * w0 * t) * (
                math.cos(wd * t) + (zeta * w0 / wd) * math.sin(wd * t))
        if zeta <= 1.0 + 1e-9:                                  # 临界阻尼:最快且不过冲
            return 1.0 - math.exp(-w0 * t) * (1.0 + w0 * t)
        s = math.sqrt(zeta * zeta - 1.0)                        # 过阻尼:两个实根,爬过去
        r1, r2 = -w0 * (zeta - s), -w0 * (zeta + s)
        return 1.0 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)

    return f


def settle_time(mass, stiffness, damping, eps=0.001):
    """弹簧衰减到距目标 eps 以内所需的秒数(包络 e^(-zeta·w0·t) 的解析上界)。

    用来判断 IR 给的 duration 是否**截断**了这条弹簧 —— 截断是一种降级,要留痕,
    不能让"动画播到一半被切掉"看起来像正常结束。
    """
    zeta, w0, _ = spring_params(mass, stiffness, damping)
    decay = zeta * w0
    if decay <= 1e-9:
        return float("inf")                                     # 无阻尼:永远不停
    return -math.log(eps) / decay


def sample_curve(easing, duration_ms, n=SAMPLES):
    """(easing, 时长) → ([(x, y) …], notes[])。x/y 都是 0..1 的归一化进度。

    这是**唯一**的对外入口:各后端只调它,于是"各家采出来的数一致"是构造上成立的,
    再由 conformance 逐点验一遍。返回值四舍五入到 6 位 —— 三平台 libm 的末位差异
    远小于 5e-7,跨平台 golden 因此逐字节可复现。
    """
    kind, payload = resolve_easing(easing)
    notes = []
    if kind == UNRESOLVED:
        return [], ["unresolved: easing '%s' 没有公开的控制点(figma 未给 bezier/spring),不采样"
                    % payload]
    if kind == BEZIER:
        f = bezier_solver(*payload)
        pts = [(i / float(n - 1), f(i / float(n - 1))) for i in range(n)]
    else:
        mass, stiffness, damping = payload
        dur_s = max(float(duration_ms), 1.0) / 1000.0
        g = spring_solver(mass, stiffness, damping)
        pts = [(i / float(n - 1), g(dur_s * i / float(n - 1))) for i in range(n)]
        need = settle_time(mass, stiffness, damping)
        if need > dur_s:
            notes.append("truncated: 弹簧在 %.0fms 内没停(还要 %.0fms 才收敛到 0.1%%),"
                         "曲线被 duration 截断"
                         % (dur_s * 1000, (need - dur_s) * 1000))
        zeta = spring_params(mass, stiffness, damping)[0]
        if zeta >= 1.0:
            notes.append("no-overshoot: 阻尼比 %.2f ≥ 1 = 临界/过阻尼,这条弹簧**不会过冲**"
                         "(是数学,不是口味)" % zeta)
    return [(round(x, 6), round(y, 6)) for x, y in pts], notes


def bake_flow(flow, generator):
    """flow dict → (motion.json 内容, notes[])。**烘焙也放在本文件里**,好让它跟着
    逐字节镜像一起走 —— 各后端只负责把返回值写盘,不各写一份烘焙逻辑(那正是会漂的地方)。

    key 用 `ev<i>`(flow.events 的下标):确定性、与 el 是不是数组无关。
    """
    out, notes = {}, []
    for i, ev in enumerate(flow.get("events") or []):
        tr = ev.get("transition")
        if not tr:
            continue
        key = "ev%d" % i
        pts, ns = sample_curve(tr.get("easing"), tr.get("duration", 0))
        entry = {
            "el": ev.get("el"), "do": ev.get("do"), "arg": ev.get("arg"),
            "type": tr.get("type"), "duration": tr.get("duration", 0),
            "figma": describe(tr.get("easing"), tr.get("duration", 0)),
            "points": [list(p) for p in pts],
        }
        if tr.get("direction"):
            entry["direction"] = tr["direction"]
        out[key] = entry
        for n in ns:
            notes.append("%s (%s): %s" % (key, entry["figma"], n))
        if not pts:
            entry["unresolved"] = True
    return {"_generated_by": generator,
            "_note": "sampled easing curves; x/y are 0..1 progress. Regenerate, never hand-edit.",
            "samples": SAMPLES, "curves": out}, notes


def describe(easing, duration_ms):
    """给日志 / 生成文件头注释用的一行人话。"""
    kind, payload = resolve_easing(easing)
    if kind == BEZIER:
        return "cubic-bezier(%g,%g,%g,%g) %dms" % (payload + (int(duration_ms),))
    if kind == SPRING:
        zeta, _, response = spring_params(*payload)
        return "spring(damping=%.2f, response=%.3fs) %dms" % (zeta, response, int(duration_ms))
    return "easing '%s' (unresolved)" % payload
