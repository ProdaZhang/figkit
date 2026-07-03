"""工具2 · 界面知识库还原器(确定性纯脚本,仅标准库)。

把界面 DSL(.md)解析成元素列表,再渲染成自包含 html(L0线稿/L1皮肤/L2氛围
三档切换)+ 可选 svg 静态快照。同 DSL + 同版本 → 输出字节一致。

皮肤(配色)非渲染必需:md 内可选 `## 皮肤` 段(id 或类型 → 色),或外部
`--skin theme.skin.json`(同键覆盖皮肤段);都没有则回退类型默认 L1。
分层 z 可选——无 z 时按 (缩进, 文档顺序) 兜底。

用法: python ui_render.py <dsl.md> [out.html] [--svg out.svg] [--skin theme.skin.json]
"""
import re, sys, json, os

_GEO = re.compile(r"@\{([^}]*)\}")
_ID  = re.compile(r":([^\s\[\]]+)")
_Z   = re.compile(r"z=(\d+)")
_REP = re.compile(r"[×x](\d+)")
_BR  = re.compile(r"\[([^\]]+)\]")
_TXT = re.compile(r'"([^"]*)"')
_SHAPE = re.compile(r"形=([^\s]+)")
_SKINHEX = re.compile(r"#[0-9a-fA-F]{6}")
_META_KIND = re.compile(r"类型\s*[:：]\s*(\S+)")
_META_SIZE = re.compile(r"尺寸\s*[:：]\s*(\d+)\s*[×xX*]\s*(\d+)")
_META_COORD = re.compile(r"坐标系\s*[:：]\s*(\S+)")


def recommend_size(img_w, img_h):
    """按 UI设计规范:横版锁高1080、竖版锁宽1080,另一轴按原图比例(给捕获 skill 写 > 尺寸)。"""
    if img_w >= img_h:
        return (int(round(1080.0 * img_w / img_h)), 1080)
    return (1080, int(round(1080.0 * img_h / img_w)))


def _parse_skin_lines(lines):
    """`## 皮肤` 段 → {键: {fill, ink}};键 = 元素 id 或 类型(类型主题)。

    行格式: `键  #填充[/#文字]`(键在前、色在后)。以 `#` 起头的行视作注释跳过
    (皮肤行键在前,不会以 `#` 开头),色取行内 `#RRGGBB`:第一个=填充、第二个=文字。
    """
    skin = {}
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        hexes = _SKINHEX.findall(s)
        if not hexes:
            continue
        key = s[:s.index(hexes[0])].strip().rstrip(":：").strip()
        if not key:
            continue
        skin[key] = {"fill": hexes[0], "ink": hexes[1] if len(hexes) > 1 else ""}
    return skin


def parse_dsl(text):
    """界面 DSL 文本 → {screen, palette, skin, elements[], events[]}。

    Layout 行文法(基准): 名称 [:id] [类型] @{x y w h} [z=N] [形=形状] [[态]] [×N] ["文本"]
    类型 = @{ 之前的方括号; 态 = @{...} 之后的方括号; 无 @{} 的行(标题/注释)跳过。
    缩进 = 嵌套层级(子元素缩进更深);分层无 z 时按 (缩进, 文档顺序) 兜底,见 _enrich。
    `## 皮肤` 段(可选) = id 或 类型 → 颜色,见 _parse_skin_lines。
    """
    screen, palette = "", None
    kind, size = "屏", (2400, 1080)
    coordmode = ""
    elements, events, pal_lines, skin_lines, imports = [], [], [], [], {}
    yuantu = {}
    section = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            screen = line[2:].strip(); continue
        if line.startswith("## "):
            head = line[3:].strip()
            section = next((k for k in ("Layout", "Events", "配色板", "设计点评", "皮肤", "引用", "原图")
                            if head.startswith(k)), None)
            continue
        if line.startswith(">"):
            body = line.lstrip(">").strip()
            mk = _META_KIND.search(body)
            if mk:
                kind = mk.group(1)
            msz = _META_SIZE.search(body)
            if msz:
                size = (int(msz.group(1)), int(msz.group(2)))
            mc = _META_COORD.search(body)
            if mc:
                coordmode = mc.group(1)
            continue
        if line.strip().startswith("```"):
            continue
        if not line.strip():
            continue
        if section == "配色板":
            pal_lines.append(line.strip()); continue
        if section == "皮肤":
            skin_lines.append(line.strip()); continue
        if section == "原图":
            s = line.strip()
            if s and not s.startswith("#"):
                parts = s.split(None, 1)
                if len(parts) == 2:
                    yuantu[parts[0].strip()] = parts[1].strip()
            continue
        if section == "引用":
            mi = re.match(r"(.+?)\s*=\s*(.+)", line.strip())
            if mi:
                imports[mi.group(1).strip()] = mi.group(2).strip()
            continue
        if section == "Events":
            events.append(line.strip()); continue
        if section == "Layout":
            m = _GEO.search(line)
            if not m:
                continue
            indent = len(line) - len(line.lstrip())
            pre, post = line[:m.start()], line[m.end():]
            geo = m.group(1).split()
            x = float(geo[0]); y = float(geo[1])
            w = float(geo[2]) if len(geo) > 2 else None
            h = float(geo[3]) if len(geo) > 3 else None
            mid = _ID.search(pre)
            eid = mid.group(1) if mid else None
            tb = _BR.search(pre)
            etype = tb.group(1) if tb else "未知"
            name = pre
            if mid:
                name = name.replace(":" + eid, "")
            if tb:
                name = name.replace("[" + etype + "]", "")
            name = name.strip()
            mz = _Z.search(post)
            z = int(mz.group(1)) if mz else None
            ms = _BR.search(post)
            state = ms.group(1) if ms else None
            mr_name = _REP.search(name)
            mr = mr_name or _REP.search(post)
            repeat = int(mr.group(1)) if mr else 1
            if mr_name:
                name = _REP.sub("", name).strip()
            mt = _TXT.search(post)
            etext = mt.group(1) if mt else None
            msh = _SHAPE.search(post)
            shape = msh.group(1) if msh else None
            elements.append({"name": name, "id": eid, "type": etype,
                             "x": x, "y": y, "w": w, "h": h, "z": z,
                             "indent": indent, "state": state,
                             "repeat": repeat, "text": etext, "shape": shape})
    if pal_lines:
        palette = " · ".join(pal_lines)
    return {"screen": screen, "palette": palette,
            "kind": kind, "size": size, "imports": imports,
            "coordmode": coordmode,
            "skin": _parse_skin_lines(skin_lines),
            "yuantu": yuantu,
            "elements": elements, "events": events}


