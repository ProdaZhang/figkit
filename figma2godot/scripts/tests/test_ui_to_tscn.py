# -*- coding: utf-8 -*-
"""ui_to_tscn 单元断言:节点数/命名/父相对几何/文本转义/StyleBoxFlat/渐变。"""
import importlib.util
import json
import os
import re
import sys

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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

    # 8. 径向渐变 → GradientTexture2D 的 FILL_RADIAL(不再是平均色回退)。
    #    捕获层只带出色标(figma 的 handle 位置没跟过来),所以按 CSS 缺省理解:
    #    `ellipse at center` + `farthest-corner`。UV 里的正圆贴到非正方形元素上
    #    自然被拉成椭圆 —— 与 CSS 的缺省形状一致,不用另外补偿。
    cap4 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('8:1', fill='radial-gradient(rgba(255,0,0,1) 0%, rgba(0,0,255,1) 100%)')]}
    t4 = M.convert(cap4, 'radial-case')
    check('type="TextureRect"' in t4 and 'fill = 1' in t4
          and 'fill_from = Vector2(0.5, 0.5)' in t4
          and 'fill_to = Vector2(1.2071, 0.5)' in t4
          and 'colors = PackedColorArray(1, 0, 0, 1, 0, 0, 1, 1)' in t4,
          '径向渐变 → FILL_RADIAL 的 GradientTexture2D(中心→最远角)')
    # 平均色回退还在,但只留给真解不动的(conic 之类)
    t4b = M.convert({'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('8:2', fill='conic-gradient(rgba(255,0,0,1) 0%, rgba(0,0,255,1) 100%)')]}, 'conic')
    check('type="Panel"' in t4b and 'bg_color = Color(0.5, 0, 0.5, 1)' in t4b,
          'conic 等仍走平均色 Panel 回退')

    # 8b. 字形描边:IR 给的是 CSS `-webkit-text-stroke` 的宽度(骑线、可见的是外侧一半),
    #     而 Godot 的 outline_size **不是可见像素数** —— 同一份字体上实测每单位只显出
    #     约 0.3px(底栏页签的描边墨量÷字身墨量:size 6→0.63、12→1.22、18→1.74、20→1.83,
    #     HTML 参照 1.90)。所以按实测标定 ×5/3,而不是照 stroke/2 给(那样细到看不见)。
    tstroke = M.convert({'frame': 'X', 'w': 200, 'h': 60, 'stageBg': '', 'els': [
        dict(_el('9:1', w=200.0, h=60.0),
             text={'content': 'x', 'color': 'rgba(255,255,255,1)', 'size': 36, 'family': 'F',
                   'weight': 400, 'lh': 48, 'ls': 0, 'alignH': 'center', 'alignV': 'center',
                   'textAlign': 'center', 'wrap': False,
                   'stroke': '12.0px rgba(74,74,74,1.0)'})]}, 'stroke-case')
    check('outline_size = 20' in tstroke
          and 'font_outline_color = Color(0.2902, 0.2902, 0.2902, 1)' in tstroke,
          '12px 描边 → outline_size 20(实测标定 ×5/3),颜色照发')

    # 9. 四角圆角简写 + 阴影(StyleBoxFlat 原生 shadow,别丢)
    cap5 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('5:1', fill='rgba(0,0,0,1)', radius='1px 2px 3px 4px',
            shadow='0px 4px 0px rgba(0,0,0,0.6)')]}
    t5 = M.convert(cap5, 'sb-case')
    check('corner_radius_top_left = 1' in t5 and 'corner_radius_top_right = 2' in t5
          and 'corner_radius_bottom_right = 3' in t5 and 'corner_radius_bottom_left = 4' in t5,
          '圆角简写 a b c d → TL/TR/BR/BL = 1/2/3/4')
    # **硬阴影(blur=0)不走 shadow_size。** StyleBoxFlat 的 shadow_size 是"往外扩多少像素",
    # 而 `0px 4px 0px` 的语义是"把整个形状按位移复制一份填成阴影色"。按 shadow_size 画,
    # size 会被 max(1, blur+spread) 夹成 1 —— 设计稿上那块厚实的投影只剩一圈 1px 描边。
    # 现在改为在本体**之前**垫一个同形状同圆角的 Panel(排在前面 = 画在下面)。
    check('shadow_size' not in t5 and 'sh_5_1' in t5
          and t5.index('name="5_1_shadow"') < t5.index('name="5_1" '),
          '硬阴影 → 垫一层同圆角实心 Panel(不是 shadow_size),且排在本体之前')
    sh = t5[t5.index('id="sh_5_1"'):]
    check('bg_color = Color(0, 0, 0, 0.6)' in sh.split('\n\n')[0]
          and 'corner_radius_top_left = 1' in sh.split('\n\n')[0],
          '垫层用阴影色 + 与本体同一套四角圆角')
    blk = t5[t5.index('name="5_1_shadow"'):].split('\n\n')[0]
    check('offset_top = 4.0' in blk and 'offset_left = 0.0' in blk,
          '垫层按 (0,4) 位移')

    # 带模糊的阴影仍走 StyleBoxFlat 原生 shadow —— 那才是 shadow_size 表达得了的东西
    t5b = M.convert({'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('5:2', fill='rgba(0,0,0,1)', shadow='0px 4px 8px rgba(0,0,0,0.6)')]}, 'sb-blur')
    check('shadow_size = 8' in t5b and 'shadow_offset = Vector2(0, 4)' in t5b
          and '5_2_shadow' not in t5b,
          '带模糊的阴影仍走原生 shadow_size,不垫层')

    # 10. rot/opacity:弧度 + 中心 pivot + modulate
    cap6 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('6:1', fill='rgba(255,255,255,1)', rot=45, opacity=0.5, w=40, h=40)]}
    t6 = M.convert(cap6, 'rot-case')
    check('rotation = 0.785398' in t6 and 'pivot_offset = Vector2(20, 20)' in t6
          and 'modulate = Color(1, 1, 1, 0.5)' in t6,
          'rot 45° → rotation 0.785398 rad + pivot 中心;opacity → modulate a=0.5')

    # 11. 百分比圆角:capture 对每个 ELLIPSE 都产 "50%",曾被 float() 抛异常吞掉
    #     → 圆角全丢、椭圆渲染成方块且无告警。口径 = min(w,h) 的比例(见 mapping 的已知取舍)。
    cap7 = {'frame': 'X', 'w': 200, 'h': 200, 'stageBg': '', 'els': [
        _el('7:1', fill='rgba(255,0,0,1)', radius='50%', w=100, h=100)]}
    t7 = M.convert(cap7, 'ellipse-case')
    check('corner_radius_top_left = 50' in t7 and 'corner_radius_bottom_right = 50' in t7,
          '百分比圆角 50% + 100x100 → 四角 50(椭圆不再变方块)')
    check(M.parse_radius('50%', 300, 80) == (40, 40, 40, 40),
          'parse_radius 仍折成 min(w,h)/2 = 40 —— 那是 StyleBoxFlat 那条路的回退口径')
    # 但**实色**的非正方形椭圆角不再走那条路:它落成一份带椭圆角的 .svg,
    # 逐轴按 CSS 算(水平 150、垂直 40),不再是 40 的胶囊。
    check(M.radius_axes('50%', 300, 80) == ((150.0, 40.0),) * 4,
          'radius_axes 逐轴给 CSS 真值:300x80 的 50% = (150, 40)')
    t7b, svgs = M.convert_all({'frame': 'X', 'w': 400, 'h': 200, 'stageBg': '', 'els': [
        _el('7:2', fill='rgba(255,0,0,1)', radius='50%', w=300, h=80)]}, 'oblong')
    check('type="TextureRect"' in t7b and len(svgs) == 1
          and 'A 150 40 0 0 1' in list(svgs.values())[0],
          '非正方形实色 50% → .svg 里画的是 rx=150 ry=40 的真椭圆角')
    check(M.parse_radius('50%') is None or M.parse_radius('50%') == (0, 0, 0, 0),
          '缺尺寸时百分比退化为 0/None,不瞎猜')
    check(M.parse_radius('bogus', 100, 100) is None,
          '真正解析不了的仍返回 None')

    # sub_resource 的 id 规矩比节点名严:Godot 只收 [A-Za-z0-9_]。figma **组件实例**的
    # id 形如 `I25:4109;206:12513;202:12604`(实例链用分号连),节点名那套黑名单换掉冒号
    # 却留下分号 —— 引擎侧报 "The scene unique ID must contain only letters, numbers,
    # and underscores",StyleBoxFlat/Gradient 注册失败,这些元素**裸奔无样式**。
    # 合成夹具里的 id 都是干净的 "1:40",撞不出来;真稿一跑就是几十条(2026-08-04 于 4.7.1)。
    inst = [_el('I25:4109;206:12513;202:12604', fill='rgba(255,0,0,1.0)', radius='8px'),
            _el('I25:2568;135:9615', fill='linear-gradient(0.0deg, rgba(1,2,3,1.0) 0.0%, '
                                          'rgba(4,5,6,1.0) 100.0%)')]
    ti = M.convert(dict(frame='f', w=100, h=50, stageBg='', els=inst), 'screen-inst')
    bad = re.findall(r'\[sub_resource type="[^"]+" id="([^"]*)"\]', ti)
    check(bad and all(re.fullmatch(r'[A-Za-z0-9_]+', s) for s in bad),
          'sub_resource id 只含 [A-Za-z0-9_](组件实例 id 的分号不能漏)')
    # 引用侧必须跟着改名,否则 SubResource("...") 指向一个不存在的 id
    check(all(('SubResource("%s")' % s) in ti for s in bad),
          'SubResource() 引用与 sub_resource id 一致')

    # 圆角裁剪嵌套时,clip_children 该给**最外层**。Godot 不支持嵌套,一条链只能留一个:
    # 外层裁的是压在背景上的外轮廓,丢了就是四个方角怼底色(实测:邮件面板 80px 圆角
    # 退成矩形剪刀,底部两角变硬直角);内层裁的是纹理/装饰,退成矩形只多出一点同色方角。
    nest = [_el('n:1', radius='80px', clip=True, w=400, h=300),
            _el('n:2', parent='n:1', radius='40px', clip=True, w=200, h=100),
            _el('n:3', parent='n:2', fill='rgba(1,2,3,1.0)', w=300, h=200)]
    tn = M.convert(dict(frame='f', w=400, h=300, stageBg='', els=nest), 'screen-nest')
    check('clip_children' in _node_block(tn, 'n_1'),
          '外层圆角裁剪拿 clip_children(轮廓优先)')
    check('clip_contents = true' in _node_block(tn, 'n_2')
          and 'clip_children' not in _node_block(tn, 'n_2'),
          '内层退化成矩形 clip_contents(Godot 的 clip_children 不能嵌套)')
    # 空模子会把子节点裁得一干二净 —— 只负责裁的容器在 IR 里没填充,必须自己画出实心形状
    check('bg_color = Color(1, 1, 1, 1)' in _node_block(tn, 'n_1')
          or 'bg_color = Color(1, 1, 1, 1)' in tn.split('[node ')[0],
          '当模子的容器要有实心底,否则子节点全被裁没')
    check(any('n:2' in s and '圆角裁剪退回矩形' in s
              for s in M.collect_losses(dict(frame='f', w=400, h=300, stageBg='', els=nest))),
          '退化的那一层要留痕(honest degradation)')

    ok = all(results)
    print('  %d/%d 通过' % (sum(results), len(results)))
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if _run() else 1)
