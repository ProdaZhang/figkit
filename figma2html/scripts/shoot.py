# -*- coding: utf-8 -*-
"""Edge 无头截图封装(固化踩过的坑:虚拟时间预算等 JS/字体加载、独立 user-data-dir 防锁、
本机 540×960 稳、1080×1920 易黑屏)。

用法:
  python3 shoot.py <url> <out.png> [--w 540 --h 960 --wait 4500]
"""
import sys, os, tempfile, subprocess

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    env = os.environ.get("EDGE_PATH")          # 跨机器/非默认安装:环境变量优先
    if env:
        if os.path.exists(env):
            return env
        raise SystemExit("EDGE_PATH 指向的文件不存在: %s" % env)
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Edge(可设环境变量 EDGE_PATH 指定其它 Edge/Chromium 路径)")


if __name__ == '__main__':
    args = sys.argv[1:]
    opt = {'--w': '540', '--h': '960', '--wait': '4500'}
    pos = []
    i = 0
    while i < len(args):
        if args[i] in opt:
            opt[args[i]] = args[i + 1]; i += 2
        else:
            pos.append(args[i]); i += 1
    if len(pos) < 2:
        print("用法: python3 shoot.py <url> <out.png> [--w 540] [--h 960] [--wait 2000]\n"
              "  用无头 Edge 截图核验渲染结果;url 可以是 http:// 也可以是 file://。\n"
              "  例: python3 shoot.py http://localhost:8321/examples/login/app.html out.png --w 540 --h 960",
              file=sys.stderr)
        raise SystemExit(2)
    url, out = pos[0], pos[1]
    udd = tempfile.mkdtemp(prefix='shoot_')
    cmd = [find_edge(), '--headless=new', '--disable-gpu', '--no-sandbox',
           '--user-data-dir=' + udd, '--virtual-time-budget=' + opt['--wait'],
           '--window-size=%s,%s' % (opt['--w'], opt['--h']),
           '--screenshot=' + out, url]
    subprocess.run(cmd)
    print('OK' if os.path.exists(out) else 'FAIL', out)