def validate(parsed):
    """提醒(非阻断):返回未标 z 的元素标识列表。缺 z 时分层按 (缩进, 文档顺序) 兜底。"""
    return [(e["name"] or e["id"] or e["type"]) for e in parsed["elements"] if e["z"] is None]


def normalize_coords(parsed):
    """坐标系=父相对px 时,按缩进推父、累加 px 原点、除以 stage 尺寸 → 绝对屏百分比(就地改 elements)。
    其它坐标系(默认百分比)原样返回。"""
    if parsed.get("coordmode") != "父相对px":
        return parsed
    sw, sh = parsed["size"]
    stack = []  # [(indent, abs_x_px, abs_y_px)]
    for e in parsed["elements"]:
        ind = e.get("indent", 0)
        while stack and stack[-1][0] >= ind:
            stack.pop()
        px = stack[-1][1] if stack else 0.0
        py = stack[-1][2] if stack else 0.0
        ax = px + (e["x"] or 0.0)
        ay = py + (e["y"] or 0.0)
        w = e["w"] or 0.0
        h = e["h"] or 0.0
        stack.append((ind, ax, ay))
        e["x"] = ax / sw * 100.0 if sw else 0.0
        e["y"] = ay / sh * 100.0 if sh else 0.0
        e["w"] = w / sw * 100.0 if sw else 0.0
        e["h"] = h / sh * 100.0 if sh else 0.0
    return parsed


_INST = "实例·"


def _fit_contain(ix, iy, iw, ih, mod_w, mod_h, sw, sh):
    """包围盒(屏%)+模块像素+屏像素 → 模块等比居中后的子矩形(屏%)。"""
    bw, bh = iw / 100.0 * sw, ih / 100.0 * sh
    if bw <= 0 or bh <= 0 or mod_w <= 0 or mod_h <= 0:
        return ix, iy, iw, ih
    am, ab = mod_w / mod_h, bw / bh
    if ab > am:
        dh, dw = bh, bh * am
    else:
        dw, dh = bw, bw / am
    mx, my = (bw - dw) / 2.0, (bh - dh) / 2.0
    return (ix + mx / sw * 100.0, iy + my / sh * 100.0, dw / sw * 100.0, dh / sh * 100.0)


def _place(e, mod_w, mod_h, sw, sh):
    """实例 → 模块内容在屏上的子矩形(屏%)。4 值 → contain 进框;否则 → 原像素左上放置。"""
    if e["w"] is not None and e["h"] is not None:
        return _fit_contain(e["x"], e["y"], e["w"], e["h"], mod_w, mod_h, sw, sh)
    if sw <= 0 or sh <= 0:
        return (e["x"], e["y"], 0.0, 0.0)
    return (e["x"], e["y"], mod_w / sw * 100.0, mod_h / sh * 100.0)


