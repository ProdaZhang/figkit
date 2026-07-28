# -*- coding: utf-8 -*-
"""合成 kitchen-sink 夹具:一屏打满 IR 的全部视觉特性,供跨后端一致性测试用。

**为什么要它**:此前唯一的跨后端共享夹具是 login 三屏(24 个元素),实测只覆盖
radius / border / stageBg —— shadow / blur / rot / opacity / img / vec / gradient /
text-stroke / 百分比圆角**全部零覆盖**。也就是说"一份 IR、六个后端"这句话,
只在 3/12 个特性上被真正交叉验证过;`radius:"50%"`(capture 对每个 ELLIPSE 都产)
在 godot 被整个丢掉、在 cocos 被当成 50px,就是这么漏出去的。

和 login 夹具一样,本文件构造 figma 节点树后喂给 `figma_capture.capture()`,
走的是与真 figma 完全同一条捕获管线,所以产物 schema 天然正确。

用法: python3 tools/conformance/make_kitchen_sink.py   (产物 kitchen-sink.ui.json,确定性)
"""
import base64
import io
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE)) if os.path.basename(_HERE) != "conformance" \
    else os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "figma2html", "scripts"))
import figma_capture  # noqa: E402

C = lambda r, g, b: {"r": r, "g": g, "b": b}          # noqa: E731
BOX = lambda x, y, w, h: {"x": x, "y": y, "width": w, "height": h}   # noqa: E731


def _n(nid, name, typ, x, y, w, h, **kw):
    n = {"id": nid, "name": name, "type": typ, "visible": True,
         "absoluteBoundingBox": BOX(x, y, w, h)}
    n.update(kw)
    return n


def solid(c, a=1):
    return [{"type": "SOLID", "visible": True, "color": c, "opacity": a}]


