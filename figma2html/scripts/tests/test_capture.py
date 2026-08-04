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


def test_writable_shapes_are_never_baked_into_a_bitmap():
    """簇里只要有能直接写出来的形状,就**不许**整块折成图 —— 有没有 PNG 都不许。

    这条是 2026-08-04 从一次真事故里补的:一个 1012×1618 的邮件面板,figma 里是
    4 个圆角实色矩形 + 1 条渐变 + 几个椭圆,**零张图片填充**,只因角落有 9 个矢量装饰,
    旧的 `needs_image = 含矢量 and 无文字` 就把整块烤成了一张 PNG。产物退化成
    "截图 + 热区",下游 unity/godot/cocos 拿到的也全是位图。

    两个分支都必须守:
      · 缺 PNG —— 旧代码这里靠 `vector_leaf_count<=4` 兜底,矢量一多(这里 5 个)
        就整块变透明占位,面板直接消失,连"截图"都不剩。
      · 有 PNG —— 旧代码二话不说折叠。这才是真实事故的那条路径。
    """
    def cluster():
        # 一个圆角实色矩形(能写) + 5 个矢量装饰(写不出来),正是真实面板的形状
        kids = [_rect("4:2", 110, 210, 300, 100, cornerRadius=24)]
        kids += [{"id": "4:%d" % (10 + i), "type": "VECTOR", "visible": True,
                  "absoluteBoundingBox": {"x": 120 + i * 10, "y": 220, "width": 8, "height": 8}}
                 for i in range(5)]
        return {"id": "4:1", "type": "GROUP", "visible": True,
                "absoluteBoundingBox": {"x": 110, "y": 210, "width": 300, "height": 100},
                "children": kids}

    def assert_descended(cap, where):
        by = {e["id"]: e for e in cap["els"]}
        assert "4:2" in by, ("%s:圆角矩形被吃掉了,只剩 %s" % (where, list(by)))
        assert by["4:2"]["radius"] == "24px", (where, by["4:2"]["radius"])
        assert by["4:2"]["fill"], ("%s:实色填充没写出来" % where)
        assert not by["4:1"]["img"], ("%s:整簇被折成了图 %s" % (where, by["4:1"]["img"]))

    # 分支一:一张 PNG 都没有
    cap, _ = fc.capture(_frame([cluster()]), NOASSET, ASSET_REL)
    assert_descended(cap, "缺图")

    # 分支二:PNG 就在手边(真实事故路径)。capture 只 os.path.exists、从不解析像素,
    # 所以占位文件的内容无所谓 —— 这里要验的是"有图也不准折"。
    import tempfile, shutil
    d = tempfile.mkdtemp()
    try:
        open(os.path.join(d, "n4_1.png"), "wb").write(b"not-a-real-png")
        cap, _ = fc.capture(_frame([cluster()]), d, ASSET_REL)
        assert_descended(cap, "有图")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_mask_becomes_a_clip_instead_of_being_painted():
    """带 isMask 的子层是**裁剪形状**,不是一层画面。

    也是 2026-08-04 那次事故的一半:一个渐变矩形挂着 isMask,本该只给同组兄弟
    提供圆角轮廓,却被当普通图层照着画 —— 黄面板渲成了绿的;而被它裁的那个
    2143×680 大椭圆失去约束,糊满整屏。
    形状铺满父盒的矩形/椭圆 → 父级 overflow:hidden + 圆角,精确等价;
    兜不住的形状 → 不装作还原,走 known-loss(见 stderr)。
    """
    mask = _rect("5:2", 110, 210, 300, 200, cornerRadius=40, isMask=True)
    spill = {"id": "5:3", "type": "ELLIPSE", "visible": True,
             "absoluteBoundingBox": {"x": -400, "y": 300, "width": 1200, "height": 400},
             "fills": [{"type": "SOLID", "visible": True,
                        "color": {"r": .9, "g": .9, "b": .8, "a": 1}}]}
    group = {"id": "5:1", "type": "GROUP", "visible": True,
             "absoluteBoundingBox": {"x": 110, "y": 210, "width": 300, "height": 200},
             "rectangleCornerRadii": [0, 0, 0, 0],      # 组自带的全零圆角,不许挡住遮罩形状
             "children": [mask, spill]}
    cap, _ = fc.capture(_frame([group]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}

    assert "5:2" not in by, "遮罩被当成一层画出来了(它只该提供形状)"
    assert by["5:1"]["clip"] is True, "父级没拿到裁剪"
    assert by["5:1"]["radius"] == "40px", ("遮罩圆角没折进父级:%r" % by["5:1"]["radius"])
    assert "5:3" in by, "被裁的兄弟不该消失,只该被裁"

    # 没有遮罩时不许平白多出裁剪 —— 否则这条测试对"到处乱裁"是瞎的
    plain = {"id": "6:1", "type": "GROUP", "visible": True,
             "absoluteBoundingBox": {"x": 110, "y": 210, "width": 300, "height": 200},
             "children": [_rect("6:2", 110, 210, 50, 50)]}
    cap2, _ = fc.capture(_frame([plain]), NOASSET, ASSET_REL)
    by2 = {e["id"]: e for e in cap2["els"]}
    assert by2["6:1"]["clip"] is False, "无遮罩的组不该被裁"


def _vec(nid, x, y, w, h, **kw):
    n = {"id": nid, "type": "VECTOR", "visible": True,
         "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
         "fills": [{"type": "SOLID", "visible": True, "color": {"r": 1, "g": 0, "b": 0, "a": 1}}]}
    n.update(kw)
    return n


def test_vectors_are_drawn_from_paths_not_downloaded_as_bitmaps():
    """矢量拿到几何就照着画,不下 PNG。

    figma REST 加 `geometry=paths` 就会给出每个矢量的 SVG 路径。以前不看这个字段,
    一律去 /v1/images 渲 PNG —— 那个接口有**渲染配额**,真会被打爆(2026-08-04 连退
    11 次 429、41 个簇一张没拿到),而且位图分辨率固定、改色要重导、下游引擎也只能吃位图。
    有路径就不该有素材依赖:missing 必须是空的。
    """
    v = _vec("7:1", 110, 210, 60, 20,
             fillGeometry=[{"path": "M0 0L60 0L60 20L0 20Z", "windingRule": "NONZERO"}])
    cap, missing = fc.capture(_frame([v]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}
    assert by["7:1"]["paths"], "没产出路径"
    assert by["7:1"]["paths"][0]["d"] == "M0 0L60 0L60 20L0 20Z"
    assert by["7:1"]["paths"][0]["fill"], "路径没带颜色"
    assert not by["7:1"]["img"], "有路径还去贴图了"
    assert not missing, "有路径还登记了缺素材:%r" % (missing,)


def test_stroke_geometry_is_not_also_drawn_as_a_css_border():
    """描边已经烘进路径里,就不许再沿矩形盒子画一遍。

    figma 的 strokeGeometry 是**把描边转成的可填充轮廓**。若同时再留 border /
    外扩环,等于沿着元素的矩形盒子把描边又画一遍 —— 踩过:一根 38×1 的箭头杆带
    12px 居中描边,环画成 6px 白色方框,整个返回箭头糊成一坨白块。
    """
    v = _vec("7:2", 110, 210, 38, 1, fills=[],
             strokes=[{"type": "SOLID", "visible": True, "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
             strokeWeight=12.0, strokeAlign="CENTER",
             strokeGeometry=[{"path": "M0 -6L38 -6L38 6L0 6Z", "windingRule": "NONZERO"}],
             absoluteRenderBounds={"x": 104, "y": 204, "width": 50, "height": 12})
    cap, _ = fc.capture(_frame([v]), NOASSET, ASSET_REL)
    e = {x["id"]: x for x in cap["els"]}["7:2"]
    assert e["paths"], "描边几何没变成路径"
    assert not e["border"], "描边被画了第二遍(border):%r" % e["border"]
    assert not e["shadow"], "描边被画了第二遍(外扩环):%r" % e["shadow"]
    # 圆头端点甩出包围盒 → 盒子要按 renderBounds 放大,viewBox 反向平移,否则端点被切
    assert (e["w"], e["h"]) == (50.0, 12.0), "没按 renderBounds 定框:%sx%s" % (e["w"], e["h"])
    assert e["viewBox"].startswith("-6.00 -6.00"), "viewBox 没平移:%r" % e["viewBox"]


def test_partial_mask_wraps_only_the_siblings_after_it():
    """遮罩不铺满父盒时,不许放弃 —— 造一层裁剪包裹,只罩住它**之后**的兄弟。

    figma 的遮罩只影响其后的兄弟。以前判定"没铺满父盒"就直接放弃:遮罩自己被当普通
    图层画了出来(邮件行里那块青色矩形盖住了图标底色),而它本该裁住的深绿装饰方角
    溢出圆角框。两处错同一个根因。
    """
    before = _rect("b:2", 110, 210, 60, 60)                        # 在遮罩之前:不受影响
    mask = _rect("b:3", 110, 210, 60, 60, cornerRadius=30, isMask=True)
    after = _rect("b:4", 100, 240, 200, 40)                        # 在遮罩之后:要被裁
    parent = {"id": "b:1", "type": "GROUP", "visible": True,
              "absoluteBoundingBox": {"x": 110, "y": 210, "width": 400, "height": 100},
              "children": [before, mask, after]}
    cap, _ = fc.capture(_frame([parent]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}

    assert "b:3" not in by, "遮罩被画出来了(它只该提供形状)"
    assert by["b:1"]["clip"] is False, "遮罩没铺满父盒,不该让整个父级去裁"
    wid = "b:3~mask"
    assert wid in by, "没造裁剪包裹层,遮罩等于被放弃了"
    assert by[wid]["clip"] is True and by[wid]["radius"] == "30px", by[wid]
    assert (by[wid]["w"], by[wid]["h"]) == (60.0, 60.0), "包裹层几何应等于遮罩盒"
    assert by["b:4"]["parent"] == wid, "遮罩之后的兄弟没挂进包裹层"
    assert by["b:2"]["parent"] == "b:1", "遮罩**之前**的兄弟不该被裁"


def test_stroke_band_is_clipped_by_its_alignment():
    """figma 的 strokeGeometry 是**预裁带**(骑在边线上、总宽 2w),不是最终描边。

    实测:8px INSIDE 描边给出来的带子是 ±8,指望消费方按 strokeAlign 去裁 ——
    INSIDE 裁进形状内、OUTSIDE 裁到形状外,裁完各剩 w。整条照画就两边各多一倍:
    系统页签的青边粗了一倍,信封那圈 5px 白描边的内半边直接盖住了绿色本体。
    CENTER 本来就对(实测 12px CENTER 给的是 ±6 = w),不许裁。
    """
    def one(align):
        n = _vec("c:1", 110, 210, 100, 40,
                 fillGeometry=[{"path": "M0 0L100 0L100 40L0 40Z", "windingRule": "NONZERO"}],
                 strokes=[{"type": "SOLID", "visible": True,
                           "color": {"r": 0, "g": 0, "b": 1, "a": 1}}],
                 strokeWeight=8.0, strokeAlign=align,
                 strokeGeometry=[{"path": "M-8 -8L108 -8L108 48L-8 48Z", "windingRule": "NONZERO"}])
        cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
        return {e["id"]: e for e in cap["els"]}["c:1"]["paths"]

    ins = one("INSIDE")
    assert ins[1]["clip"] == "inside", "INSIDE 的描边带没被裁进形状内:%r" % ins[1].get("clip")
    out = one("OUTSIDE")
    assert out[1]["clip"] == "outside", "OUTSIDE 的描边带没被裁到形状外:%r" % out[1].get("clip")
    ctr = one("CENTER")
    assert not ctr[1]["clip"], "CENTER 的带子本来就对,不该再裁:%r" % ctr[1].get("clip")
    for r in (ins, out, ctr):
        assert not r[0]["clip"], "填充路径不该被裁"


def test_rotated_vector_viewbox_uses_local_size_not_the_aabb():
    """节点旋转时,路径坐标在**未旋转的本地空间**里,viewBox 必须跟着本地 size。

    拿旋转后的轴对齐包围盒当 viewBox,图形会被压扁 —— 那个倾斜的礼物字形因此
    缩到了 0.8 倍。
    """
    import math as _m
    c, s = _m.cos(_m.radians(30)), _m.sin(_m.radians(30))
    n = _vec("d:1", 110, 210, 140, 150,                      # 140×150 = 旋转后的 AABB
             relativeTransform=[[c, -s, 0], [s, c, 0]],
             size={"x": 100, "y": 120},                      # 本地尺寸,路径就在这个空间
             fillGeometry=[{"path": "M0 0L100 0L100 120L0 120Z", "windingRule": "NONZERO"}])
    cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
    e = {x["id"]: x for x in cap["els"]}["d:1"]
    assert (e["w"], e["h"]) == (100.0, 120.0), "旋转节点的 w/h 应是本地 size"
    assert e["viewBox"] == "0 0 100.00 120.00", "viewBox 跟着 AABB 走了:%r" % e["viewBox"]


def test_mask_wrapper_is_layered_where_the_mask_was():
    """裁剪包裹层的 z 要在**遮罩所在的文档序位置**发,不能提前发在父节点之前。

    提前发的话它比父节点自己还小,于是连同里面的内容一起被后画的兄弟盖死 ——
    邮件图标里那道深绿波浪就是这么整块消失的(在,但被白卡片盖住)。
    """
    card = _rect("e:2", 110, 210, 400, 100)                  # 大白卡,在遮罩之前画
    mask = _rect("e:3", 120, 220, 60, 60, cornerRadius=30, isMask=True)
    wave = _rect("e:4", 115, 250, 80, 40)
    parent = {"id": "e:1", "type": "GROUP", "visible": True,
              "absoluteBoundingBox": {"x": 110, "y": 210, "width": 400, "height": 100},
              "children": [card, mask, wave]}
    cap, _ = fc.capture(_frame([parent]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}
    wid = "e:3~mask"
    assert wid in by, "没造包裹层"
    assert by[wid]["z"] > by["e:2"]["z"], (
        "包裹层压在先画的卡片下面了(z %s <= %s),里面的东西会被盖死"
        % (by[wid]["z"], by["e:2"]["z"]))
    assert by[wid]["z"] > by["e:1"]["z"], "包裹层的 z 比父节点还小"


def test_paint_blend_modes_are_flattened_against_the_known_backdrop():
    """figma 的画笔带混合模式,CSS 的 border/background 没有逐画笔混合 —— 捕获期压平。

    按钮那圈深边就是黑色 30% + **OVERLAY** 压在按钮自己的填充上。只读颜色和不透明度、
    按 NORMAL 合成会明显偏暗:金色按钮描边 figma 渲出来是 (255,189,0),按 NORMAL
    算是 (178,142,0)。背景色在捕获期是已知的,所以压平既精确、下游引擎又能直接用。

    数值不是凑的,是按混合公式算的,并与 figma 自渲染逐通道核过:
      OVERLAY(b≥.5) = 2b-1;  out = .7·b + .3·overlay
        金 (1,.8,0) → R 1·→255,G .7·.8+.3·.6=.74→189,B 0→0
      COLOR_BURN(黑) = 0,**但 b==1 → 1**;  out = .97·b
        金 → R 255(靠那条特例),G .97·.8=.776→198,B 0
    """
    BLACK = {"r": 0, "g": 0, "b": 0, "a": 1}
    gold = [{"type": "SOLID", "visible": True, "blendMode": "NORMAL",
             "color": {"r": 1.0, "g": 0.8, "b": 0.0, "a": 1}}]

    # ① 描边 OVERLAY,压在自己的填充上
    n = _rect("f:1", 110, 210, 100, 40, fills=gold,
              strokes=[{"type": "SOLID", "visible": True, "blendMode": "OVERLAY",
                        "opacity": 0.3, "color": BLACK}],
              strokeWeight=7.0, strokeAlign="INSIDE")
    cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
    e = {x["id"]: x for x in cap["els"]}["f:1"]
    assert e["border"] == "7.0px solid rgba(255,189,0,1.0)", (
        "OVERLAY 没压平(按 NORMAL 会得到 178,142,0):%r" % e["border"])

    # ② 填充 COLOR_BURN,压在**上一个铺满的兄弟**上 —— 按钮纹理就是这么垫底的
    base = _rect("g:2", 110, 210, 100, 40, fills=gold)
    tex = _rect("g:3", 110, 210, 100, 40,
                fills=[{"type": "SOLID", "visible": True, "blendMode": "COLOR_BURN",
                        "opacity": 0.03, "color": BLACK}])
    holder = {"id": "g:1", "type": "FRAME", "visible": True,
              "absoluteBoundingBox": {"x": 110, "y": 210, "width": 100, "height": 40},
              "children": [base, tex]}
    cap2, _ = fc.capture(_frame([holder]), NOASSET, ASSET_REL)
    e2 = {x["id"]: x for x in cap2["els"]}["g:3"]
    assert e2["fill"] == "rgba(255,198,0,1.0)", (
        "COLOR_BURN 没压平,或漏了 b==1 那条特例(会把 R 一起压暗):%r" % e2["fill"])

    # ③ 背景未知就别装:退回 NORMAL 并登记 known-loss
    lone = _rect("h:1", 110, 210, 100, 40,
                 fills=[{"type": "SOLID", "visible": True, "blendMode": "OVERLAY",
                         "opacity": 0.3, "color": BLACK}])
    frame = {"id": "0:1", "type": "FRAME", "visible": True,
             "absoluteBoundingBox": {"x": 100, "y": 200, "width": 1080, "height": 1920},
             "fills": [], "children": [lone]}          # 帧无底色 → 背景未知
    cap3, miss = fc.capture(frame, NOASSET, ASSET_REL)
    assert any(m[2] == "BLEND-OVERLAY" for m in miss), "背景未知却没吭声:%r" % (miss,)


def test_clipped_frames_actually_clip():
    """figma 帧勾了「裁剪内容」就得真裁。

    不裁的后果:滚动列表最后一行整条漏在容器外面,看着像层级错了。
    """
    row = _rect("8:2", 110, 400, 100, 200)          # 底边 600,越出容器 500
    frame = {"id": "8:1", "type": "FRAME", "visible": True, "clipsContent": True,
             "absoluteBoundingBox": {"x": 110, "y": 210, "width": 300, "height": 290},
             "children": [row]}
    cap, _ = fc.capture(_frame([frame]), NOASSET, ASSET_REL)
    by = {e["id"]: e for e in cap["els"]}
    assert by["8:1"]["clip"] is True, "clipsContent 没转成裁剪"
    assert "8:2" in by, "被裁的子节点不该消失,只该被裁"

    frame["clipsContent"] = False
    cap2, _ = fc.capture(_frame([frame]), NOASSET, ASSET_REL)
    assert {e["id"]: e for e in cap2["els"]}["8:1"]["clip"] is False, "没勾裁剪却裁了"


def test_stroke_alignment_decides_inside_versus_outside():
    """CSS 的 border 只会向内画,figma 有三种对齐 —— 不能一律按 border。

    OUTSIDE 按 border 画就是**画反了方向**:本该外扩 N px,变成往里吃掉 N px 填充。
    一个 10px 描边的装饰因此差 20px,肉眼可见。外扩用 box-shadow(跟随圆角,
    outline 不跟),CENTER 各一半。
    """
    SK = [{"type": "SOLID", "visible": True, "color": {"r": 0, "g": 0, "b": 1, "a": 1}}]
    got = {}
    for align in ("INSIDE", "OUTSIDE", "CENTER"):
        r = _rect("9:1", 110, 210, 100, 50, strokes=SK, strokeWeight=10.0, strokeAlign=align)
        cap, _ = fc.capture(_frame([r]), NOASSET, ASSET_REL)
        got[align] = {e["id"]: e for e in cap["els"]}["9:1"]

    assert got["INSIDE"]["border"].startswith("10.0px solid"), got["INSIDE"]["border"]
    assert not got["INSIDE"]["shadow"], "INSIDE 不该外扩:%r" % got["INSIDE"]["shadow"]

    assert not got["OUTSIDE"]["border"], "OUTSIDE 还在往里画:%r" % got["OUTSIDE"]["border"]
    assert got["OUTSIDE"]["shadow"].startswith("0 0 0 10.0px"), got["OUTSIDE"]["shadow"]

    assert got["CENTER"]["border"].startswith("5.0px solid"), got["CENTER"]["border"]
    assert got["CENTER"]["shadow"].startswith("0 0 0 5.0px"), got["CENTER"]["shadow"]
    for a in got:
        assert got[a]["borderAlign"] == a.lower(), (a, got[a]["borderAlign"])


def test_outside_text_stroke_is_doubled_because_css_centres_it():
    """figma 文字描边默认全在字外,而 -webkit-text-stroke 是**居中**的。

    照抄宽度的话一半会吃进字面,每个带描边的标题都瘦一圈 —— 中文标题尤其明显。
    """
    SK = [{"type": "SOLID", "visible": True, "color": {"r": 0, "g": 0, "b": 0, "a": 1}}]
    base = {"id": "a:1", "type": "TEXT", "visible": True, "characters": "标题",
            "absoluteBoundingBox": {"x": 110, "y": 210, "width": 200, "height": 50},
            "fills": [{"type": "SOLID", "visible": True, "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
            "style": {"fontSize": 40, "textAlignHorizontal": "CENTER", "textAlignVertical": "TOP"},
            "strokes": SK, "strokeWeight": 6.0}

    out = dict(base, strokeAlign="OUTSIDE")
    cap, _ = fc.capture(_frame([out]), NOASSET, ASSET_REL)
    assert {e["id"]: e for e in cap["els"]}["a:1"]["text"]["stroke"].startswith("12.0px"), "OUTSIDE 没加倍"

    ctr = dict(base, strokeAlign="CENTER")
    cap2, _ = fc.capture(_frame([ctr]), NOASSET, ASSET_REL)
    assert {e["id"]: e for e in cap2["els"]}["a:1"]["text"]["stroke"].startswith("6.0px"), "CENTER 不该加倍"


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


def test_a_hairline_is_not_dropped_for_having_a_zero_height_box():
    """**一条水平线的 absoluteBoundingBox 高度就是 0** —— 别把它当空盒扔掉。

    figma 里的分隔线/下划线是零厚度几何 + 描边:看得见的那几像素全在描边里,
    只出现在 absoluteRenderBounds。capture 的空盒守卫本来是拿来跳过真正空的容器的,
    却把这类线一并静默吃掉 —— 邮件详情里附件上方那两条 6px 分隔线
    (bb=879×0 / render=885×6 / strokeGeometry 一条)就这么从 IR 里整条消失,
    html 与 godot 两边都没有,而且**谁都没吭一声**。

    有可画几何又有非零渲染边界的,要收下,并按渲染边界定框、viewBox 反向平移
    (线的一半在 y<0,不平移会被切掉上半截)。
    """
    line = _vec("9:1", 110, 300, 200, 0,
                fills=[],
                strokes=[{"type": "SOLID", "visible": True,
                          "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                strokeWeight=6,
                strokeGeometry=[{"path": "M0 -3L200 -3L200 3L0 3Z", "windingRule": "NONZERO"}],
                absoluteRenderBounds={"x": 107, "y": 297, "width": 206, "height": 6})
    cap, _missing = fc.capture(_frame([line]), NOASSET, ASSET_REL)
    el = {e["id"]: e for e in cap["els"]}.get("9:1")
    assert el is not None, "零高度的线被当空盒丢掉了 —— figma 的分隔线全长这样"
    assert el["h"] == 6.0, "应按 renderBounds 定高(描边的真实厚度),读到 %r" % el["h"]
    assert el["w"] == 206.0, "应按 renderBounds 定宽(圆头描边会超出 bb),读到 %r" % el["w"]
    assert len(el["paths"]) == 1, "描边几何应照着画出来"
    vb = [float(v) for v in el["viewBox"].split()]
    assert vb[0] < 0 and vb[1] < 0, (
        "viewBox 必须反向平移到负坐标(路径的一半在 y<0),读到 %r" % el["viewBox"])


def test_preview_is_nested_like_the_runtime_not_flat():
    """tree.html 必须**按 parent 嵌套**,和 render.js 同构。

    扁平预览(所有节点平铺成兄弟、用帧内绝对坐标)贴的样式一模一样,唯独容器关系不对,
    于是任何依赖父子的效果一律看不出来 —— `clip` 的 overflow:hidden 首当其冲。
    这不是"预览糙一点":它**会说谎**,拿它排查裁剪会把早就修好的功能判成坏的。
    """
    outer = _rect("p:1", 110, 210, 200, 100, cornerRadius=20, clipsContent=True,
                  children=[_rect("p:2", 150, 250, 400, 400)])
    cap, _ = fc.capture(_frame([outer]), NOASSET, ASSET_REL)
    doc = fc.to_html(cap, "s01")
    i_out, i_in = doc.index('data-id="p:1"'), doc.index('data-id="p:2"')
    assert i_out < i_in < doc.index("</div>", i_out), \
        "子节点没嵌在父节点里(它出现在父节点闭合之后)—— 扁平预览里 overflow:hidden 不会生效"
    # 几何转成父相对:p:2 相对 p:1 是 (40, 40)
    seg = doc[i_in:doc.index(">", i_in)]
    assert "left:40.0px" in seg and "top:40.0px" in seg, "嵌套了却还用绝对坐标:%r" % seg
    assert "overflow:hidden" in doc[i_out:i_in], "裁剪容器没带 overflow:hidden"


def test_single_line_text_is_normalised_to_its_line_box():
    """文本的竖直位置得在**捕获层**算完,别留给后端各自猜。

    实测 figma(拿 absoluteRenderBounds 当墨迹真值,5 个样本):行块高 = lineHeight,
    按 textAlignVertical 放进文本框;**行块比框高时不是顶对齐、而是居中溢出**。
    「运营」框高 31、行高 50.4、TOP,墨迹中心落在框心 1820.5 而不是行块顶对齐的 1830 —— 差 10px。

    这套「行高 + 竖直锚点」是 CSS 语汇,引擎侧没有等价物:godot 的 Label 和 Unity 的
    UI Toolkit 都**没有 line-height**。于是同一份 IR:html 靠 line-height 对上了,
    godot 低 12px、unity 因为吃不到半行距(half-leading)整体高 8.5px。

    根治:单行文本在捕获层就把盒子归一成**行盒**(y 落到行块位置、h = lineHeight),
    alignV 一律 center。这样三端都只要"在盒子里居中"就精确一致,谁也不用 line-height。
    多行框(框高装得下两行以上)不动 —— 那时候顶对齐是对的。
    """
    def one(y, h, lh, av, size=36.0):
        n = {"id": "t:1", "name": "t", "type": "TEXT", "visible": True,
             "absoluteBoundingBox": {"x": 110, "y": y + 200, "width": 200, "height": h},
             "characters": "四个字内", "fills": [{"type": "SOLID", "visible": True,
                                               "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
             "style": {"fontSize": size, "lineHeightPx": lh, "textAlignVertical": av,
                       "textAlignHorizontal": "CENTER", "fontFamily": "X", "fontWeight": 700}}
        cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
        return {e["id"]: e for e in cap["els"]}["t:1"]

    # ① 框比行高一点(删除已读:框 56 / 行 48 / TOP)→ 行盒贴顶
    e = one(1617, 56, 48, "TOP")
    assert (e["y"], e["h"]) == (1617.0, 48.0), "TOP 的行盒应贴框顶、高=行高:%r" % [e["y"], e["h"]]
    # ② 框比行**矮**(运营:框 31 / 行 50.4 / TOP)→ 行盒居中溢出,不是贴顶
    e = one(1805, 31, 50.4, "TOP", 42.0)
    assert abs(e["y"] - (1805 + (31 - 50.4) / 2)) < 0.6, (
        "行块高过框时 figma 是居中溢出,不是顶对齐:%r" % e["y"])
    assert abs(e["y"] + e["h"] / 2 - (1805 + 31 / 2)) < 0.6, "墨迹中心应落在框心"
    # ③ CENTER 照旧居中
    e = one(391, 46, 40.5, "CENTER", 28.0)
    assert abs(e["y"] - (391 + (46 - 40.5) / 2)) < 0.6, "CENTER 的行盒应居中:%r" % e["y"]
    # ④ 竖直锚点归一后一律 center —— 后端不必再懂 flex-start/flex-end
    for av in ("TOP", "CENTER", "BOTTOM"):
        assert one(100, 60, 48, av)["text"]["alignV"] == "center", av
    # ⑤ 多行框(框 578 / 行 52)不动:那时候顶对齐是对的
    e = one(517, 578, 52, "TOP")
    assert (e["y"], e["h"]) == (517.0, 578.0), "多行框不该被归一成一行:%r" % [e["y"], e["h"]]


def test_stroke_band_is_split_so_backends_never_need_boolean_ops():
    """描边带要在捕获层就**劈开**,只留 strokeAlign 真正要的那一半。

    之前的做法是原样发 ±w 的带子 + 一个 `clip:inside/outside` 提示,让后端自己裁。
    能裁的只有拿得到布尔裁剪的后端(svg 的 clipPath / mask):html、godot 靠它对上了;
    Unity 的 Painter2D 没有布尔裁剪,只能整条照画 —— 系统页签那圈青边粗了一倍,
    而且带子是逐段闭合的四边形,多轮廓一起填还撞出穿帮的斜条。

    figma 的带子结构是恒定的:每条子路径 = [中线起点 → 内偏移 → 内侧几何 →
    中线终点 → 外偏移 → 外侧几何 → 闭合],内外两条链命令数相同,从中间劈得开。
    劈完只发要的那半、clip 清空,任何后端"照着填"就精确 —— 布尔裁剪不再是入场券。
    """
    # 100×40 的矩形,四条边各一条闭合带子(±8);每条恒为
    # [中线起点 → 内偏移 → 内侧几何 → 中线终点 → 外偏移 → 外侧几何 → 闭合]。
    # 拐角按斜接(miter):相邻两段在**同一个偏移点**交汇 —— 偏移链能首尾接成闭合轮廓,
    # 靠的就是这个。
    band = ("M0 0L8 8L92 8L100 0L108 -8L-8 -8L0 0Z"             # 上边
            "M100 0L92 8L92 32L100 40L108 48L108 -8L100 0Z"     # 右边
            "M100 40L92 32L8 32L0 40L-8 48L108 48L100 40Z"      # 下边
            "M0 40L8 32L8 8L0 0L-8 -8L-8 48L0 40Z")             # 左边

    def one(align):
        n = _vec("c:1", 110, 210, 100, 40,
                 fillGeometry=[{"path": "M0 0L100 0L100 40L0 40Z", "windingRule": "NONZERO"}],
                 strokes=[{"type": "SOLID", "visible": True,
                           "color": {"r": 0, "g": 0, "b": 1, "a": 1}}],
                 strokeWeight=8.0, strokeAlign=align,
                 strokeGeometry=[{"path": band, "windingRule": "NONZERO"}])
        cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
        return {e["id"]: e for e in cap["els"]}["c:1"]["paths"][1]

    ins = one("INSIDE")
    assert not ins["clip"], "劈开之后不该再留裁剪提示:%r" % ins["clip"]
    assert ins["rule"] == "evenodd", "环靠 evenodd 把中间那圈留出来:%r" % ins["rule"]
    xs, ys = fc._path_points(ins["d"])
    assert min(ys) >= -0.01 and max(ys) <= 40.01, "INSIDE 的环越出形状:y∈%r" % [min(ys), max(ys)]
    assert min(xs) >= -0.01 and max(xs) <= 100.01, "INSIDE 的环越出形状:x∈%r" % [min(xs), max(xs)]
    assert 8.0 in ys and 92.0 in xs, "内缩轮廓(+8)没接出来:%r" % ins["d"]
    out = one("OUTSIDE")
    assert not out["clip"] and out["rule"] == "evenodd"
    xs, ys = fc._path_points(out["d"])
    assert -8.0 in ys and 108.0 in xs, "外扩轮廓(-8)没接出来:%r" % out["d"]
    assert 8.0 not in ys and 92.0 not in xs, "OUTSIDE 里混进了内缩轮廓:%r" % out["d"]
    # 环必须是**两条**闭合轮廓(形状 + 内缩/外扩),缺一条就退化成实心块
    for r in (ins, out):
        assert r["d"].count("M") == 2 and r["d"].count("Z") == 2, r["d"]
    ctr = one("CENTER")
    assert not ctr["clip"] and ctr["d"] == band, "CENTER 本来就对,原样发"


def test_a_band_that_does_not_split_cleanly_falls_back_to_the_clip_hint():
    """劈不开就**退回原样 + clip 提示**,别硬劈出错几何。

    带子的结构是 figma 生成器给的,不是规范保证的。命令数劈不成两半、
    或者半边偏移量对不上描边宽,一律当作"不认识",退回老路子由后端裁。
    """
    n = _vec("c:2", 110, 210, 100, 40,
             fillGeometry=[{"path": "M0 0L100 0L100 40L0 40Z", "windingRule": "NONZERO"}],
             strokes=[{"type": "SOLID", "visible": True,
                       "color": {"r": 0, "g": 0, "b": 1, "a": 1}}],
             strokeWeight=8.0, strokeAlign="INSIDE",
             strokeGeometry=[{"path": "M-8 -8L108 -8L108 48L-8 48Z", "windingRule": "NONZERO"}])
    cap, _ = fc.capture(_frame([n]), NOASSET, ASSET_REL)
    p = {e["id"]: e for e in cap["els"]}["c:2"]["paths"][1]
    assert p["clip"] == "inside", "劈不开的带子应退回 clip 提示:%r" % p["clip"]
    assert p["d"] == "M-8 -8L108 -8L108 48L-8 48Z", "退回时不许改动原路径"


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
