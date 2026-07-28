# login 示例(自足可跑 · 零网络 · 零 figma)

演示 figma2html 的完整链:**ui.json(像素)+ flow.json(声明交互)+ app hook(域内语义)→ 可点可跑**。
三份 `screen-*.ui.json` 由 `make_fixture.py` 合成(走与真 figma 同一条 `figma_capture.capture()` 管线),因此不需要 figma 文件、token 或网络。

## 跑起来(约 10 秒)

**直接双击 `app.html` 就行**,不用起服务器 —— `fixtures.js` 把 `flow.json` + 三份 `.ui.json`
内联成 `window.__FIGKIT_FIXTURES`,绕开了浏览器在 `file://` 下对本地 XHR 的封锁
(不内联就是白屏,且没有任何报错,踩过)。

想用服务器也行:

```bash
# 1. 在 skill 根目录(figma2html/)起静态服务
python3 -m http.server 8321
# 2. 浏览器开 http://localhost:8321/examples/login/app.html
# 3. (可选)无头截图核验
python3 scripts/shoot.py http://localhost:8321/examples/login/app.html out.png --w 540 --h 960
```

## 两套文案(改 fixture 前先看这条)

同一套几何、两种文案,都由 `make_fixture.py` 产,**别手改 .ui.json**:

```bash
python3 make_fixture.py                 # en → 本目录(门面 demo)+ 刷新 fixtures.js
python3 make_fixture.py --lang zh --out <backend>/scripts/tests/fixtures   # zh → 各后端测试夹具
```

各后端 `scripts/tests/fixtures/` 里是**故意保留的中文版**:让 CJK 编码/字形/换行一直在
golden 逐字节比对的覆盖里。改了几何要两边都重跑,并重生成各后端 golden。

## 能点什么(全部来自 flow.json 声明)

| 操作 | 机制 |
|---|---|
| 点「Notice」 | `openModal notice`;点弹窗任意处关闭(`@any:notice`) |
| 点服务器条/「Switch」 | `openModal serverlist`;列表行由 app hook 用 MOCK 数据克隆模板行注入;点面板外关闭(`@panelOutside`) |
| 点列表行 | `list.onRowClick → selectServer`:维护中(灰宝石)拦截,否则回填底屏已选服条 |
| 点协议勾选框 | `toggleFlag agreed`(引擎通用 checkbox 绑定) |
| 点「START」 | `guard:[agreed,selected]` 不满足→提示;满足→`send enter`(mock 返回 token) |

## 文件

- `make_fixture.py` — 合成三屏节点树 → 调 capture 产 ui.json + fixtures.js(改 capture 后重跑刷新)
- `fixtures.js` — **生成物,别手改**:内联夹具,让 `file://` 双击可跑
- `flow.json` — 交互声明(契约见 `../../references/flow-events.md`)
- `app.js` — 域内 hook(数据→行/回填/状态色);协议名为**示例协议**
- `net.js` — mock 通信层(`window.NET`+`window.MOCK`);接真后端整体替换
- `app.html` — 组装页(引 `../../runtime/` 的 render.js + assemble.js)
