# -*- coding: utf-8 -*-
"""figma_capture 冒烟/回归:合成节点树夹具 -> 断言产出的 ui.json records。

确定性、无外部依赖(不需 figma token / 不需 Edge / 不需真 PNG):用不存在的素材目录,
所有 PNG 视为缺失,正好覆盖"资产感知折叠缺图回退透明"这条核心规则。
对标 figma2dsl 的 test_baseline —— 守住 capture(全保真捕获)这个核,改坏即红。
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import figma_capture as fc

NOASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '__noassets__')  # 不存在 → 所有 PNG 缺失
ASSET_REL = '_assets/test'


def _rect(nid, x, y, w, h, **kw):
    n = {"id": nid, "type": "RECTANGLE", "visible": True,
         "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
         "fills": [{"type": "SOLID", "visible": True, "color": {"r": 1, "g": 1, "b": 1, "a": 1}}]}
    n.update(kw)
    return n


def _frame(children, w=1080, h=1920, fills=None):
    # 帧原点放在 (100,200),用来验证几何转成"相对帧原点"的绝对 px
    return {"id": "0:1", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 100, "y": 200, "width": w, "height": h},
            "fills": fills if fills is not None else
            [{"type": "SOLID", "visible": True, "color": {"r": 0.2, "g": 0.4, "b": 0.6, "a": 1}}],
            "children": children}


def test_capture_geometry_styles_and_stagebg():
    rect = _rect("1:2", 160, 260, 200, 80, cornerRadius=16)
    text = {"id": "1:3", "type": "TEXT", "visible": True, "characters": "开始游戏",
            "absoluteBoundingBox": {"x": 180, "y": 300, "width": 160, "height": 40},
            "fills": [{"type": "SOLID", "visible": True, "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
            "style": {"fontSize": 28, "fontFamily": "Noto Sans SC", "fontWeight": 700,
                      "textAlignHorizontal": "CENTER", "textAlignVertical": "CENTER"}}
    ell = {"id": "1:4", "type": "ELLIPSE", "visible": True,
           "absoluteBoundingBox": {"x": 160, "y": 360, "width": 40, "height": 40},
           "fills": [{"type": "SOLID", "visible": True, "color": {"r": 1, "g": 0, "b": 0, "a": 1}}]}
    cap, missing = fc.capture(_frame([rect, text, ell]), NOASSET, ASSET_REL)

    assert cap["w"] == 1080 and cap["h"] == 1920, (cap["w"], cap["h"])
    assert cap["stageBg"] == "rgba(51,102,153,1)", cap["stageBg"]   # 帧纯色填充 → stageBg
    by = {e["id"]: e for e in cap["els"]}
    assert set(by) == {"1:2", "1:3", "1:4"}, list(by)

    # 几何相对帧原点(100,200)
    assert by["1:2"]["x"] == 60 and by["1:2"]["y"] == 60, (by["1:2"]["x"], by["1:2"]["y"])
    assert by["1:2"]["radius"] == "16px", by["1:2"]["radius"]
    assert by["1:2"]["fill"] == "rgba(255,255,255,1)", by["1:2"]["fill"]
    # ELLIPSE → 圆
    assert by["1:4"]["radius"] == "50%", by["1:4"]["radius"]
    assert by["1:4"]["fill"] == "rgba(255,0,0,1)", by["1:4"]["fill"]
    # TEXT
    t = by["1:3"]["text"]
    assert t is not None and t["content"] == "开始游戏", t
    assert t["size"] == 28 and t["weight"] == 700, (t["size"], t["weight"])
    assert by["1:3"]["x"] == 80, by["1:3"]["x"]   # 180-100


def test_capture_asset_aware_collapse_missing_png():
    # 纯矢量簇(无文字、无可渲染形状)缺 PNG → 整簇折叠成单个透明占位(vec=True, img=''),不平涂黑、不展开
    veccluster = {"id": "2:1", "type": "GROUP", "visible": True,
                  "absoluteBoundingBox": {"x": 110, "y": 210, "width": 50, "height": 50},
                  "children": [{"id": "2:2", "type": "VECTOR", "visible": True,
                                "absoluteBoundingBox": {"x": 110, "y": 210, "width": 50, "height": 50}}]}
    cap, missing = fc.capture(_frame([veccluster]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}
    assert "2:1" in by, list(by)
    assert by["2:1"]["vec"] is True and by["2:1"]["img"] == "", by["2:1"]
    assert len(cap["els"]) == 1, [e["id"] for e in cap["els"]]   # 折叠成一个占位,不递归展开 2:2
    assert any(m[0] == "2:1" for m in missing)                    # 缺图被登记


def test_rotation_from_relativeTransform_and_instance_fallback():
    # 有 relativeTransform(旋转 45°)→ rot 捕获;无 relativeTransform(模拟实例内部节点)→ rot 回退 0
    c, s = math.cos(math.radians(45)), math.sin(math.radians(45))
    rot_node = _rect("3:1", 300, 400, 40, 40, relativeTransform=[[c, -s, 0], [s, c, 0]], size={"x": 40, "y": 40})
    flat_node = _rect("3:2", 500, 400, 40, 40)   # 无 relativeTransform
    cap, _ = fc.capture(_frame([rot_node, flat_node]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}
    assert abs(by["3:1"]["rot"] - 45) < 1.0, by["3:1"]["rot"]
    assert by["3:2"]["rot"] == 0, by["3:2"]["rot"]   # 缺 relativeTransform → 0(figma API 限制,非 bug)


def test_rec_to_css_whitespace_matches_render_js():
    # ③ 防漂移:rec_to_css 单行用 nowrap、多行(含 \n)用 pre-wrap,与 render.js applyRecStyle 一致。
    base = {"id": "x", "name": "t", "type": "TEXT", "x": 0, "y": 0, "w": 10, "h": 10, "z": 1, "rot": 0,
            "opacity": 1, "radius": "", "border": "", "shadow": "", "blur": "", "fill": "", "img": "", "imgSize": "",
            "text": {"content": "单行", "color": "#000", "size": 14, "family": "X", "weight": 400, "lh": 0, "ls": 0,
                     "alignH": "center", "alignV": "center", "textAlign": "center", "stroke": ""}}
    single_css = fc.rec_to_css(base)
    multi = {**base, "text": {**base["text"], "content": "第一行\n第二行"}}
    multi_css = fc.rec_to_css(multi)
    assert "white-space:nowrap" in single_css, single_css
    assert "white-space:pre-wrap" in multi_css, multi_css


def _run():
    ok = True
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except Exception as e:
                ok = False; print("FAIL", name, repr(e))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
