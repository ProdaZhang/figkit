# cocos-typecheck — figma2cocos 运行时的严格类型门

```bash
cd tools/cocos-typecheck
npm ci
python3 check.py
```

两条都得绿:

```text
PASS runtime_typechecks_clean     # tsc --noEmit 零错
PASS gate_has_teeth               # 往真源码里种一个必然的类型错误,tsc 必须报 TS2322
```

## 为什么第二条不能省

README / SKILL.md / mapping.md 三处都写着 cocos 的 TS「已过严格类型门,**故意错用 API 会被抓**」。
只跑第一条证明不了后半句:tsconfig 写歪的时候(`files` 空了、d.ts 根本没加载、
`strict` 掉了)它**同样零错、同样绿**。所以 `check.py` 会把
`const x: string = new Node('teeth').position.x;` 种进 `flow-binder.ts`,
要求 tsc 报出 `TS2322` —— 这一条同时证明了三件事:cc 的声明真的加载了、
成员类型是真的、赋值检查开着。跑完源码原样还原。

## 门开在哪一档

`strict: true` + `experimentalDecorators`(`@ccclass` 要用)+ `noEmit`,
对官方 `@cocos/creator-types` **3.8.3**(engine d.ts,即 `import { ... } from 'cc'` 的真声明)。

**这比 Creator 自己严。** Creator 生成的 `tsconfig.cocos.json` 默认是 `strict: false`;
这里故意调到 strict,因为这份运行时没有在 Creator 里实机跑过(见 mapping.md 顶部的交付态声明),
类型是目前唯一能自动化的约束。

依赖版本**钉死不带 `^`**:同一个 commit 在任何机器上装到的是同一套声明,
否则"我这儿是绿的"就又变成一句不可复现的话。

`noImplicitOverride` 试过,**没要** —— 它不属于 `strict`,开了会要求给 `onLoad` 之类补
`override`。那是把门槛挪到文档声称之外,再回头改运行时去迁就它;门该守的是那句话说过的东西。

## 为什么它在 `tools/` 而不在 `figma2cocos/` 里

和 `tools/docs-assets/` 同一个理由:**七个 skill 必须能单独安装且零依赖**。
一道开发期的门不该让使用者装 node 工具链。`tools/run_all_tests.py`(纯标准库、离线)
因此也不跑它 —— 它由 CI 里单独一个 job 跑,见 `.github/workflows/tests.yml`。

配置本身仍然被离线守着:`tools/conformance` 会检查 `tsconfig.json` 的 `files`
覆盖了 `figma2cocos/runtime/` 下**每一个** `.ts`,以及 `package.json` 钉的版本
与文档里声称的那个版本号一致 —— 少写一个文件、或文档和配置各说各话,那才是这道门
最容易悄悄失效的方式。
