import os, sys, importlib.util

# 测试输出含中文;Windows 控制台默认代码页(CI 上是非 CJK)会让 print 抛 UnicodeEncodeError,
# 整套测试因此在 windows-latest 上红 —— 与被测逻辑毫无关系。把本进程输出钉成 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
d = os.path.dirname(os.path.abspath(__file__))
rc = 0
for fn in sorted(os.listdir(d)):
    if fn.startswith("test_") and fn.endswith(".py"):
        spec = importlib.util.spec_from_file_location(fn[:-3], os.path.join(d, fn))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        print("==", fn, "==")
        if not m._run(): rc = 1
raise SystemExit(rc)
