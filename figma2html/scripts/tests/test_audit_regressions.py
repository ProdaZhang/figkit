"""Capture/validation regressions from the seven-issue audit (synthetic inputs)."""
import copy
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import figma_capture as fc
import flow_check


def node(nid, typ='RECTANGLE', w=100, h=100, **kw):
    return dict(id=nid, name=nid, type=typ, size=dict(x=w, y=h),
                absoluteBoundingBox=dict(x=0, y=0, width=w, height=h), **kw)


def gradient(start, end):
    return dict(type='GRADIENT_LINEAR', gradientHandlePositions=[dict(x=start[0], y=start[1]), dict(x=end[0], y=end[1])],
                gradientStops=[dict(position=0, color=dict(r=1, g=0, b=0, a=1)),
                               dict(position=1, color=dict(r=0, g=0, b=1, a=1))])


def test_image_paint_alpha_keeps_node_and_child_alpha_independent():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, 'image.png').write_bytes(b'asset presence fixture')
        for alpha in (0, .25, 1):
            image = node('image', 'FRAME', opacity=.6, fills=[dict(type='IMAGE', imageRef='image', opacity=alpha)],
                         children=[node('child', fills=[dict(type='SOLID', color=dict(r=0, g=1, b=0, a=1))])])
            root = node('root', 'FRAME', fills=copy.deepcopy(image['fills']), children=[image])
            cap, missing = fc.capture(root, tmp, 'assets')
            assert not missing
            rec, child = cap['els']
            assert rec.get('imgOpacity', 1) == alpha and rec['opacity'] == .6
            assert child['opacity'] == 1
            assert cap.get('stageBgOpacity', 1) == alpha
            preview = fc.to_html(cap, 'test')
            assert ('data-fig-paint="1"' in preview) == (alpha != 1)
            if alpha != 1:
                assert 'opacity:%g;background:' % alpha in preview


def test_linear_gradient_keeps_handle_positions_for_nodes_and_stage():
    for start, end, stops in [((.25, .5), (.75, .5), [25, 75]),
                              ((-.25, .5), (1.25, .5), [-25, 125]),
                              ((.75, .5), (.25, .5), [25, 75])]:
        paint = gradient(start, end)
        root = node('root', 'FRAME', fills=[paint], children=[node('g', fills=[paint])])
        cap, _ = fc.capture(root, '__noassets__', 'assets')
        for css in (cap['stageBg'], cap['els'][0]['fill']):
            assert [float(x) for x in re.findall(r'([-\d.]+)%', css)] == stops, css
            assert float(re.search(r'gradient\(([-\d.]+)deg', css)[1]) == (270 if start[0] > end[0] else 90)


def test_linear_gradient_uses_pixel_aspect_ratio():
    paint = gradient((0, 0), (1, 1))
    cap, _ = fc.capture(node('root', 'FRAME', children=[node('g', w=200, h=100, fills=[paint])]), '__noassets__', 'assets')
    css = cap['els'][0]['fill']
    assert abs(float(re.search(r'gradient\(([-\d.]+)deg', css)[1]) - 116.565051) < .0001, css
    assert [float(x) for x in re.findall(r'([-\d.]+)%', css)] == [0, 100]
    # The child is locally unrotated but its ancestor rotates its absolute bbox.
    child = node('g', w=200, h=100, fills=[paint], relativeTransform=[[1, 0, 0], [0, 1, 0]])
    child['absoluteBoundingBox'].update(width=100, height=200)
    parent = node('p', 'FRAME', relativeTransform=[[0, -1, 200], [1, 0, 0]], children=[child])
    cap, _ = fc.capture(node('root', 'FRAME', children=[parent]), '__noassets__', 'assets')
    assert next(e for e in cap['els'] if e['id'] == 'g')['fill'] == css


def test_degenerate_linear_gradient_is_a_solid_color():
    assert fc.gradient_css(gradient((.5, .5), (.5, .5)), 100, 100) == 'rgba(0,0,255,1)'


def flow_fixture():
    return (dict(base='base', modals={'公告-详情': dict(cap='m', roots=['panel'], panel='panel')},
                 events=[dict(el='button', do='openModal', arg='公告-详情'),
                         dict(el='@any:公告-详情', do='closeModal')]),
            dict(base=dict(els=[dict(id='button')]), m=dict(els=[dict(id='panel')])) )


def test_unicode_modal_names_pass_the_shared_selector_grammar():
    flow, caps = flow_fixture()
    assert not flow_check.check_flow(flow, caps)
    flow['events'][1]['el'] = '@panelOutside:公告-详情'
    assert not flow_check.check_flow(flow, caps)
    flow['events'][1]['el'] = '@typo:公告-详情'
    assert flow_check.check_flow(flow, caps)


def test_open_modal_target_is_validated_including_missing_and_bad_types():
    for target in ('missing', None, [], {}):
        flow, caps = flow_fixture()
        flow['events'][0]['arg'] = target
        errors = flow_check.check_flow(flow, caps)
        assert any('events[0]' in e and 'openModal' in e for e in errors), errors


def _run():
    failed = []
    for name, fn in sorted(globals().copy().items()):
        if name.startswith('test_'):
            try:
                fn()
                print('PASS', name)
            except Exception as exc:
                failed.append(name)
                print('FAIL', name, repr(exc))
    return not failed


if __name__ == '__main__':
    sys.exit(0 if _run() else 1)
