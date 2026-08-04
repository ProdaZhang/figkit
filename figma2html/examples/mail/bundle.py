# -*- coding: utf-8 -*-
"""把 flow.json + 四屏 .ui.json 内联成 fixtures.js,让 app.html 双击(file://)就能跑。

为什么需要:app.html 是用同步 XHR 去读这些 json 的,而浏览器出于安全会拦掉
file:// 页面对本地文件的 XHR —— 直接双击只会看到白屏,且控制台里的报错
长得像"脚本坏了",很难联想到是跨域。内联是唯一免服务器的走法。
(figkit 的 examples/login 就是这么干的,这里照抄同一套约定。)

改了 flow.json 或重跑了 figma_capture 之后,记得重跑本脚本:
    python bundle.py
"""
import io, json, os

HERE = os.path.dirname(os.path.abspath(__file__))

flow = json.load(io.open(os.path.join(HERE, 'flow.json'), encoding='utf-8'))
bundle = {'flow.json': flow}
for rel in (flow.get('caps') or {}).values():
    p = os.path.normpath(os.path.join(HERE, rel))
    bundle[rel] = json.load(io.open(p, encoding='utf-8'))     # 键必须是 flow 里写的原样相对路径

body = json.dumps(bundle, ensure_ascii=False, indent=1, sort_keys=True)
js = ('// fixtures.js —— bundle.py 生成,别手改。\n'
      '// 内联 flow.json + 四屏 .ui.json,好让 app.html 在 file://(双击打开)下也能跑。\n'
      'window.__FIGKIT_FIXTURES = ' + body + ';\n')
with io.open(os.path.join(HERE, 'fixtures.js'), 'w', encoding='utf-8', newline='\n') as f:
    f.write(js)
print('wrote fixtures.js (%d 条, %d 字节)' % (len(bundle), len(js)))
