# -*- coding: utf-8 -*-
"""录 README 的 demo.gif:Edge 无头逐帧截图 → Pillow 编码。

无头浏览器没法录屏,所以走**分帧确定性重放**:每一帧起一个新页面,用 ?step=N 告诉
gif_driver.js 演到哪一步、并把真实动画对象暂停在指定毫秒,再截一张。
同一个脚本跑两次得到同一串图。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# (step, 这一帧在 GIF 里停留多少毫秒)
FRAMES = [
    (0, 900),    # 静止
    (1, 90), (2, 90), (3, 800),      # 公告淡入 → 停住
    (4, 90), (5, 90), (6, 900),      # 选服下滑 + 逐项 → 停住
    (7, 120),                        # 关闭出场
    (8, 260),                        # 按下 START
    (9, 1100),                       # 进入
]


def find_edge():
    env = os.environ.get("EDGE_PATH")
    if env and os.path.exists(env):
        return env
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Edge")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    login, out_gif = sys.argv[1], sys.argv[2]
    edge = find_edge()

    with io.open(os.path.join(login, "app.html"), encoding="utf-8") as f:
        page = f.read()
    page = page.replace("</body>", '  <script src="_gif.js"></script>\n</body>')
    gif_html = os.path.join(login, "_gif.html")
    with io.open(gif_html, "w", encoding="utf-8", newline="") as f:
        f.write(page)
    shutil.copy(os.path.join(here, "gif_driver.js"), os.path.join(login, "_gif.js"))

    tmp = tempfile.mkdtemp(prefix="figkit_gif_")
    imgs, durs = [], []
    try:
        for step, dur in FRAMES:
            png = os.path.join(tmp, "s%d.png" % step)
            url = "file:///%s?step=%d" % (gif_html.replace("\\", "/"), step)
            subprocess.run([edge, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--window-size=540,960", "--virtual-time-budget=2500",
                            "--user-data-dir=%s" % os.path.join(tmp, "ud%d" % step),
                            "--screenshot=%s" % png, url], capture_output=True)
            if not os.path.exists(png):
                raise SystemExit("step %d 没截出来" % step)
            im = Image.open(png).convert("RGB")
            imgs.append(im.resize((im.width // 2, im.height // 2), Image.LANCZOS))
            durs.append(dur)
            print("step %d  %dx%d  hold=%dms" % (step, im.width, im.height, dur))
    finally:
        for f_ in (gif_html, os.path.join(login, "_gif.js")):
            if os.path.exists(f_):
                os.remove(f_)

    pal = [im.convert("P", palette=Image.ADAPTIVE, colors=128) for im in imgs]
    pal[0].save(out_gif, save_all=True, append_images=pal[1:],
                duration=durs, loop=0, optimize=True)
    print("wrote %s (%d frames, %d bytes)" % (out_gif, len(pal), os.path.getsize(out_gif)))


if __name__ == "__main__":
    main()
