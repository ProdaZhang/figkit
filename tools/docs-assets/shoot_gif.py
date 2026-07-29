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

# (step, 这一帧在 GIF 里停留多少毫秒)。step 的含义在 gif_driver.js 的 STEPS 里 ——
# **两边必须对着改**:这张表原本的注释写着「7 = 关闭出场」,而 driver 的第 7 步其实是 guard,
# 出场那一步压根不存在。注释和代码各说各话时,错的通常是没人跑得到的那一份。
FRAMES = [
    (0, 900),                        # 静止
    (1, 90), (2, 90), (3, 700),      # 公告淡入(figma 原稿的 DISSOLVE)→ 停住
    (4, 140),                        # 公告出场中途(preset 补的 SCALE_OUT)
    (5, 90), (6, 90), (7, 900),      # 选服下滑(figma 的 MOVE_IN)+ 逐项 → 停住
    (8, 220),                        # 没勾协议就点开始 → guard 拦下 + 抖动中途
    (9, 260),                        # 勾协议
    (10, 1100),                      # 进入
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
    # ⚠️ 必须绝对化。传相对路径时 file:/// 拼出来的是一个**不存在**的 URL,Edge 照样截图
    # (截的是错误页),每一帧都一样 → Pillow 把相同的连续帧合并 → 产出一张**单帧 GIF**,
    # 而脚本还打印「11 frames」。真踩过:整套跑完全绿,GIF 里一动不动。
    login, out_gif = os.path.abspath(sys.argv[1]), sys.argv[2]
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

    # 每一帧都该跟上一帧不一样 —— 这份 GIF 的全部意义就是"它在动"。
    # 全都一样时 Pillow 会静默合并成单帧,而上面的日志照样报出帧数,看不出来。
    same = [i for i in range(1, len(imgs)) if imgs[i].tobytes() == imgs[i - 1].tobytes()]
    if same:
        raise SystemExit("第 %s 帧与前一帧逐像素相同 —— driver 没演到,或那一步停在了动画之后"
                         % ", ".join(str(FRAMES[i][0]) for i in same))

    pal = [im.convert("P", palette=Image.ADAPTIVE, colors=128) for im in imgs]
    pal[0].save(out_gif, save_all=True, append_images=pal[1:],
                duration=durs, loop=0, optimize=True)
    print("wrote %s (%d frames, %d bytes)" % (out_gif, len(pal), os.path.getsize(out_gif)))


if __name__ == "__main__":
    main()
