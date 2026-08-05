# -*- coding: utf-8 -*-
"""design-diff — 拿 **figma 自己导出的那一帧** 当地面真值,量 figkit 渲出来的差多少。

    python3 tools/design-diff/check.py <screen.ui.json> <figma-export.png> [--heat out.png]
    python3 tools/design-diff/check.py <screen.ui.json> <figma-export.png> --rendered <engine.png>

第二种形式是给**引擎**用的:Unity / Godot / Cocos 各自渲出来的那张 PNG 直接喂进来,
省得这支脚本去认四套构建管线。要求它是**帧原尺寸**(与导出图同尺度),别缩放过。

**为什么需要它。** README 里那张四端对照表的每个数字,量的都是"各引擎 vs figkit 自己的 HTML
产物" —— 它证明的是**四端一致**,不是**忠于设计稿**。这两件事不一样:capture 只要把设计读错了,
四个后端就会**一致地**错,而全套测试一路绿。这正是本仓在别处写过的那句话("一致不是正确")
往上再推一层,落在捕获层自己身上 —— 而那一层此前没有任何东西守着。

这支脚本把 figma 导出的 PNG 当基准,渲一屏 `.ui.json` 出来逐像素比,并且把误差**拆成
文字与非文字两半**:字形栅格化在两个渲染器之间永远对不齐(figma 有自己的 hinting,
浏览器有自己的),那部分差异是噪声;真正说明问题的是**文字之外**那半 —— 几何、颜色、
圆角、描边、图片有没有落在设计说的地方。

用法上的四条要求:
  1. 导出必须是 **1×、帧原尺寸**(figma 里选中帧 → Export → PNG,缩放 1x)。
     导 2x 再缩回来会引入一次重采样,量出来的全是它。
  2. 屏与导出必须是**同一个变体**。设计稿改过之后再导,比的就是两份内容,数字没有意义
     (实测踩过:某一屏的奖励格在新版里换了品质底色与数量,均差从 1.2 跳到 4.2,
     和渲染保真毫无关系)。
  3. 渲染走 **render.js**(运行时那条路),不是 capture 顺手产的 `.tree.html` 预览 ——
     那两套贴样式逻辑是平行实现,比错了就答非所问。
  4. **文案要装得进设计给的盒子**。字长过盒子,溢出去那截就落进"文字外"那半,
     被当成几何误差(实测:示例译成英文后正文多绕一行,详情屏 0.53 → 0.82,
     渲染没动一个像素)。`tools/html-smoke/` 会在真浏览器里替你量这一条。

依赖 Pillow 与 Edge/Chromium,所以放在 `tools/` 而不是任何 skill 里(skill 必须零依赖)。
"""
import argparse
import http.server
import io
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PIL import Image, ImageChops, ImageDraw
except ImportError:
    print("需要 Pillow:  pip install pillow", file=sys.stderr)
    raise SystemExit(2) from None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
]

# 只渲一屏、不装配 flow。字体那两条 @font-face 与示例页保持一致 —— 少了它,
# 整屏回退到系统字体,量到的差异全是字形噪声。
PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>design-diff</title><style>
@font-face { font-family:'FigCJK'; src:url('fonts/FigCJK-Regular.woff2') format('woff2');
             font-weight:400; font-display:block; }
@font-face { font-family:'FigCJK'; src:url('fonts/FigCJK-Bold.woff2') format('woff2');
             font-weight:700; font-display:block; }
*{margin:0;padding:0;box-sizing:border-box}
body{background:%(bg)s;width:%(w)dpx;height:%(h)dpx;overflow:hidden;
     font-family:'FigCJK','Source Han Sans SC','Noto Sans SC','Microsoft YaHei',sans-serif;
     user-select:none}
