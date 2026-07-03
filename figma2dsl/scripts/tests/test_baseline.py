import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import figma_to_dsl, ui_render

def _frame(children, w=1080, h=1920):
    return {"id": "0:1", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": w, "height": h},
            "fills": [], "children": children}

def test_build_dsl_runs_and_returns_md_and_sidecar():
    doc = _frame([
        {"id": "1:2", "type": "TEXT", "visible": True, "characters": "开始游戏",
         "absoluteBoundingBox": {"x": 360, "y": 1520, "width": 360, "height": 96},
         "fills": [{"type": "SOLID", "visible": True, "color": {"r": 0, "g": 0, "b": 0}}]},
    ])
    md, side = figma_to_dsl.build_dsl(doc, "0:1", "99", "测试屏")
    assert md.startswith("# screen-99 · figma · 测试屏"), md[:40]
    assert "## Layout" in md and "## 皮肤" in md
    assert isinstance(side, dict) and side["frame"] == "0:1" and isinstance(side["els"], list)

def test_build_dsl_meta_brand_prefix_injection():
    doc = _frame([
        {"id": "1:2", "type": "TEXT", "visible": True, "characters": "确认",
         "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 40},
         "fills": [{"type": "SOLID", "visible": True, "color": {"r": 0, "g": 0, "b": 0}}]},
    ])
    meta = {"07": {"u": "确认弹窗", "l": "居中双按钮", "t": "#弹窗", "p": ["双按钮落定"]}}
    md, _ = figma_to_dsl.build_dsl(doc, "0:1", "07", "确认", meta=meta,
                                   brand="demo", file_key="KEY123", prefix="myui")
    assert md.startswith("# myui-07 · demo · 确认"), md[:40]
    assert "> 用途: 确认弹窗" in md and "> 标签: #弹窗" in md
    assert "Figma:KEY123#0:1" in md and "双按钮落定" in md
    # 默认调用不带 meta → 占位而非私货
    md2, _ = figma_to_dsl.build_dsl(doc, "0:1", "07", "确认")
    assert "自家" not in md2 and "ELF" not in md2

def test_ui_render_parse_smoke():
    parsed = ui_render.parse_dsl("# X\n\n## Layout\n\n```\n背景 :bg [背景槽] @{0 0 100 100} z=1\n```\n")
    assert parsed["elements"][0]["id"] == "bg"

def _run():
    ok = True
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try: fn(); print("PASS", name)
            except Exception as e: ok = False; print("FAIL", name, e)
    return ok

if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)
