# -*- coding: utf-8 -*-
"""bake_motion.py — flow.json → motion.json(转场缓动的采样曲线表),给 Cocos 侧吃。

用法:
    python3 bake_motion.py <flow.json> <outdir>

**为什么 cocos 也要这一步。** 别的后端是编译型的(产 .tscn / .uss),烘焙顺手挂在
转换器里;cocos 是**运行时解释器**,没有转换器可挂 —— 但曲线该在哪解算不因此改变:

  figma 给的是一条具体曲线(`cubic-bezier(.32,.72,0,1)`)或一组弹簧参数;Creator 的
  `easing.quadOut` 之流是**另一套同名不同形**的曲线。让 TS 侧"挑一个最像的内置缓动",
  同一份 IR 在六个引擎里就是六种手感,而每家测试照样绿(实测量级:easeOutCubic 与
  cubic-bezier(.23,1,.32,1) 最大差 19.8 个百分点,且差在起步段 —— 肉眼看得出,测试看不出)。

所以曲线一律在 python 侧解成 17 个采样点,`flow-binder.ts` 只做线性插值,
再由 tools/conformance 拿 cocos 烘出来的点跟 godot/unity 逐点对账。
`motion.py` 是 figma2html 主拷贝的**逐字节镜像**(skill 必须自足、可单独安装)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 见 motion.py 头部
import motion                                                    # noqa: E402


def bake(flow_path, outdir, sys_mod):
    try:
        with open(flow_path, "r", encoding="utf-8") as f:
            flow = json.load(f)
    except Exception as e:                                       # noqa: BLE001
        sys_mod.stderr.write("[motion] 读不了 %s: %s\n" % (flow_path, e))
        return None
    data, notes = motion.bake_flow(flow, "figma2cocos/scripts/bake_motion.py")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "motion.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    for n in notes:
        sys_mod.stderr.write("[known-loss] motion: " + n + "\n")
    if data["curves"]:
        sys_mod.stderr.write("[motion] 烘出 %d 条曲线 —— 把本文件导进工程,"
                             "拖成 FlowBinder 的 motionAsset\n" % len(data["curves"]))
    return out


def main(argv):
    if len(argv) != 3:
        sys.stderr.write("用法: python3 bake_motion.py <flow.json> <outdir>\n")
        return 2
    out = bake(argv[1], argv[2], sys)
    if out is None:
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