def resolve(parsed, base_dir, modules_dir=None, _stack=()):
    """展开所有 实例· 元素为扁平绝对元素;返回新 parsed(elements/skin 合并,imports 清空)。"""
    sw, sh = parsed["size"]
    imports = parsed.get("imports") or {}
    out_els, out_skin = [], dict(parsed.get("skin") or {})
    for e in parsed["elements"]:
        t = e["type"]
        if not t.startswith(_INST):
            out_els.append(e); continue
        alias = t.split("·", 1)[1]
        rel = imports.get(alias)
        if rel is None:
            raise ValueError("未声明引用: %s(在 ## 引用 加 '%s = 路径')" % (alias, alias))
        path = os.path.normpath(os.path.join(base_dir, rel))
        if not os.path.exists(path) and modules_dir:
            path = os.path.normpath(os.path.join(modules_dir, rel))
        if path in _stack:
            raise ValueError("模块循环引用: %s" % " -> ".join(list(_stack) + [path]))
        with open(path, encoding="utf-8") as f:
            sub = parse_dsl(f.read())
        sub = resolve(sub, os.path.dirname(path), modules_dir, tuple(_stack) + (path,))
        mw, mh = sub["size"]
        cx, cy, cw, ch = _place(e, mw, mh, sw, sh)
        layer = e["z"] if e["z"] is not None else e.get("indent", 0)
        pid = e["id"]
        sub_skin = sub.get("skin") or {}
        kids = sorted(sub["elements"],
                      key=lambda k: (k["z"] if k["z"] is not None else k.get("indent", 0)))
        for k in kids:
            nk = dict(k)
            nk["x"] = cx + k["x"] / 100.0 * cw
            nk["y"] = cy + k["y"] / 100.0 * ch
            nk["w"] = k["w"] / 100.0 * cw
            nk["h"] = k["h"] / 100.0 * ch
            nk["z"] = layer
            nk["indent"] = 0
            nid = (pid + "." + k["id"]) if (pid and k["id"]) else k["id"]
            nk["id"] = nid
            c = sub_skin.get(k["id"]) or sub_skin.get(k["type"]) or sub_skin.get(k["type"].split("·")[0])
            if c and nid:
                out_skin[nid] = c
            out_els.append(nk)
    new = dict(parsed)
    new["elements"] = out_els
    new["skin"] = out_skin
    new["imports"] = {}
    return new


TYPE_ABBR = {"按钮": "anniu", "文本": "wenben", "图标槽": "tubiao",
             "背景槽": "beijing", "立绘槽": "lihui", "面板": "mianban",
             "容器": "rongqi", "数值条": "shuzhitiao", "装饰": "zhuangshi",
             "chrome": "chrome", "未知": "unknown"}


def _enrich(elements, skin=None, yuantu=None):
    """skin 已是合并后的有效皮肤(id/类型混键);查色优先级 id → 类型 → `·`前基础类型。

    分层 layer = z(若标);否则按缩进深度兜底(子元素缩进更深 → 叠在父容器上),
    同层由文档顺序决定(svg 稳定排序 / html DOM 追加序)。
    yuantu = {元素id: 图片路径};有原图的元素 img 字段非空,渲染时优先贴背景图。
    """
    skin = skin or {}
    yuantu = yuantu or {}
    out = []
    for e in elements:
        t = e["type"]
        base = t.split("·")[0]
        abbr = TYPE_ABBR.get(t) or TYPE_ABBR.get(base, "unknown")
        sk = skin.get(e["id"]) or skin.get(t) or skin.get(base) or {}
        layer = e["z"] if e["z"] is not None else e.get("indent", 0)
        out.append({"id": e["id"], "type": t, "abbr": abbr,
                    "label": e["name"] or (e["id"] or e["type"]),
                    "text": e["text"] or "",
                    "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
                    "z": e["z"], "layer": layer, "indent": e.get("indent", 0),
                    "state": e["state"] or "", "repeat": e["repeat"],
                    "shape": e.get("shape") or "",
                    "fill": sk.get("fill") or "", "ink": sk.get("ink") or "",
                    "img": yuantu.get(e["id"], "")})
    return out


def _eff_skin(parsed, external=None):
    """有效皮肤 = md 内 `## 皮肤` 段,被外部 --skin 覆盖(同键 --skin 优先)。"""
    eff = dict(parsed.get("skin") or {})
    eff.update(external or {})
    return eff


def _els_json(elements, skin=None, yuantu=None):
    return json.dumps(_enrich(elements, skin, yuantu), ensure_ascii=False)


