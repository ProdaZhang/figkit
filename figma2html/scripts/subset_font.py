# -*- coding: utf-8 -*-
"""字体子集化:收集若干 .ui.json 里实际用到的字 → 子集字体(几十 KB,离线可移植)。
依赖 fonttools + brotli(pip install fonttools brotli)。

用法:
  # ① 静态源字体 → 一份 woff2(给 HTML 的 @font-face)
  python3 subset_font.py <源字体.ttf/.otf> <out.woff2> <ui.json...> [--extra "✓ "]

  # ② 可变源字体 → 按字重实例化出**多份静态**字体(.ttf 给引擎 + .woff2 给 HTML)
  python3 subset_font.py <VF.ttf> <输出目录> <ui.json...> --weights 400,700 --family FigCJK

**为什么要 ②。** 引擎侧(cocos/unity/godot)吃的是静态 .ttf,而 CJK 可变字体的 `wght`
默认值常常不是 400 —— 思源黑体那支 `NotoSansSC-VF.ttf` 默认 **100(Thin)**,直接引用
拿到的是整屏细体,而设计稿里大半文本是 Bold 700。所以字重必须在这一步**实例化**出来。

**两个字重必须是两个不同的族名。** Cocos 在 web 上加载 TTFFont 走的是浏览器 @font-face,
族名取的是**字体文件内部的名字**,而 Label 画字时只给 font-family、不给 font-weight ——
两份文件同名就撞车,浏览器只认一份(实测拿到的是 Regular),整屏该粗的字全是细的。
所以这里把 name 表里的族名改成 `<family>-<Regular|Bold>`。HTML 侧不受影响:
那边自己写 @font-face,族名与字重由 CSS 说了算。

**别再合成一次粗体。** 有了真 Bold 字面,消费方就不能再开引擎的合成粗体
(Unity 的 `-unity-font-style: bold` / Label 的 isBold),否则粗上加粗 —— 实测标题
墨水像素从 1930 涨到 2613。
"""
import json
import os
import sys

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    from fontTools import subset
except ImportError:                      # 唯一的外部依赖,别让人对着 ModuleNotFoundError 猜
    print("需要 fonttools:  pip install fonttools brotli", file=sys.stderr)
    raise SystemExit(2) from None   # 要的是那句提示,不是 ImportError 的栈


def collect_chars(ui_paths):
    chars = set()
    for p in ui_paths:
        d = json.load(open(p, encoding='utf-8'))
        for e in d.get('els', []):
            t = e.get('text')
            if t and t.get('content'):
                chars |= set(t['content'])
    return chars


def weight_name(w):
    return {100: 'Thin', 300: 'Light', 400: 'Regular', 500: 'Medium',
            600: 'SemiBold', 700: 'Bold', 900: 'Black'}.get(w, 'W%d' % w)


def build_instance(src, outdir, family, weight, text):
    """从可变源切出一个字重 → 子集 → 同时落 .ttf(引擎)与 .woff2(HTML)。"""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    f = instancer.instantiateVariableFont(TTFont(src), {'wght': weight}, inplace=False)
    opts = subset.Options()
    opts.layout_features = ['*']          # CJK 的标点/竖排替换都在 features 里,别裁
    opts.name_IDs = ['*']
    opts.notdef_outline = True
    opts.recalc_bounds = True
    s = subset.Subsetter(options=opts)
    s.populate(text=text)
    s.subset(f)

    full = '%s-%s' % (family, weight_name(weight))
    for rec in f['name'].names:
        if rec.nameID in (1, 4, 6, 16):   # family / full / postscript / typographic family
            rec.string = full
    os.makedirs(outdir, exist_ok=True)
    ttf = os.path.join(outdir, full + '.ttf')
    f.save(ttf)
    f.flavor = 'woff2'
    f.save(os.path.join(outdir, full + '.woff2'))
    return ttf


if __name__ == '__main__':
    args = sys.argv[1:]
    extra, weights, family = '', None, 'FigCJK'
    for flag, cast in (('--extra', str), ('--weights', str), ('--family', str)):
        if flag in args:
            i = args.index(flag)
            val = cast(args[i + 1])
            del args[i:i + 2]
            if flag == '--extra':
                extra = val
            elif flag == '--weights':
                weights = [int(x) for x in val.split(',') if x.strip()]
            else:
                family = val
    if len(args) < 2:
        print("用法:\n"
              "  python3 subset_font.py <src.ttf/otf> <out.woff2> [<cap.ui.json> ...] "
              "[--extra 额外字符]\n"
              "  python3 subset_font.py <VF.ttf> <outdir> [<cap.ui.json> ...] "
              "--weights 400,700 [--family FigCJK]\n"
              "  按若干 .ui.json 里出现过的字符做子集化,CJK 字体能从几 MB 压到几十 KB。\n"
              "  给了 --weights 就把可变字体按字重实例化成多份静态字体(引擎要的是静态)。\n"
              "  依赖 fonttools(pip install fonttools brotli)。",
              file=sys.stderr)
        raise SystemExit(2)
    src, out = args[0], args[1]
    chars = collect_chars(args[2:]) | set(extra)
    text = ''.join(sorted(c for c in chars if c.strip())) + extra

    if weights:
        for w in weights:
            p = build_instance(src, out, family, w, text)
            print('%-9s %s  %.1f KB' % (weight_name(w), p, os.path.getsize(p) / 1024.0))
        print('subset %d glyphs x %d weights' % (len(set(text)), len(weights)))
    else:
        subset.main([
            src, '--text=%s' % text, '--flavor=woff2', '--output-file=%s' % out,
            '--layout-features=*', '--no-hinting', '--desubroutinize',
        ])
        print('subset %d glyphs -> %s' % (len(set(text)), out))
