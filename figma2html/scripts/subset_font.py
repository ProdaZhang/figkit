# -*- coding: utf-8 -*-
"""字体子集化:收集若干 .ui.json 里实际用到的字 → 子集 woff2(几十 KB,离线可移植)。
依赖 fonttools + brotli(pip install fonttools brotli)。

用法:
  python subset_font.py <源字体.ttf/.otf> <out.woff2> <ui.json...> [--extra "✓ "]
"""
import sys, json
from fontTools import subset


def collect_chars(ui_paths):
    chars = set()
    for p in ui_paths:
        d = json.load(open(p, encoding='utf-8'))
        for e in d.get('els', []):
            t = e.get('text')
            if t and t.get('content'):
                chars |= set(t['content'])
    return chars


if __name__ == '__main__':
    args = sys.argv[1:]
    extra = ''
    if '--extra' in args:
        i = args.index('--extra'); extra = args[i + 1]; del args[i:i + 2]
    src, out = args[0], args[1]
    ui_paths = args[2:]
    chars = collect_chars(ui_paths) | set(extra)
    text = ''.join(sorted(c for c in chars if c.strip())) + extra
    subset.main([
        src, '--text=%s' % text, '--flavor=woff2', '--output-file=%s' % out,
        '--layout-features=*', '--no-hinting', '--desubroutinize',
    ])
    print('subset %d glyphs -> %s' % (len(set(text)), out))
