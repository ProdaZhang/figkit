"""Minimal synthetic regressions; no private designs, network or browser needed."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import figma_capture as fc

WHITE = {'type':'SOLID','color':{'r':1,'g':1,'b':1,'a':1}}
def node(nid='n', typ='RECTANGLE', w=20, h=10, **kw):
    n=dict(id=nid,type=typ,absoluteBoundingBox=dict(x=0,y=0,width=w,height=h),
           size=dict(x=w,y=h),relativeTransform=[[1,0,0],[0,1,0]],fills=[copy.deepcopy(WHITE)])
    n.update(kw); return n
def frame(*kids):
    return node('root','FRAME',200,200,children=list(kids))
def capture(*kids):
    cap,missing=fc.capture(frame(*kids),'__noassets__','assets')
    assert not missing,missing
    return cap
def text(**kw):
    return node(typ='TEXT',characters='999',style=dict(fontSize=12,fontFamily='Test',fontWeight=400),**kw)

def test_uniform_override_decoration_is_retained_on_replaceable_parent():
    cap=capture(text(characterStyleOverrides=[2,2,2],styleOverrideTable={'2':{'textDecoration':'STRIKETHROUGH','fontWeight':700}}))
    t=cap['els'][0]['text']
    assert t['decoration']=='line-through' and t['weight']==700 and 'runs' not in t
    assert 'text-decoration-line:line-through' in fc.to_html(cap,'test')

def test_base_decoration_and_mixed_utf16_runs():
    n=text(); n['style']['textDecoration']='UNDERLINE'
    assert capture(n)['els'][0]['text']['decoration']=='underline'
    n['characters']='A\U0001f600B'; n['characterStyleOverrides']=[0,2,2,3]
    n['styleOverrideTable']={'2':{'textDecoration':'STRIKETHROUGH'},'3':{'textDecoration':'NONE','fontSize':20}}
    t=capture(n)['els'][0]['text']
    assert [r['content'] for r in t['runs']]==['A','\U0001f600','B']
    assert [r['decoration'] for r in t['runs']]==['underline','line-through','none']
    assert t['runs'][-1]['size']==20

def test_gradient_paint_alpha_does_not_double_node_alpha():
    for opacity,alpha in [(0,0.0),(.27,.135),(1,.5)]:
        p=dict(type='GRADIENT_LINEAR',opacity=opacity,gradientStops=[dict(position=0,color=dict(r=1,g=0,b=0,a=.5))])
        n=node(fills=[p],opacity=.4); cap=capture(n)
        assert 'rgba(255,0,0,%s)' % alpha in cap['els'][0]['fill']
        assert cap['els'][0]['opacity']==.4
        root=frame(); root['fills']=[p]
        assert 'rgba(255,0,0,%s)' % alpha in fc.capture(root,'__noassets__','assets')[0]['stageBg']

def test_mirrors_and_nested_affine_geometry_are_not_double_applied():
    child=node('child',relativeTransform=[[1,0,5],[0,-1,12]])
    parent=node('parent','FRAME',50,40,relativeTransform=[[0,-1,90],[1,0,20]],children=[child])
    cap=capture(parent); p,c=cap['els']
    assert p['matrix']==[0,1,-1,0,90,20]
    assert c['matrix']==[0,1,1,0,78,25]
    css=fc.rec_to_css(c,p)
    assert 'matrix(1,0,0,-1,5,12)' in css,css
    assert 'rotate(' not in css
    horizontal=capture(node(relativeTransform=[[-1,0,20],[0,1,0]]))['els'][0]
    assert horizontal['matrix']==[-1,0,0,1,20,0]

def repeat(count=3,axis='HORIZONTAL',**kw):
    seed=node('seed','ELLIPSE',8,8)
    return node('repeat','TRANSFORM_GROUP',48,8,children=[seed],
                transformModifiers=[dict(type='REPEAT',repeatType='LINEAR',unitType='RELATIVE',axis=axis,count=count,offset=2.5)],**kw)

def test_linear_repeats_keep_spacing_ids_and_source_immutable():
    n=repeat(); before=copy.deepcopy(n); cap=capture(n)
    kids=[r for r in cap['els'] if r['parent']=='repeat']
    assert len(kids)==3 and [r['x'] for r in kids]==[0,20,40]
    assert len({r['id'] for r in cap['els']})==4 and n==before
    assert capture(n)==cap

def test_repeats_follow_rotated_parent_and_vertical_axis():
    n=repeat(relativeTransform=[[-1,0,48],[0,-1,8]])
    cap=capture(n); p=cap['els'][0]
    kids=[r for r in cap['els'] if r['parent']=='repeat']
    assert [r['matrix'][4] for r in kids]==[48,28,8]
    assert 'matrix(1,0,0,1,20,0)' in fc.rec_to_css(kids[1],p)
    cap=capture(repeat(axis='VERTICAL'))
    assert [r['y'] for r in cap['els'][1:]]==[0,20,40]

def test_nested_repeat_and_excessive_count_are_bounded():
    inner=repeat(2); inner['id']='inner'
    outer=repeat(3); outer['children']=[inner]
    cap=capture(outer)
    assert len(cap['els'])==10
    assert len({r['id'] for r in cap['els']})==10
    cap=capture(repeat(1000000))
    assert len(cap['els'])==2 and cap['losses'][0]['code']=='UNSUPPORTED-REPEAT'

def test_shadow_spread_precision_and_vector_filter():
    effect=dict(type='DROP_SHADOW',offset=dict(x=.25,y=4.5),radius=3.5,spread=2,color=dict(r=0,g=0,b=0,a=.2))
    n=node(effects=[effect]); r=capture(n)['els'][0]
    assert r['shadow'].startswith('0.25px 4.5px 3.5px 2px ')
    n.update(type='VECTOR',fillGeometry=[dict(path='M0 0L20 0L10 10Z')])
    cap=capture(n); r=cap['els'][0]
    assert r['vectorShadows'][0]['blur']==1.75
    markup=fc.rec_to_css(r)
    assert 'box-shadow:' not in markup and 'feMorphology' in markup and 'SourceAlpha' in markup

def test_unsupported_custom_paints_are_reported_and_strict_cli_fails():
    n=node(fills=[WHITE,dict(type='CUSTOM',customEffectId='fixture-effect')])
    cap=capture(n)
    assert {r['code'] for r in cap['losses']}=={'CUSTOM-FILL','MULTIPLE-FILLS'}
    with tempfile.TemporaryDirectory(prefix='figkit_strict_') as tmp:
        src=Path(tmp)/'nodes.json';src.write_text(json.dumps({'nodes':{'root':{'document':frame(n)}}}),encoding='utf-8')
        cmd=[sys.executable,'-B',fc.__file__,str(src),'root','test',tmp,'assets',str(Path(tmp)/'out')]
        assert subprocess.run(cmd,capture_output=True).returncode==0
        result=subprocess.run(cmd+['--strict'],capture_output=True)
        assert result.returncode==1 and b'CUSTOM-FILL' in result.stderr

def test_svg_static_ids_do_not_collide_after_sanitising_node_ids():
    a=node('a:b','VECTOR',fillGeometry=[dict(path='M0 0L20 0L10 10Z')])
    b=copy.deepcopy(a);b['id']='a_b'
    import re
    for n in [a,b]:
        n.update(strokes=[WHITE],strokeWeight=1,strokeAlign='INSIDE',strokeGeometry=[dict(path='M0 0L5 5Z')])
    markup=fc.to_html(capture(a,b),'test')
    ids=re.findall(r' id="([^"]+)"',markup)
    assert len(ids)==len(set(ids)) and len(ids)==2

def test_runtime_regressions_with_node_dom_double():
    result=subprocess.run(['node',str(Path(__file__).with_name('runtime-fidelity.cjs'))],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_design_diff_thresholds_include_text_regions():
    try:
        from PIL import Image
    except ImportError:
        print('SKIP optional design-diff threshold test: Pillow not installed')
        return
    from types import SimpleNamespace
    script=Path(__file__).resolve().parents[3]/'tools/design-diff/check.py'
    spec=importlib.util.spec_from_file_location('design_diff',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    args=SimpleNamespace(label='test',rendered='memory',design='memory',heat='',max_mean=None,max_text_mean=0,max_nontext_mean=None)
    cap={'els':[{'x':0,'y':0,'w':8,'h':8,'text':{'content':'test'}}]}
    ref=Image.new('RGB',(20,20),'white');got=ref.copy();got.putpixel((3,3),(0,0,0))
    import contextlib,io
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        assert module.report(ref,ref,cap,args)==0
        assert module.report(ref,got,cap,args)==1
        args.max_text_mean=None;args.max_nontext_mean=0
        assert module.report(ref,got,cap,args)==0  # text gate is independently necessary
        args.max_mean=0
        assert module.report(ref,got,cap,args)==1
    cap['els'][0]['matrix']=[0,1,-1,0,20,5]
    mask,_=module.text_mask(cap,(40,40),margin=0)
    assert mask.getpixel((16,9))==255 and mask.getpixel((2,2))==0

def _run():
    ok=True
    for name,fn in sorted(globals().items()):
        if name.startswith('test_'):
            try: fn();print('PASS',name)
            except Exception as e: ok=False;print('FAIL',name,repr(e))
    return ok

if __name__=='__main__':
    raise SystemExit(0 if _run() else 1)