HTML_TEMPLATE = r'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>{SCREEN}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0c0e13;color:#cdd3dd;font:14px/1.45 "Segoe UI","Microsoft YaHei",sans-serif}
header{padding:10px 16px;background:#161922;border-bottom:1px solid #262b38;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header b{color:#fff}
button{background:#26304a;color:#cfe0f0;border:1px solid #3a4a6a;border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit}
button.on{background:#7a3ac0;border-color:#9a5ae0;color:#fff}
.viewport{padding:18px;overflow:auto}
.stage{position:relative;width:{STAGEW}px;height:{STAGEH}px;border:1px solid #2a3040;transform-origin:top left;background:#12151d}
.stage.skin,.stage.atmo{background:radial-gradient(120% 90% at 38% 42%,#1c0f18,#140b14 55%,#08060c)}
.el{position:absolute;display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden;cursor:pointer;box-sizing:border-box;transition:.1s;z-index:2}
.el:hover{outline:2px solid #ffffff88;outline-offset:1px;z-index:900}
.stage.wire .el{border:1.5px solid #4a90d9;border-radius:4px;padding:6px 4px 4px}
.stage.wire .tag{position:absolute;top:0;left:0;font-size:10px;line-height:1.1;padding:2px 5px;background:rgba(0,0,0,.55);color:#cfe0f0;border-bottom-right-radius:5px;white-space:nowrap}
.stage:not(.wire) .tag{display:none}
.w-anniu{border-color:#3aa655 !important}.w-wenben{border-color:#5a6472 !important}
.w-tubiao,.w-beijing,.w-lihui{border-style:dashed !important;border-color:#e08a3a !important;background:repeating-linear-gradient(45deg,#181c25,#181c25 8px,#1f2430 8px,#1f2430 16px)}
.w-shuzhitiao{border-color:#2bb3a3 !important}.w-zhuangshi{border-style:dashed !important;border-color:#3a4150 !important}.w-chrome{border-color:#7a8290 !important}
.slotnote{font-size:12px;color:#e0b070;pointer-events:none}
.stage.calib .el{cursor:move !important;outline:1px dashed #ffffff66}
.el .rs{position:absolute;right:0;bottom:0;width:12px;height:12px;background:#ff5fb0;cursor:nwse-resize;display:none}
.stage.calib .el .rs{display:block}
.bar{position:absolute;left:8px;right:8px;bottom:8px;height:8px;border-radius:4px;background:#2a2440}
.bar>i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:linear-gradient(90deg,#7a5ac0,#b47ae0)}
aside{position:fixed;right:14px;top:74px;width:270px;max-height:78vh;overflow:auto;background:#12151d;border:1px solid #2a3040;border-radius:8px;padding:12px;font-size:12px;z-index:1000}
aside h3{font-size:13px;margin-bottom:6px;color:#fff}aside .ev{padding:5px 0;border-bottom:1px dashed #2a3040}aside .ev b{color:#7ad0ff}
</style></head><body>
<header><b>{SCREEN}</b>
<button id="bWire" onclick="render('wire')">线稿</button>
<button id="bSkin" class="on" onclick="render('skin')">皮肤</button>
<button id="bAtmo" onclick="render('atmo')">氛围</button>
<button id="bLayout" onclick="render('layout')">布局</button>
<button id="bCalib" onclick="toggleCalib()">校准</button>
<button onclick="exportDSL()">导出 DSL</button>
<span style="margin-left:auto;color:#7a818c">校准模式可拖拽/缩放槽 → 导出 DSL · {PALETTE}</span></header>
<div class="viewport"><div class="stage skin" id="stage"></div></div>
<aside><h3>交互日志</h3><div id="log" style="color:#7a818c">点任意元素…</div></aside>
<script>
const C={x:{STAGEW},y:{STAGEH}};
const ELS={ELS};
const EVENTS={EVENTS};
const PALETTE={PALETTEJSON};
const CANVAS={CANVAS};const CANVASINK={CANVASINK};
const INSTANCES={INSTANCES};
const NAME={"anniu":"按钮","wenben":"文本","tubiao":"图标槽","beijing":"背景槽","lihui":"立绘槽","mianban":"面板","rongqi":"容器","shuzhitiao":"数值条","zhuangshi":"装饰","chrome":"chrome","unknown":"?"};
const accent=(PALETTE.match(/#[0-9a-fA-F]{6}/)||["#7a3ac0"])[0];
function skinByType(ab,state){
  let s;
  if(ab==="anniu") s="background:linear-gradient(#3a2e5a,#241c3e);color:#e8def5;border-radius:8px;font-size:15px";
  else if(ab==="mianban"||ab==="rongqi") s="background:rgba(30,24,55,.82);border:1px solid #6a5a8a;border-radius:12px";
  else if(ab==="wenben") s="color:#d8d0e8;justify-content:flex-start;padding-left:6px;font-size:14px";
  else if(ab==="shuzhitiao") s="background:#2a2440;border-radius:6px;color:#cfe0f0;font-size:13px";
  else if(ab==="tubiao") s="border:1.5px dashed #e08a3a;border-radius:8px;background:rgba(24,28,37,.8);color:#e0b070;font-size:13px";
  else if(ab==="beijing"||ab==="lihui") s="border-radius:6px;background:#160f1f";
  else if(ab==="zhuangshi") s="background:#3a4150;opacity:.5";
  else if(ab==="chrome") s="background:linear-gradient(#1a0f18,#140b14);color:#cfc4dc;font-size:14px;justify-content:space-between;padding:0 16px";
  else s="color:#d8d0e8";
  if(state) s+=";box-shadow:0 0 18px "+accent+"aa;outline:2px solid "+accent;
  return s;
}
function centerText(e){return e.text||((e.abbr==="rongqi"||e.abbr==="mianban")?"":e.label);}
const stage=document.getElementById("stage"),log=document.getElementById("log");
let curMode="skin",calib=false;
function scaleNow(){return Math.min(1,(window.innerWidth-330)/C.x);}
function toggleCalib(){calib=!calib;const b=document.getElementById("bCalib");if(b)b.classList.toggle("on",calib);render(curMode);}
function makeDraggable(d,e){
  d.onmousedown=(ev)=>{
    if(ev.target.className==="rs")return;
    ev.preventDefault();const sx=ev.clientX,sy=ev.clientY,ox=e.x,oy=e.y,s=scaleNow();
    function mv(m){e.x=Math.round((ox+(m.clientX-sx)/s/C.x*100)*10)/10;e.y=Math.round((oy+(m.clientY-sy)/s/C.y*100)*10)/10;d.style.left=e.x/100*C.x+"px";d.style.top=e.y/100*C.y+"px";}
    function up(){document.removeEventListener("mousemove",mv);document.removeEventListener("mouseup",up);}
    document.addEventListener("mousemove",mv);document.addEventListener("mouseup",up);
  };
  const rs=document.createElement("div");rs.className="rs";d.appendChild(rs);
  rs.onmousedown=(ev)=>{
    ev.preventDefault();ev.stopPropagation();const sx=ev.clientX,sy=ev.clientY,ow=e.w,oh=e.h,s=scaleNow();
    function mv(m){e.w=Math.max(1,Math.round((ow+(m.clientX-sx)/s/C.x*100)*10)/10);e.h=Math.max(1,Math.round((oh+(m.clientY-sy)/s/C.y*100)*10)/10);d.style.width=e.w/100*C.x+"px";d.style.height=e.h/100*C.y+"px";}
    function up(){document.removeEventListener("mousemove",mv);document.removeEventListener("mouseup",up);}
    document.addEventListener("mousemove",mv);document.addEventListener("mouseup",up);
  };
}
function exportDSL(){
  const lines=(curMode==="layout")
    ? INSTANCES.map(e=>e.label+" :"+e.id+" [实例·"+e.alias+"] @{"+e.x+" "+e.y+(e.native?"":(" "+e.w+" "+e.h))+"}"+(e.z?(" z="+e.z):""))
    : ELS.map(e=>{let s=" ".repeat(e.indent||0)+e.label;if(e.id)s+=" :"+e.id;s+=" ["+e.type+"]";s+=" @{"+e.x+" "+e.y+" "+e.w+" "+e.h+"}";if(e.z)s+=" z="+e.z;if(e.state)s+=" ["+e.state+"]";if(e.shape)s+=" 形="+e.shape;if(e.text)s+=' "'+e.text+'"';return s;});
  let ta=document.getElementById("dslout");
  if(!ta){ta=document.createElement("textarea");ta.id="dslout";ta.style.cssText="position:fixed;left:14px;bottom:14px;width:60vw;height:200px;z-index:2000;background:#0c0e13;color:#cfe0f0;border:1px solid #3a4a6a;font:12px monospace;padding:8px";document.body.appendChild(ta);}
  ta.value="## Layout\n\n```\n"+lines.join("\n")+"\n```\n";ta.style.display="block";ta.select();
}
function _z(e){return e.layer==null?0:e.layer;}
function renderLayout(){
  for(const e of INSTANCES){
    const d=document.createElement("div"); d.className="el";
    const b=e.box;
    d.style.cssText=`left:${b[0]/100*C.x}px;top:${b[1]/100*C.y}px;width:${b[2]/100*C.x}px;height:${b[3]/100*C.y}px;border:2px dashed #b47ae0;background:rgba(120,60,180,.12);color:#e8def5`;
    d.style.zIndex=e.z||7;
    const tg=document.createElement("span");tg.className="tag";tg.style.display="block";tg.textContent=e.label+" ["+e.alias+"]";d.appendChild(tg);
    const c=document.createElement("span");c.textContent="▣ 实例·"+e.alias+(e.native?"(原尺寸)":"(缩放)");c.style.fontSize="13px";d.appendChild(c);
    if(calib){ makeDraggable(d,e); if(e.native){ const rs=d.querySelector('.rs'); if(rs) rs.style.display='none'; } }
    stage.appendChild(d);
  }
}
function render(mode){
  curMode=mode;
  for(const id of ["Wire","Skin","Atmo","Layout"]){const b=document.getElementById("b"+id); if(b) b.classList.toggle("on",mode===id.toLowerCase());}
  stage.className="stage "+mode+(calib?" calib":""); stage.innerHTML="";
  stage.style.background=CANVAS||"";stage.style.color=CANVASINK||"";   // @canvas 主题:套品牌画布底色
  if(mode==="layout"){ renderLayout(); return; }
  for(const e of ELS){
    const d=document.createElement("div");
    d.className="el"+(mode==="wire"?" w-"+e.abbr:"");
    d.title=e.label+"·"+(NAME[e.abbr]||e.abbr)+(e.repeat>1?" ×"+e.repeat:"");
    d.style.cssText=`left:${e.x/100*C.x}px;top:${e.y/100*C.y}px;width:${e.w/100*C.x}px;height:${e.h/100*C.y}px`;
    d.style.zIndex=_z(e);
    const isArt=(e.abbr==="beijing"||e.abbr==="lihui");
    const isBar=(e.abbr==="shuzhitiao");
    if(isBar){
      if(mode!=="wire") d.style.cssText+=";"+skinByType(e.abbr,e.state);
      d.style.justifyContent="flex-start"; d.style.alignItems="flex-start"; d.style.padding=(mode==="wire"?"14px 6px 4px":"6px 8px");
      if(mode==="wire"){const t=document.createElement("span");t.className="tag";t.textContent=e.label+"·"+(NAME[e.abbr]||e.abbr);d.appendChild(t);}
      const mm=(e.text||"").match(/(\d+)\s*\/\s*(\d+)/);
      const ratio=mm?Math.max(0,Math.min(1,(+mm[1])/((+mm[2])||1))):0.6;
      const lab=document.createElement("span");lab.style.fontSize="13px";lab.textContent=e.text||e.label;d.appendChild(lab);
      const bar=document.createElement("div");bar.className="bar";const fill=document.createElement("i");fill.style.width=(ratio*100)+"%";bar.appendChild(fill);d.appendChild(bar);
    } else if(mode==="wire"){
      const t=document.createElement("span"); t.className="tag"; t.textContent=e.label+"·"+(NAME[e.abbr]||e.abbr); d.appendChild(t);
      const c=document.createElement("span");
      c.textContent=isArt?("▢ "+e.label+"槽·换素材"):centerText(e);
      if(isArt) c.className="slotnote";
      d.appendChild(c);
    } else {
      d.style.cssText+=";"+skinByType(e.abbr,e.state);
      if(isArt){
        if(mode==="atmo" && !e.img) d.style.background="radial-gradient(circle at 42% 48%,#040308 6%,#cfc6d2 11%,#3a2630 18%,#1a0e16 55%,#08060c)";
        if(!e.img){ const n=document.createElement("span"); n.className="slotnote"; n.textContent="▢ "+e.label+"槽·换素材"; d.appendChild(n); }
      } else d.textContent=centerText(e);
    }
    if(mode!=="wire"){ if(e.fill) d.style.background=e.fill; if(e.ink) d.style.color=e.ink; }
    if(mode!=="wire" && e.img){ d.style.background="url('"+e.img+"') center/cover no-repeat"; }
    if(e.shape==="圆"||e.shape==="圆形"||e.shape==="circle") d.style.borderRadius="50%";
    if(calib){ makeDraggable(d,e); }
    else d.onclick=()=>{
      const hit=EVENTS.filter(t=>t.includes(e.label)||(e.id&&t.includes(e.id)));
      const msg=hit.length?hit.join(" / "):"(无显式交互·展示元素)";
      const div=document.createElement("div"); div.className="ev";
      const b=document.createElement("b"); b.textContent=e.label; div.appendChild(b);
      div.appendChild(document.createTextNode(" "+msg));
      if(log.firstChild && log.firstChild.nodeType===1) log.insertBefore(div, log.firstChild);
      else { log.innerHTML=""; log.appendChild(div); }
    };
    stage.appendChild(d);
  }
}
function fit(){const s=Math.min(1,(window.innerWidth-330)/C.x);stage.style.transform="scale("+s+")";stage.parentElement.style.height=(C.y*s+36)+"px";}
addEventListener("resize",fit);render("skin");fit();
</script></body></html>'''


def _extract_instances(parsed, base_dir, modules_dir=None):
    """从未展开的 parsed 抽实例 + 算其屏上占位框(供 html「布局」档拖拽校准)。

    box = native 取模块原像素占比(x,y,fw,fh)、contain 取声明包围盒(x,y,w,h);native 仅拖不缩。
    """
    sw, sh = parsed["size"]
    imports = parsed.get("imports") or {}
    out = []
    for e in parsed["elements"]:
        if not e["type"].startswith(_INST):
            continue
        alias = e["type"].split("·", 1)[1]
        rel = imports.get(alias)
        mw, mh = 100, 100
        if rel:
            mp = os.path.normpath(os.path.join(base_dir, rel))
            if not os.path.exists(mp) and modules_dir:
                mp = os.path.normpath(os.path.join(modules_dir, rel))
            if os.path.exists(mp):
                with open(mp, encoding="utf-8") as f:
                    mw, mh = parse_dsl(f.read())["size"]
        native = e["w"] is None
        bw = e["w"] if e["w"] is not None else (mw / sw * 100.0 if sw else 0.0)
        bh = e["h"] if e["h"] is not None else (mh / sh * 100.0 if sh else 0.0)
        out.append({"id": e["id"], "label": e["name"], "alias": alias,
                    "x": e["x"], "y": e["y"], "w": e["w"], "h": e["h"],
                    "box": [e["x"], e["y"], bw, bh], "native": native, "z": e["z"]})
    return out


def render_html(parsed, skin=None, instances=None):
    import html as _h
    eff = _eff_skin(parsed, skin)
    cv = eff.get("@canvas") or {}
    W, H = parsed["size"]
    scr = _h.escape(parsed["screen"] or "")
    pal = _h.escape(parsed["palette"] or "")
    return (HTML_TEMPLATE
            .replace("{PALETTEJSON}", json.dumps(parsed["palette"] or "", ensure_ascii=False))
            .replace("{CANVAS}", json.dumps(cv.get("fill") or "", ensure_ascii=False))
            .replace("{CANVASINK}", json.dumps(cv.get("ink") or "", ensure_ascii=False))
            .replace("{INSTANCES}", json.dumps(instances or [], ensure_ascii=False))
            .replace("{STAGEW}", str(W)).replace("{STAGEH}", str(H))
            .replace("{SCREEN}", scr)
            .replace("{PALETTE}", pal)
            .replace("{ELS}", _els_json(parsed["elements"], eff, parsed.get("yuantu")))
            .replace("{EVENTS}", json.dumps(parsed["events"], ensure_ascii=False)))


SVG_STROKE = {"anniu": "#3aa655", "wenben": "#5a6472", "tubiao": "#e08a3a",
              "beijing": "#e08a3a", "lihui": "#e08a3a", "mianban": "#4a90d9",
              "rongqi": "#4a90d9", "shuzhitiao": "#2bb3a3", "zhuangshi": "#3a4150",
              "chrome": "#7a8290", "unknown": "#5a6472"}


def render_svg(parsed, skin=None):
    """单文件静态 svg 线框(对照 spike 3-md还原.svg)。

    全屏底图先画(底层);数值条画 track+fill;标签用中文类型;选中态品红描边;
    形=圆 才画圆;容器/面板无文本时不画居中标签;底部附图例。
    分层按 layer(z 优先,否则缩进)稳定排序——同层保文档顺序。
    """
    import html as _h
    W, H = parsed["size"]
    foot = H + 64
    art = ("beijing", "lihui")
    cont = ("rongqi", "mianban")
    eff = _eff_skin(parsed, skin)
    cv = eff.get("@canvas") or {}
    stagebg = cv.get("fill") or "#12151d"          # @canvas:套品牌画布;否则暗底
    deffill = cv.get("fill") or "#161a24"          # 无主题元素的默认填充
    defink = cv.get("ink") or "#cdd3dd"            # 默认文字色
    enr = _enrich(parsed["elements"], eff)
    ordered = sorted(enr, key=lambda el: el["layer"])
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
         'font-family="Microsoft YaHei,Segoe UI,sans-serif">' % (W, foot),
         '<rect width="%d" height="%d" fill="%s"/>' % (W, foot, stagebg),
         '<rect x="0" y="0" width="%d" height="%d" fill="%s" stroke="#2a3040"/>' % (W, H, stagebg)]
    for e in ordered:
        x, y, w, h = e["x"]/100*W, e["y"]/100*H, e["w"]/100*W, e["h"]/100*H
        sel = bool(e["state"])
        stroke = "#e848a0" if sel else SVG_STROKE.get(e["abbr"], "#5a6472")
        sw = ' stroke-width="2.5"' if sel else ''
        dash = ' stroke-dasharray="7 5"' if (e["abbr"] == "tubiao" or e["abbr"] in art or e["abbr"] == "zhuangshi") else ''
        rx = min(w, h) / 2 if e["shape"] in ("圆", "圆形", "circle") else 4
        did = _h.escape(e["id"] or "")
        rfill = e["fill"] or deffill
        g = ['<g data-id="%s"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" '
             'fill="%s" stroke="%s"%s%s/>' % (did, x, y, w, h, rx, rfill, stroke, sw, dash)]
        g.append('<text x="%.1f" y="%.1f" font-size="11" fill="#8893a2">%s</text>'
                 % (x + 6, y + 14, _h.escape("%s·%s" % (e["label"], e["type"]))))
        if e["abbr"] in art:
            g.append('<text x="%.1f" y="%.1f" font-size="12" fill="#e0b070" text-anchor="middle">%s</text>'
                     % (x + w / 2, y + h / 2 + 4, _h.escape("▢ %s槽·换素材" % e["label"])))
        elif e["abbr"] == "shuzhitiao":
            m = re.search(r"(\d+)\s*/\s*(\d+)", e["text"] or "")
            ratio = max(0.0, min(1.0, int(m.group(1)) / (int(m.group(2)) or 1))) if m else 0.6
            g.append('<text x="%.1f" y="%.1f" font-size="12" fill="#cdd3dd">%s</text>'
                     % (x + 6, y + 20, _h.escape(e["text"] or e["label"])))
            g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="8" rx="4" fill="#2a2440"/>'
                     % (x + 6, y + h - 14, max(1.0, w - 12)))
            g.append('<rect data-bar="1" x="%.1f" y="%.1f" width="%.1f" height="8" rx="4" fill="#2bb3a3"/>'
                     % (x + 6, y + h - 14, max(1.0, (w - 12) * ratio)))
        else:
            ctext = e["text"] or ("" if e["abbr"] in cont else e["label"])
            if ctext:
                g.append('<text x="%.1f" y="%.1f" font-size="12" fill="%s" text-anchor="middle">%s</text>'
                         % (x + w / 2, y + h / 2 + 4, e["ink"] or defink, _h.escape(ctext)))
        g.append('</g>')
        p.append("".join(g))
    p.append('<text x="12" y="%d" font-size="13" fill="#fff">%s · md→svg 还原(静态线框)</text>'
             % (H + 22, _h.escape(parsed["screen"])))
    leg = [("#4a90d9", "容器/面板"), ("#3aa655", "按钮"), ("#5a6472", "文本"),
           ("#e08a3a", "图标/背景槽·换素材"), ("#2bb3a3", "数值条"),
           ("#3a4150", "装饰"), ("#e848a0", "选中态")]
    lx = 12
    for col, name in leg:
        p.append('<rect x="%d" y="%d" width="14" height="14" rx="3" fill="%s" stroke="%s"/>'
                 '<text x="%d" y="%d" font-size="12" fill="%s">%s</text>'
                 % (lx, H + 42, deffill, col, lx + 20, H + 54, defink, _h.escape(name)))
        lx += len(name) * 15 + 44
    p.append('</svg>')
    return "\n".join(p)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    svg_out = None
    if "--svg" in argv:
        i = argv.index("--svg")
        svg_out = argv[i + 1]
        del argv[i:i + 2]
    skin = None
    if "--skin" in argv:
        i = argv.index("--skin")
        with open(argv[i + 1], encoding="utf-8") as f:
            skin = json.load(f)
        del argv[i:i + 2]
    modules_dir = None
    if "--modules" in argv:
        i = argv.index("--modules")
        modules_dir = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print("用法: python ui_render.py <dsl.md> [out.html] [--svg out.svg] [--skin theme.skin.json] [--modules dir]")
        return 2
    src = argv[0]
    out = argv[1] if len(argv) > 1 else (src.rsplit(".", 1)[0] + ".html")
    bd = os.path.dirname(os.path.abspath(src))
    with open(src, encoding="utf-8") as f:
        raw = parse_dsl(f.read())
    insts = _extract_instances(raw, bd, modules_dir)
    parsed = resolve(raw, bd, modules_dir)
    parsed = normalize_coords(parsed)
    miss = validate(parsed)
    if miss:
        print("⚠ 提醒:这些元素未标 z=(分层将按 缩进/文档顺序 兜底;捕获入库前宜补全):")
        for n in miss:
            print("   -", n)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(parsed, skin, instances=insts))
    print("html ->", out)
    if svg_out:
        with open(svg_out, "w", encoding="utf-8") as f:
            f.write(render_svg(parsed, skin))
        print("svg ->", svg_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
