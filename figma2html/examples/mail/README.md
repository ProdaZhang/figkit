# mail 示例 — 一份**真的** figma 稿(自足可跑 · 零网络 · 零 figma)

`login` 演的是**管线**(捕获 → IR → 各后端),界面刻意做到最小,而且它是
`make_fixture.py` **合成**的 —— 手工搭出来的节点树,只会长成作者想到的样子。

这一份不一样:它是从真实项目的 figma 文件里**捕获**下来的四屏邮件界面,
原样进仓。所以它演的是合成夹具够不着的那半边:

1. **真稿会怎么为难 IR。** 列表屏 129 个元素、组件实例 id 带分号
   (`I25:4109;206:12513;202:12604`)、矢量描边是骑在边线上的预裁带、
   道具底框靠 `isMask` 的兄弟节点裁圆角、面板底部是 `radius:50%` 的**椭圆**角。
   这些没有一条是合成夹具想得到的,而每一条都在某个后端上翻过车 —— 现在它们
   全都有实测账,记在各后端的 `references/mapping.md` 里。
2. **弹窗内的交互。** 三个弹窗(有附件 / 已领取 / 无附件),关闭按钮住在弹窗那一屏上,
   靠 v1.1 的 `@in:<modal>:<nodeId>` 绑;点面板外关闭走 `@panelOutside:<modal>`。
3. **引擎不做、只能由 app hook 做的那半边。** 「领取」是**原地换态**:同一个面板
   换成已领取那一版(水印 + 绿色删除按钮),配 flow 里声明的 `DISSOLVE`,
   读起来是一个面板在换内容,而不是"关一个再开一个"。figkit 不实现它 ——
   它不知道哪个弹窗是"同一封邮件的另一态"。这条写在 `app.js` 里。
4. **设计字体。** `fonts/FigCJK-{Regular,Bold}.woff2` 是设计稿字体(Source Han Sans SC)
   按这四屏真正用到的 116 个字做的子集,每份 19KB。四个后端共用同一份字形 ——
   否则每端各拿系统默认字体,连换行位置都不一样,逐像素比出来的差异大半是字形噪声。

## 跑起来(约 10 秒)

**直接双击 `app.html` 就行**,不用起服务器 —— `fixtures.js` 把 `flow.json` + 四屏
`.ui.json` 内联成 `window.__FIGKIT_FIXTURES`,绕开了浏览器在 `file://` 下对本地
XHR 的封锁(不内联就是白屏,且没有任何报错,踩过)。

点进去看:任意一封带附件的邮件 → 领取 → 面板原地换成已领取态;无附件的邮件
→ 只有删除;点面板外关闭。

想用服务器也行:

```bash
# 1. 在 skill 根目录(figma2html/)起静态服务
python3 -m http.server 8321
# 2. 浏览器开 http://localhost:8321/examples/mail/app.html
# 3. (可选)无头截图核验
python3 scripts/shoot.py http://localhost:8321/examples/mail/app.html out.png --w 540 --h 960
```

## 改了数据之后

`.ui.json` 是 `figma_capture.py` 的产物,`fixtures.js` 是它们加 `flow.json` 的内联包。
改了任何一份 json,**必须重跑**:

```bash
python3 bundle.py
```

漏跑的表现最阴:页面照样渲染,只是渲染的是旧内容。`scripts/tests/test_mail_example.py`
会在 CI 里逐字节比对,漏跑就红。

## 目录里都有什么

| 文件 | 是什么 |
|---|---|
| `screen-*.ui.json` | 四屏像素真源,`figma_capture.py` 从 figma 节点树捕获 |
| `flow.json` | 声明层:哪三个是弹窗、点什么开、点什么关、转场曲线 |
| `app.js` | 域内 hook:`claim` 动作 + 两处设计修正(见文件头的分类说明) |
| `app.html` | 装配页:引 `../../runtime/` 的 render.js + assemble.js |
| `bundle.py` | 生成 `fixtures.js`,让 `file://` 也能跑 |
| `assets/` | 5 张真图片填充(矢量不在这里 —— 它们以 SVG 路径的形式留在 IR 里) |
| `fonts/` | 设计字体子集,两个字重 |

`app.js` 开头把视觉修正分成了**两类**,别混成一坨"调样式":捕获缺陷绕行(figkit 修好就该删)
和设计修正(设计改了 figma 才能删)。前者现在是空的 —— 三条都已经修在捕获层了,
留着空函数是为了下一条有地方放,也是为了不让绕行掩盖捕获层到底修没修好。

## 素材权属

`assets/` 里的 PNG 与界面文案来自真实项目,随示例一并提供,只为让这份 demo
能被完整复现。要在别处复用请自行确认权属。
