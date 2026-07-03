import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui_render

PX_DSL = """# 屏

> 尺寸: 1000×2000
> 坐标系: 父相对px

## Layout

```
面板 :panel [面板] @{100 200 800 400} z=4
  按钮 :btn [按钮] @{50 25 200 80} z=6 "开始"
```
"""

def test_parse_reads_coordmode():
    p = ui_render.parse_dsl(PX_DSL)
    assert p["coordmode"] == "父相对px", p.get("coordmode")

def test_px_normalized_to_abs_percent():
    p = ui_render.normalize_coords(ui_render.parse_dsl(PX_DSL))
    panel = next(e for e in p["elements"] if e["id"] == "panel")
    btn = next(e for e in p["elements"] if e["id"] == "btn")
    assert (round(panel["x"],3),round(panel["y"],3),round(panel["w"],3),round(panel["h"],3)) == (10.0,10.0,80.0,20.0)
    assert (round(btn["x"],3),round(btn["y"],3),round(btn["w"],3),round(btn["h"],3)) == (15.0,11.25,20.0,4.0)

def test_percent_mode_unchanged():
    pct = "# Y\n\n## Layout\n\n```\n面板 :p [面板] @{10 10 80 20} z=4\n```\n"
    p = ui_render.normalize_coords(ui_render.parse_dsl(pct))
    e = p["elements"][0]
    assert (e["x"],e["y"],e["w"],e["h"]) == (10.0,10.0,80.0,20.0)

def _run():
    ok = True
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try: f(); print("PASS", n)
            except Exception as e: ok = False; print("FAIL", n, e)
    return ok

if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
