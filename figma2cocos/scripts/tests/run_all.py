# -*- coding: utf-8 -*-
# 发现式 runner:跑本目录全部 test_*.py(体例照 figma2dsl/scripts/tests/run_all.py)
import os, sys, importlib.util
d = os.path.dirname(os.path.abspath(__file__))
rc = 0
for fn in sorted(os.listdir(d)):
    if fn.startswith("test_") and fn.endswith(".py"):
        spec = importlib.util.spec_from_file_location(fn[:-3], os.path.join(d, fn))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        print("==", fn, "==")
        if not m._run(): rc = 1
raise SystemExit(rc)
