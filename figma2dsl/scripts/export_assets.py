"""figma 节点 → PNG 批量导出(per-element 素材)。
用法: python3 export_assets.py <fileKey> <nodeIds 逗号分隔> <outdir> [--token T] [--scale 2]
token 取 --token 或环境变量 FIGMA_TOKEN。需要网络;限流时分批重试。"""
import sys, os, json, time, urllib.request, urllib.parse, urllib.error

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def _get(url, token, tries=6):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"X-Figma-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                ra = e.headers.get("Retry-After")
                wait = int(ra) if (ra and str(ra).isdigit()) else min(60, 5 * (2 ** i))
                print("  429 rate-limited, retry in %ss (%d/%d)" % (wait, i + 1, tries - 1)); sys.stdout.flush()
                time.sleep(wait); continue
            raise

def main(argv):
    if len(argv) < 3:
        print("用法: python3 export_assets.py <fileKey> <nodeIds> <outdir> [--token T] [--scale N]"); return 2
    file_key, ids_csv, outdir = argv[0], argv[1], argv[2]
    token = os.environ.get("FIGMA_TOKEN", "")
    scale = "2"
    if "--token" in argv: token = argv[argv.index("--token")+1]
    if "--scale" in argv: scale = argv[argv.index("--scale")+1]
    if not token: print("缺 token(--token 或 FIGMA_TOKEN)"); return 2
    os.makedirs(outdir, exist_ok=True)
    ids = [s.strip() for s in ids_csv.split(",") if s.strip()]
    q = urllib.parse.urlencode({"ids": ",".join(ids), "format": "png", "scale": scale})
    meta = json.loads(_get("https://api.figma.com/v1/images/%s?%s" % (file_key, q), token))
    images = meta.get("images") or {}
    n = 0
    for nid in ids:
        url = images.get(nid)
        if not url:
            print("  无URL(可能限流/不可见):", nid); continue
        data = _get(url, token)
        fn = "n" + nid.replace(":", "_").replace(";", "__") + ".png"
        with open(os.path.join(outdir, fn), "wb") as f: f.write(data)
        n += 1; print("  ->", fn)
    print("导出 %d/%d" % (n, len(ids)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
