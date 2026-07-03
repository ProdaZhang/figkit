import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import figma_to_dsl as F

def _bb(x,y,w,h): return {"x":x,"y":y,"width":w,"height":h}
def _solid(): return [{"type":"SOLID","visible":True,"color":{"r":.9,"g":.9,"b":.9}}]
def _text(nid,name,x,y,s):
    return {"id":nid,"type":"TEXT","name":name,"visible":True,"characters":s,
            "absoluteBoundingBox":_bb(x,y,100,30),
            "fills":[{"type":"SOLID","visible":True,"color":{"r":0,"g":0,"b":0}}]}
def _row(nid,name,x,y):
    return {"id":nid,"type":"FRAME","name":name,"visible":True,
            "absoluteBoundingBox":_bb(x,y,600,80),"fills":_solid(),
            "children":[_text(nid+":a","t1",x+10,y+10,"AAA"),
                        _text(nid+":b","t2",x+10,y+45,"BBB")]}
def _panel():
    # FRAME 含两个子 FRAME(各含2文本)→ 现有启发式 child_conts=2 → 成为容器
    return {"id":"2:1","type":"FRAME","name":"面板","visible":True,
            "absoluteBoundingBox":_bb(100,200,800,400),"fills":_solid(),
            "children":[_row("2:10","行A",150,250),_row("2:20","行B",150,340)]}
def _frame(children,w=1080,h=1920):
    return {"id":"0:1","type":"FRAME","name":"屏","visible":True,
            "absoluteBoundingBox":_bb(0,0,w,h),"fills":[],"children":children}

def _coords(line):
    m=re.search(r"@\{([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)\}",line)
    return tuple(float(g) for g in m.groups())
def _line_with(md,name):
    for l in md.splitlines():
        if name in l and "@{" in l: return l
    raise AssertionError("无含 '%s' 的 Layout 行" % name)

def test_header_has_coordmode_and_pixel_size():
    md,_=F.build_dsl(_frame([_panel()]),"0:1","99","测试")
    assert "> 坐标系: 父相对px" in md
    assert re.search(r"> 尺寸: 1080×1920", md), md[:300]

def test_container_coords_relative_to_frame():
    md,_=F.build_dsl(_frame([_panel()]),"0:1","99","测试")
    assert _coords(_line_with(md,"面板")) == (100.0,200.0,800.0,400.0)

def test_child_coords_parent_relative_px():
    md,_=F.build_dsl(_frame([_panel()]),"0:1","99","测试")
    assert _coords(_line_with(md,"行A")) == (50.0,50.0,600.0,80.0)
    assert _coords(_line_with(md,"行B")) == (50.0,140.0,600.0,80.0)

def _hidden_text(nid, s, x=200, y=1700):
    return {"id":nid,"type":"TEXT","name":"隐藏","visible":False,"characters":s,
            "absoluteBoundingBox":_bb(x,y,200,40),
            "fills":[{"type":"SOLID","visible":True,"color":{"r":0,"g":0,"b":0}}]}

def test_hidden_skipped_and_parent_tracked():
    # 帧含:一个容器面板(Task4 的 _panel,parent 应="") + 一个隐藏的直接子文本(应被跳过)
    doc = _frame([_panel(), _hidden_text("9:9","隐藏文字别出现")])
    md, side = F.build_dsl(doc, "0:1", "99", "测试")
    assert "隐藏文字别出现" not in md                     # 隐藏节点不进 md
    assert not any(e["node"] == "9:9" for e in side["els"])  # 也不进 sidecar
    panel_el = next(e for e in side["els"] if e["node"] == "2:1")
    rowA_el  = next(e for e in side["els"] if e["node"] == "2:10")
    assert panel_el["parent"] == ""                       # 面板挂帧根
    assert rowA_el["parent"] == panel_el["id"]            # 行A 的父 = 面板 dsl id

def test_image_node_emits_yuantu_and_sidecar_fields():
    img = {"id":"4:2","type":"RECTANGLE","name":"立绘","visible":True,
           "absoluteBoundingBox":_bb(100,200,400,600),
           "fills":[{"type":"IMAGE","visible":True,"imageRef":"abc","scaleMode":"FILL"}]}
    md, side = F.build_dsl(_frame([img]),"0:1","17","测试")
    assert "## 原图" in md
    el = next(e for e in side["els"] if e["node"]=="4:2")
    assert el["img"] == "_assets/s17/n4_2.png"
    assert "_assets/s17/n4_2.png" in md
    assert "img" in el and "shape" in el and "text" in el and "skin" in el and "ink" in el

