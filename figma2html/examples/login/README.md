# login 示例(自足可跑 · 零网络 · 零 figma)

演示 figma2html 的完整链:**ui.json(像素)+ flow.json(声明交互)+ app hook(域内语义)→ 可点可跑**。
三份 `screen-*.ui.json` 由 `make_fixture.py` 合成(走与真 figma 同一条 `figma_capture.capture()` 管线),因此不需要 figma 文件、token 或网络。

## 跑起来(约 30 秒)

```bash
# 1. 在 skill 根目录(figma2html/)起静态服务
python -m http.server 8321
# 2. 浏览器开
#    http://localhost:8321/examples/login/app.html
# 3. (可选)无头截图核验
python scripts/shoot.py http://localhost:8321/examples/login/app.html out.png --w 540 --h 960
```

## 能点什么(全部来自 flow.json 声明)

| 操作 | 机制 |
|---|---|
| 点「公告」 | `openModal notice`;点弹窗任意处关闭(`@any:notice`) |
| 点服务器条/「切换」 | `openModal serverlist`;列表行由 app hook 用 MOCK 数据克隆模板行注入;点面板外关闭(`@panelOutside`) |
| 点列表行 | `list.onRowClick → selectServer`:维护中(灰宝石)拦截,否则回填底屏已选服条 |
| 点协议勾选框 | `toggleFlag agreed`(引擎通用 checkbox 绑定) |
| 点「开始游戏」 | `guard:[agreed,selected]` 不满足→提示;满足→`send enter`(mock 返回 token) |

## 文件

- `make_fixture.py` — 合成三屏节点树 → 调 capture 产 ui.json(改 capture 后重跑刷新)
- `flow.json` — 交互声明(契约见 `../../references/flow-events.md`)
- `app.js` — 域内 hook(数据→行/回填/状态色);协议名为**示例协议**
- `net.js` — mock 通信层(`window.NET`+`window.MOCK`);接真后端整体替换
- `app.html` — 组装页(引 `../../runtime/` 的 render.js + assemble.js)
