# -*- coding: utf-8 -*-
"""ui_to_tscn 单元断言:节点数/命名/父相对几何/文本转义/StyleBoxFlat/渐变。"""
import importlib.util
import json
import os
import re

D = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ui_to_tscn', os.path.join(os.path.dirname(D), 'ui_to_tscn.py'))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _node_block(t, name):
    """取某个 [node name="..."] 的整块文本(到下一空行)。"""
    m = re.search(r'\[node name="%s"[^\n]*\]\n(.*?)(?:\n\n|\Z)' % re.escape(name), t, re.S)
    return m.group(0) if m else ''


def _el(id_, **kw):
    """最小合法元素,便于拼合成夹具。"""
    base = dict(id=id_, name=kw.pop('nm', id_), type=kw.pop('tp', 'RECTANGLE'),
                parent='', x=0, y=0, w=100, h=50, z=1, rot=0, opacity=1,
                radius='', border='', shadow='', blur='', fill='', img='',
                imgSize='', text=None, vec=False)
    base.update(kw)
    return base


def _run():
    results = []

    def check(cond, msg):
        results.append(bool(cond))
        print(('  PASS  ' if cond else '  FAIL  ') + msg)

    with open(os.path.join(D, 'fixtures', 'screen-login.ui.json'), encoding='utf-8') as f:
        cap = json.load(f)
    t = M.convert(cap, 'screen-login')

    # 1. 节点数:root + StageBg + 10 元素 = 12
    check(t.count('[node ') == 12, '节点数 = 12(root + StageBg + 10 els)')

    # 2. 命名:figma id 冒号 → 下划线,原始冒号 id 不落入节点名
    check('[node name="1_40" type="Label" parent="."]' in t
          and 'name="1:40"' not in t, '节点名 1:40 → 1_40(冒号换下划线)')

    # 3. 已知父子(1:12 ∈ 1:10)的父相对 offset 手算:286-260=26, 1302-1280=22, +46
    b = _node_block(t, '1_12')
    check('parent="1_10"' in b
          and 'offset_left = 26.0' in b and 'offset_top = 22.0' in b
          and 'offset_right = 72.0' in b and 'offset_bottom = 68.0' in b,
          '1_12 父相对几何 = (26, 22, 72, 68),挂在 1_10 下')

    # 4. StyleBoxFlat:agree-box 圆角 8 四角、描边 2px 白、半透明底
    b = re.search(r'\[sub_resource type="StyleBoxFlat" id="sb_1_30"\]\n(.*?)\n\n', t, re.S).group(1)
    check('bg_color = Color(1, 1, 1, 0.2)' in b
          and b.count('corner_radius_') == 4 and 'corner_radius_top_left = 8' in b
          and b.count('border_width_') == 4 and 'border_width_left = 2' in b
          and 'border_color = Color(1, 1, 1, 1)' in b,
          'sb_1_30:圆角 8×4 + 描边 2×4 白 + rgba(255,255,255,0.2) 底')

    # 5. Label 基础映射:text/字号/对齐
    b = _node_block(t, '1_3')
    check('text = "示例登录"' in b and 'theme_override_font_sizes/font_size = 88' in b
          and 'horizontal_alignment = 1' in b and 'vertical_alignment = 1' in b,
          'Label 1_3:text + font_size 88 + 居中对齐')

    # 6. 文本转义:含换行与引号的 notice-body(多行 → \n 转义 + autowrap)
    cap2 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('9:12', nm='notice-body', tp='TEXT',
            text=dict(content='第一行\n带"引号"行', color='rgba(87,80,63,1)', size=30,
                      family='F', weight=400, lh=48, ls=0, alignH='flex-start',
                      alignV='flex-start', textAlign='left', stroke=''))]}
    t2 = M.convert(cap2, 'esc-case')
    check('text = "第一行\\n带\\"引号\\"行"' in t2, 'notice-body 转义:换行→\\n、引号→\\"')
    check('autowrap_mode = 3' in t2
          and 'theme_override_constants/line_spacing = 18' in t2,
          '多行文本 → autowrap_mode=3;lh 48/size 30 → line_spacing 18')

    # 7. 线性渐变 → Gradient + GradientTexture2D(真渐变,stops+角度)
    cap3 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('7:1', fill='linear-gradient(90deg, rgba(255,0,0,1) 0%, rgba(0,0,255,1) 100%)')]}
    t3 = M.convert(cap3, 'grad-case')
    check('[sub_resource type="Gradient" id="grad_7_1"]' in t3
          and 'offsets = PackedFloat32Array(0, 1)' in t3
          and 'colors = PackedColorArray(1, 0, 0, 1, 0, 0, 1, 1)' in t3
          and 'fill_from = Vector2(0, 0.5)' in t3 and 'fill_to = Vector2(1, 0.5)' in t3
          and 'texture = SubResource("gt_7_1")' in t3,
          '90deg 线性渐变:stops 正确 + fill_from(0,0.5)→fill_to(1,0.5)')

    # 8. 径向渐变 → 平均色 Panel 回退(known-loss)
    cap4 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('8:1', fill='radial-gradient(circle, rgba(255,0,0,1), rgba(0,0,255,1))')]}
    t4 = M.convert(cap4, 'radial-case')
    check('type="Panel"' in t4 and 'bg_color = Color(0.5, 0, 0.5, 1)' in t4,
          '径向渐变 → Panel 平均色 Color(0.5, 0, 0.5, 1) 回退')

    # 9. 四角圆角简写 + 阴影(StyleBoxFlat 原生 shadow,别丢)
    cap5 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('5:1', fill='rgba(0,0,0,1)', radius='1px 2px 3px 4px',
            shadow='0px 4px 0px rgba(0,0,0,0.6)')]}
    t5 = M.convert(cap5, 'sb-case')
    check('corner_radius_top_left = 1' in t5 and 'corner_radius_top_right = 2' in t5
          and 'corner_radius_bottom_right = 3' in t5 and 'corner_radius_bottom_left = 4' in t5,
          '圆角简写 a b c d → TL/TR/BR/BL = 1/2/3/4')
    check('shadow_color = Color(0, 0, 0, 0.6)' in t5 and 'shadow_size = 1' in t5
          and 'shadow_offset = Vector2(0, 4)' in t5,
          '阴影 → shadow_color/shadow_size(硬阴影兜底 1)/shadow_offset(0,4)')

    # 10. rot/opacity:弧度 + 中心 pivot + modulate
    cap6 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('6:1', fill='rgba(255,255,255,1)', rot=45, opacity=0.5, w=40, h=40)]}
    t6 = M.convert(cap6, 'rot-case')
    check('rotation = 0.785398' in t6 and 'pivot_offset = Vector2(20, 20)' in t6
          and 'modulate = Color(1, 1, 1, 0.5)' in t6,
          'rot 45° → rotation 0.785398 rad + pivot 中心;opacity → modulate a=0.5')

    # 11. 百分比圆角:capture 对每个 ELLIPSE 都产 "50%",曾被 float() 抛异常吞掉
    #     → 圆角全丢、椭圆渲染成方块且无告警。口径须与 figma2unreal 一致(min(w,h) 的比例)。
    cap7 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('7:1', fill='rgba(255,0,0,1)', radius='50%', w=100, h=100)]}
    t7 = M.convert(cap7, 'ellipse-case')
    check('corner_radius_top_left = 50' in t7 and 'corner_radius_bottom_right = 50' in t7,
          '百分比圆角 50% + 100x100 → 四角 50(椭圆不再变方块)')
    check(M.parse_radius('50%', 300, 80) == (40, 40, 40, 40),
          '非正方形 300x80 的 50% → min(w,h)/2 = 40(与 unreal 同口径)')
    check(M.parse_radius('50%') is None or M.parse_radius('50%') == (0, 0, 0, 0),
          '缺尺寸时百分比退化为 0/None,不瞎猜')
    check(M.parse_radius('bogus', 100, 100) is None,
          '真正解析不了的仍返回 None')

    ok = all(results)
    print('  %d/%d 通过' % (sum(results), len(results)))
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if _run() else 1)