def _vec(nid, x, y):  # 矢量节点
    return {"id":nid,"type":"VECTOR","name":"Vector","visible":True,
            "absoluteBoundingBox":_bb(x,y,40,40),
            "fills":[{"type":"SOLID","visible":True,"color":{"r":.2,"g":.2,"b":.2}}]}

def test_frame_text_children_preserved():
    # FRAME 直接含 2 个文本子(旧规则会丢);新规则应都保留
    panel = {"id":"7:1","type":"FRAME","name":"面板","visible":True,
             "absoluteBoundingBox":_bb(100,200,800,400),"fills":_solid(),
             "children":[_text("7:2","a",150,250,"保留文字甲"),
                         _text("7:3","b",150,300,"保留文字乙")]}
    md,_ = F.build_dsl(_frame([panel]),"0:1","99","测试")
    assert "保留文字甲" in md and "保留文字乙" in md

def test_vector_cluster_collapsed_not_recursed():
    # GROUP 含 2 矢量、无文字 → 整簇当一张图,矢量子不单独发射
    grp = {"id":"8:1","type":"GROUP","name":"图标","visible":True,
           "absoluteBoundingBox":_bb(100,200,48,48),"fills":[],
           "children":[_vec("8:2",100,200),_vec("8:3",120,200)]}
    md, side = F.build_dsl(_frame([grp]),"0:1","17","测试")
    nodes = {e["node"] for e in side["els"]}
    assert "8:1" in nodes                       # 簇本身发射
    assert "8:2" not in nodes and "8:3" not in nodes  # 内部矢量不单独发射
    el = next(e for e in side["els"] if e["node"]=="8:1")
    assert el["img"]                            # 簇发了原图

def test_style_fields_radius_border_shadow_font():
    # 圆角矩形 + 描边 + 阴影 → sidecar 应带 radius/border/shadow
    rect = {"id":"5:1","type":"RECTANGLE","name":"胶囊","visible":True,
            "absoluteBoundingBox":_bb(100,200,600,80),
            "fills":[{"type":"SOLID","visible":True,"color":{"r":1,"g":.98,"b":.95}}],
            "cornerRadius":37,
            "strokes":[{"type":"SOLID","visible":True,"color":{"r":.86,"g":.82,"b":.72},"opacity":1}],
            "strokeWeight":4,
            "effects":[{"type":"DROP_SHADOW","visible":True,"offset":{"x":0,"y":4},"radius":0,
                        "color":{"r":0,"g":0,"b":0,"a":.6}}]}
    # TEXT 带字号/字重/对齐 → sidecar font dict;TEXT 不画矩形 border
    txt = {"id":"5:2","type":"TEXT","name":"标题","visible":True,"characters":"服务器",
           "absoluteBoundingBox":_bb(120,210,200,48),
           "fills":[{"type":"SOLID","visible":True,"color":{"r":.22,"g":.22,"b":.22}}],
           "style":{"fontSize":36,"fontWeight":700,"lineHeightPx":48,"textAlignHorizontal":"CENTER"}}
    _, side = F.build_dsl(_frame([rect, txt]),"0:1","99","测试")
    r = next(e for e in side["els"] if e["node"]=="5:1")
    t = next(e for e in side["els"] if e["node"]=="5:2")
    assert r["radius"] == "37px", r["radius"]
    assert "4.0px solid rgba(" in r["border"], r["border"]
    assert r["shadow"].startswith("0px 4px 0px rgba("), r["shadow"]
    assert t["font"] and t["font"]["size"] == 36 and t["font"]["weight"] == 700, t["font"]
    assert t["font"]["align"] == "center", t["font"]
    assert t["border"] == "", t["border"]   # 文本不画矩形 border

def test_frame_image_fill_emits_bg_yuantu():
    fr = _frame([_text("9:2","t",100,100,"hi")])
    fr["fills"] = [{"type":"IMAGE","visible":True,"imageRef":"X","scaleMode":"FILL"}]  # 整屏背景图
    md, side = F.build_dsl(fr,"0:1","17","测试")
    assert "## 原图" in md
    assert "bg  _assets/s17/bg.png" in md or "bg\t_assets/s17/bg.png" in md.replace("  "," ") or "_assets/s17/bg.png" in md
    bg = next(e for e in side["els"] if e["id"]=="bg")
    assert bg["img"] == "_assets/s17/bg.png"

def _run():
    ok=True
    for n,f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS",n)
            except Exception as e: ok=False; print("FAIL",n,e)
    return ok
if __name__=="__main__":
    raise SystemExit(0 if _run() else 1)
