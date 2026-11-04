"""Optional Godot 4 headless behavior checks; set GODOT_PATH or put godot on PATH.

Everything generated (including .godot imports) stays in a temporary project.
This is runtime behavior verification, not a screenshot/pixel acceptance test.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = '''extends SceneTree

func check(ok: bool, message: String) -> void:
    if not ok:
        push_error(message)
        quit(1)
        assert(ok, message)

func _initialize() -> void:
    var binder := FlowBinder.new()
    var layer := Control.new()
    var list := Control.new()
    list.name = "list"
    layer.add_child(list)
    binder.add_child(layer)
    binder.layers["m"] = layer
    binder.modals["m"] = {"el": layer, "panel": "list"}
    binder.current = "m"
    for top in [10, 40]:
        var row := Control.new()
        row.offset_top = top
        row.offset_bottom = top + 20
        list.add_child(row)
    var fill := func(row, item, _index): row.set_meta("value", item)
    binder.render_rows("m", "list", [], fill)
    binder.render_rows("m", "list", [1], fill)
    binder.render_rows("m", "list", [1, 2, 3], fill)
    check(list.get_child_count() == 3, "empty list did not recover")
    for index in 3:
        check(list.get_child(index).offset_top == 10 + index * 30, "original row spacing lost")
        check(list.get_child(index).get_meta("value") == index + 1, "row callback did not fill data")
    binder.open_modal("missing")
    check(binder.current == "m" and layer.visible, "invalid target hid the current modal")
    binder._exit_tree() # off-tree unit instance: release cached template explicitly
    binder.free()
    print("PASS empty_list_recovers_with_original_spacing")
    print("PASS invalid_modal_preserves_current_layer")

    var scene: PackedScene = load("res://image-alpha.tscn")
    check(scene != null, "generated image scene did not import")
    var screen := scene.instantiate()
    var image_node: TextureRect = screen.get_node("image")
    check(is_equal_approx(image_node.self_modulate.a, .25), "image paint alpha missing")
    check(is_equal_approx(image_node.modulate.a, .6), "image node opacity lost")
    check(image_node.get_node("child").modulate.a == 1, "paint alpha faded child node")
    check(is_equal_approx(screen.get_node("StageBg").self_modulate.a, .4), "stage image alpha missing")
    screen.free()
    print("PASS image_and_stage_paint_alpha_are_independent_of_children")
    quit(0)
'''


def main():
    godot = os.environ.get('GODOT_PATH') or shutil.which('godot') or shutil.which('godot4')
    if not godot:
        raise SystemExit('Set GODOT_PATH to a Godot 4 executable.')
    spec = importlib.util.spec_from_file_location('ui_to_tscn', ROOT / 'figma2godot/scripts/ui_to_tscn.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='figkit_godot_') as directory:
        tmp = Path(directory)
        (tmp / 'project.godot').write_text('[application]\nconfig/name="FigKit behavior regression"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding='utf-8')
        shutil.copyfile(ROOT / 'figma2godot/runtime/flow_binder.gd', tmp / 'flow_binder.gd')
        (tmp / 'test.gd').write_text(SCRIPT, encoding='utf-8')
        def chunk(kind, body):
            return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
        (tmp / 'image.png').write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\xff')) + chunk(b'IEND', b''))
        element = dict(id='image', parent='', x=0, y=0, w=100, h=100, z=1, opacity=.6,
                       img='image.png', imgSize='cover', imgOpacity=.25)
        cap = dict(w=200, h=200, stageBg='url(image.png) center/cover no-repeat', stageBgOpacity=.4,
                   els=[element, dict(id='child', parent='image', x=0, y=0, w=20, h=20, z=2, opacity=1, fill='#00ff00')])
        text, svgs = module.convert_all(cap, 'image-alpha')
        (tmp / 'image-alpha.tscn').write_text(text, encoding='utf-8')
        for name, content in svgs.items():
            (tmp / name).write_text(content, encoding='utf-8')
        for args in [['--editor', '--import'], ['--script', 'res://test.gd']]:
            result = subprocess.run([godot, '--headless', '--path', str(tmp)] + args,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            output = result.stdout + result.stderr
            print(output.strip())
            if result.returncode or 'SCRIPT ERROR' in output or 'Parse Error' in output:
                return 1
        if 'PASS image_and_stage_paint_alpha_are_independent_of_children' not in output:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
