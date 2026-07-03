import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui_render

DSL = """# 屏

## Layout

```
游戏logo :logo [图标槽] @{25 20 50 10} z=4
面板     :panel [面板] @{10 30 80 40} z=4
```

## 皮肤

panel  #fffbf2

## 原图

logo   _assets/s15/n45_1.png
"""

def test_parse_reads_yuantu():
    p = ui_render.parse_dsl(DSL)
    assert p["yuantu"]["logo"] == "_assets/s15/n45_1.png"

def test_enrich_carries_img():
    p = ui_render.parse_dsl(DSL)
    enr = {e["id"]: e for e in ui_render._enrich(p["elements"], p["skin"], p["yuantu"])}
    assert enr["logo"]["img"] == "_assets/s15/n45_1.png"
    assert enr["panel"]["img"] == ""

def test_html_has_bg_url_for_img_element():
    p = ui_render.parse_dsl(DSL)
    html = ui_render.render_html(p)
    assert "_assets/s15/n45_1.png" in html

def _run():
    ok = True
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS", n)
            except Exception as e: ok = False; print("FAIL", n, e)
    return ok

if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