#stage{position:absolute;left:0;top:0;width:%(w)dpx;height:%(h)dpx;overflow:hidden}
</style></head><body><div id="stage"></div>
<script src="__runtime_render.js"></script>
<script>
var x = new XMLHttpRequest();
x.open('GET', '%(cap)s', false); x.send(null);
renderScreen(JSON.parse(x.responseText), document.getElementById('stage'), '');
</script></body></html>
"""


def find_browser():
    env = os.environ.get("EDGE_PATH")
    if env and os.path.exists(env):
        return env
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Edge/Chromium(可设 EDGE_PATH)")


def serve(directory):
    handler = type("H", (http.server.SimpleHTTPRequestHandler,), {
        "directory_": directory,
        "__init__": lambda self, *a, **k: http.server.SimpleHTTPRequestHandler.__init__(
            self, *a, directory=directory, **k),
        "log_message": lambda *a: None,
    })
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def text_mask(cap, size, margin=4):
    """文字元素的盒子(外扩 margin) —— 抗锯齿会溢出盒沿,不扩会把边上那圈算进"非文字"。"""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    n = 0
    for e in cap.get("els", []):
        t = e.get("text")
        if not t or not t.get("content"):
            continue
        n += 1
        x, y = e.get("x") or 0, e.get("y") or 0
        w, h = e.get("w") or 0, e.get("h") or 0
        d.rectangle([x - margin, y - margin, x + w + margin, y + h + margin], fill=255)
    return m, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cap")
    ap.add_argument("design")
    ap.add_argument("--heat", default="")
    ap.add_argument("--rendered", default="",
                    help="已经渲好的 PNG(引擎产物);给了就不再自己渲 HTML")
    ap.add_argument("--label", default="", help="报告里显示的这一端的名字")
    ap.add_argument("--shot", default="")
    args = ap.parse_args()

    cap_path = os.path.abspath(args.cap)
    cap_dir = os.path.dirname(cap_path)
    cap = json.load(io.open(cap_path, encoding="utf-8"))
    w, h = int(cap.get("w") or 0), int(cap.get("h") or 0)
    if not w or not h:
        raise SystemExit("这份 .ui.json 没有 w/h,渲不出固定尺寸")

    ref = Image.open(args.design).convert("RGB")
    if ref.size != (w, h):
        raise SystemExit("导出图 %s 与帧尺寸 %dx%d 不一致 —— 请按 **1x** 导出整帧"
                         % (ref.size, w, h))

    if args.rendered:
        got = Image.open(args.rendered).convert("RGB")
        if got.size != (w, h):
            raise SystemExit("--rendered 的图 %s 不是帧原尺寸 %dx%d —— 别缩放过再喂进来"
                             % (got.size, w, h))
        return report(ref, got, cap, args)

    # 运行时拷进屏所在目录:render.js 与 .ui.json 必须同源可取,免得跨目录再起一层服务
    rt_src = os.path.join(ROOT, "figma2html", "runtime", "render.js")
    rt_dst = os.path.join(cap_dir, "__runtime_render.js")
    page = os.path.join(cap_dir, "__design_diff.html")
    tmp = tempfile.mkdtemp(prefix="figkit_dd_")
    shot = args.shot or os.path.join(tmp, "shot.png")
    try:
        io.open(rt_dst, "w", encoding="utf-8", newline="").write(
            io.open(rt_src, encoding="utf-8").read())
        io.open(page, "w", encoding="utf-8", newline="").write(PAGE % {
            "w": w, "h": h, "bg": cap.get("stageBg") or "#333",
            "cap": os.path.basename(cap_path)})
        srv, port = serve(cap_dir)
        try:
            subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--hide-scrollbars", "--window-size=%d,%d" % (w, h),
                            "--virtual-time-budget=6000",
                            "--user-data-dir=%s" % os.path.join(tmp, "ud"),
                            "--screenshot=%s" % shot,
                            "http://127.0.0.1:%d/__design_diff.html" % port],
                           capture_output=True)
        finally:
            srv.shutdown()
        if not os.path.exists(shot):
            raise SystemExit("没截出来")
        got = Image.open(shot).convert("RGB")
    finally:
        for f in (rt_dst, page):
            if os.path.exists(f):
                os.remove(f)

    return report(ref, got, cap, args)


def report(ref, got, cap, args):
    diff = ImageChops.difference(ref, got)
    mask, ntext = text_mask(cap, ref.size)
    dp = list(diff.getdata())
    mp = list(mask.getdata())
    n = len(dp)
    total = 0
    intext = 0
    ntx = 0
    over = 0
    for i, p in enumerate(dp):
        s = p[0] + p[1] + p[2]
        total += s
        if max(p) > 24:
            over += 1
        if mp[i]:
            intext += s
            ntx += 1
    print("端      %s" % (args.label or ("render.js" if not args.rendered else os.path.basename(args.rendered))))
    print("基准    %s" % os.path.basename(args.design))
    print("文字盒  %d 个,覆盖 %.1f%% 画面" % (ntext, 100.0 * ntx / n))
    print("全帧    mean %.2f/255   >24 的像素 %.1f%%" % (total / (3.0 * n), 100.0 * over / n))
    print("文字内  mean %.2f/255" % (intext / (3.0 * max(ntx, 1))))
    print("文字外  mean %.2f/255   ← 几何/颜色/圆角/描边/图片,真正说明问题的是这个"
          % ((total - intext) / (3.0 * max(n - ntx, 1))))
    if args.heat:
        diff.point(lambda v: min(255, v * 4)).save(args.heat)
        print("热图    %s(差异 ×4,黑=一致)" % args.heat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