def build_tree():
    """每个子节点针对一个 IR 特性,id 与特性一一对应(测试按 id 定位)。"""
    kids = [
        # radius:像素四角简写
        _n("k:radius-px", "radius-px", "RECTANGLE", 40, 40, 200, 120,
           fills=solid(C(.9, .3, .3)), rectangleCornerRadii=[4, 8, 12, 16]),

        # radius:百分比(ELLIPSE → capture 强制产 "50%")
        _n("k:radius-pct", "radius-pct", "ELLIPSE", 280, 40, 120, 120,
           fills=solid(C(.2, .7, .4))),
        # 百分比 + 非正方形:各后端对 min(w,h) 的口径必须一致
        _n("k:radius-pct-oblong", "radius-pct-oblong", "ELLIPSE", 440, 40, 300, 80,
           fills=solid(C(.2, .5, .8))),

        # border(描边)
        _n("k:border", "border", "RECTANGLE", 40, 200, 200, 120,
           fills=solid(C(1, 1, 1)), cornerRadius=10,
           strokes=[{"type": "SOLID", "visible": True, "color": C(.1, .1, .1)}],
           strokeWeight=4),

        # shadow(DROP_SHADOW)
        _n("k:shadow", "shadow", "RECTANGLE", 280, 200, 200, 120,
           fills=solid(C(1, .85, .2)), cornerRadius=12,
           effects=[{"type": "DROP_SHADOW", "visible": True,
                     "offset": {"x": 0, "y": 6}, "radius": 12,
                     "color": {"r": 0, "g": 0, "b": 0, "a": .5}}]),

        # blur(LAYER_BLUR)
        _n("k:blur", "blur", "RECTANGLE", 520, 200, 200, 120,
           fills=solid(C(.6, .3, .9)),
           effects=[{"type": "LAYER_BLUR", "visible": True, "radius": 8}]),

        # rot(relativeTransform 反解角度)+ opacity
        _n("k:rot", "rot", "RECTANGLE", 40, 360, 120, 120,
           fills=solid(C(.95, .5, .1)),
           relativeTransform=[[math.cos(math.radians(45)), -math.sin(math.radians(45)), 40],
                              [math.sin(math.radians(45)), math.cos(math.radians(45)), 360]]),
        _n("k:opacity", "opacity", "RECTANGLE", 200, 360, 120, 120,
           fills=solid(C(.1, .6, .6)), opacity=0.4),

        # gradient:线性 + 径向
        _n("k:gradient-linear", "gradient-linear", "RECTANGLE", 360, 360, 200, 120,
           fills=[{"type": "GRADIENT_LINEAR", "visible": True,
                   "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
                   "gradientStops": [{"color": {"r": 1, "g": 0, "b": 0, "a": 1}, "position": 0},
                                     {"color": {"r": 0, "g": 0, "b": 1, "a": 1}, "position": 1}]}]),
        _n("k:gradient-radial", "gradient-radial", "RECTANGLE", 600, 360, 160, 120,
           fills=[{"type": "GRADIENT_RADIAL", "visible": True,
                   "gradientStops": [{"color": {"r": 1, "g": 1, "b": 1, "a": 1}, "position": 0},
                                     {"color": {"r": 0, "g": 0, "b": 0, "a": 1}, "position": 1}]}]),

        # img:三种 scaleMode(cover / contain / tile)—— 素材缺失时 capture 记 missing,
        # 这正是要测的:各后端对"声明了图但文件不在"的降级是否一致。
        _n("k:img-cover", "img-cover", "RECTANGLE", 40, 520, 160, 120,
           fills=[{"type": "IMAGE", "visible": True, "scaleMode": "FILL", "imageRef": "ks-a"}]),
        _n("k:img-contain", "img-contain", "RECTANGLE", 220, 520, 160, 120,
           fills=[{"type": "IMAGE", "visible": True, "scaleMode": "FIT", "imageRef": "ks-b"}]),
        _n("k:img-tile", "img-tile", "RECTANGLE", 400, 520, 160, 120,
           fills=[{"type": "IMAGE", "visible": True, "scaleMode": "TILE", "imageRef": "ks-c"}]),

        # text:基础 + 描边(-webkit-text-stroke)+ 多行(换行策略)
        _n("k:text", "text", "TEXT", 40, 680, 400, 60, characters="Plain text",
           fills=solid(C(0, 0, 0)),
           style={"fontSize": 32, "fontWeight": 400, "fontFamily": "Inter",
                  "textAlignHorizontal": "LEFT", "textAlignVertical": "CENTER",
                  "letterSpacing": 2, "lineHeightPx": 40}),
        _n("k:text-stroke", "text-stroke", "TEXT", 460, 680, 400, 60,
           characters="Stroked", fills=solid(C(1, 1, 1)),
           strokes=[{"type": "SOLID", "visible": True, "color": C(0, 0, 0)}], strokeWeight=3,
           style={"fontSize": 32, "fontWeight": 700, "fontFamily": "Inter",
                  "textAlignHorizontal": "CENTER", "textAlignVertical": "CENTER"}),
        _n("k:text-multiline", "text-multiline", "TEXT", 40, 760, 400, 100,
           characters="line one\nline two", fills=solid(C(.2, .2, .2)),
           style={"fontSize": 24, "fontWeight": 400, "fontFamily": "Inter",
                  "textAlignHorizontal": "LEFT", "textAlignVertical": "TOP"}),

        # vec:纯矢量簇(无文字子)→ capture 折叠成一张图并打 vec=true
        _n("k:vec", "vec-cluster", "GROUP", 600, 520, 140, 120, children=[
            _n("k:vec-leaf", "vec-leaf", "VECTOR", 610, 530, 120, 100,
               fills=solid(C(.9, .9, .2)))]),

        # 嵌套容器:父子几何换算(render.js pass2 的相对坐标)
        _n("k:nest", "nest", "FRAME", 500, 760, 240, 140, fills=solid(C(.95, .95, .9)),
           cornerRadius=8, children=[
               _n("k:nest-child", "nest-child", "RECTANGLE", 540, 800, 100, 60,
                  fills=solid(C(.3, .3, .3)), cornerRadius=6)]),
    ]
    # 帧底:渐变 stageBg(另一条与元素 fill 不同的路径)
    return _n("k:frame", "kitchen-sink", "FRAME", 0, 0, 800, 940,
              fills=[{"type": "GRADIENT_LINEAR", "visible": True,
                      "gradientHandlePositions": [{"x": 0, "y": 0}, {"x": 0, "y": 1}],
                      "gradientStops": [
                          {"color": {"r": .05, "g": .1, "b": .15, "a": 1}, "position": 0},
                          {"color": {"r": .15, "g": .2, "b": .25, "a": 1}, "position": 1}]}],
              children=kids)


# 1x1 透明 PNG(67 字节)。素材文件必须真实存在,否则 capture 把图片填充记成 missing、
# img 字段为空 —— 那样就测不到 img 与三种 imgSize 了。内容无所谓,存在与否才是关键。
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
ASSET_NAMES = ("ks-a.png", "ks-b.png", "ks-c.png", "nk_vec.png")


def _write_assets(d):
    if not os.path.isdir(d):
        os.makedirs(d)
    for fn in ASSET_NAMES:
        p = os.path.join(d, fn)
        with open(p, "wb") as f:
            f.write(_PNG_1x1)


def main():
    assets = os.path.join(_HERE, "assets")
    _write_assets(assets)
    cap, missing = figma_capture.capture(build_tree(), assets, "assets")
    out = os.path.join(_HERE, "kitchen-sink.ui.json")
    with io.open(out, "w", encoding="utf-8", newline="") as f:
        json.dump(cap, f, ensure_ascii=False, indent=1)
    print("wrote kitchen-sink.ui.json (%d els, %dx%d, %d missing-asset)"
          % (len(cap["els"]), cap["w"], cap["h"], len(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
