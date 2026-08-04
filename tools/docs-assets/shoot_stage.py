# -*- coding: utf-8 -*-
"""shoot_stage.py — 把一个示例页拍成**与引擎侧同尺度**的 540×960 舞台图。

用法:
    python3 shoot_stage.py <示例目录> <out.png> [--topbar N]

**为什么需要这么一支专用的。** README 里那对「HTML vs Godot」的对照图一直是**不同尺度**的:
`--screenshot` 拍的是窗口,而页面画在视口里,两者差着滚动条与窗口留白 ——
窗口 540×960 时视口只有 516 宽,舞台按视口缩放(`mountStage` 取 `min(vw/1080,(vh-36)/1920)`),
于是同一份 IR 在浏览器里落到 0.409,在 Godot 里落到 0.5。**肉眼看不出来**(两张图都是 540×960、
内容也都居中),但逐像素一比就是 15.9/255 的平均差 —— 那不是渲染差异,是尺子不一样。

这里把三件事一起解决:

  1. `--hide-scrollbars` —— 视口不再被滚动条切掉;
  2. 窗口 540×**996** —— `mountStage` 会扣掉 36px 顶栏留白,给足了才让舞台正好落在 0.5;
  3. 裁掉底部那 36px。

**`--topbar` 是干什么的。** 上面第 2 条是 `mountStage`(login 那条路)的约定,不是所有示例
都守它:`examples/mail` 的页面自带 `fit()`,直接按 `innerHeight` 等比缩、不预留顶栏。
对它仍按 36 给的话,舞台会在多出来的空间里**居中**,内容整体下移 18px —— 图看着正常,
逐像素比却差 29.7/255,而那全是尺子的错。所以留白量必须跟着页面走:这类页面传 `--topbar 0`。

拍完的图与引擎侧逐像素可比。实测(examples/login,对 Godot 4.3):平均差 **2.18/255**,
只有 **1.70%** 的像素差超过 24 —— 而且全在字形边缘与 1px 抗锯齿圈上,几何完全重合
(xp 条 530–541、按钮 645–704,两边与 IR 的算术值一致)。
"""

import os
import subprocess
import sys
import tempfile

from PIL import Image

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
STAGE_W, STAGE_H = 540, 960
TOPBAR = 36                     # mountStage 里那句 `innerHeight - 36`;自带 fit() 的页面传 0


def find_edge():
    env = os.environ.get("EDGE_PATH")
    if env and os.path.exists(env):
        return env
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Edge(可设 EDGE_PATH)")


def main():
    argv = sys.argv[1:]
    topbar = TOPBAR
    if "--topbar" in argv:
        i = argv.index("--topbar")
        topbar = int(argv[i + 1])
        del argv[i:i + 2]
    if len(argv) < 2:
        raise SystemExit("用法: python3 shoot_stage.py <示例目录> <out.png> [--topbar N]")
    src = os.path.abspath(argv[0])              # 相对路径会拼出不存在的 file:// URL
    out = argv[1]
    page = os.path.join(src, "app.html")
    if not os.path.exists(page):
        raise SystemExit("没有 app.html: " + page)

    tmp = tempfile.mkdtemp(prefix="figkit_stage_")
    shot = os.path.join(tmp, "shot.png")
    subprocess.run([find_edge(), "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--hide-scrollbars",
                    "--window-size=%d,%d" % (STAGE_W, STAGE_H + topbar),
                    "--virtual-time-budget=2500",
                    "--user-data-dir=%s" % os.path.join(tmp, "ud"),
                    "--screenshot=%s" % shot,
                    "file:///%s" % page.replace("\\", "/")], capture_output=True)
    if not os.path.exists(shot):
        raise SystemExit("没截出来")
    im = Image.open(shot).convert("RGB")
    if im.size != (STAGE_W, STAGE_H + topbar):
        raise SystemExit("截图尺寸意外:%s" % (im.size,))
    im.crop((0, 0, STAGE_W, STAGE_H)).save(out)
    print("wrote %s (%dx%d)" % (out, STAGE_W, STAGE_H))



if __name__ == "__main__":
    main()
