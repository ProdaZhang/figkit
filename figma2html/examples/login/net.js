// net.js(mock)— 离线假通信层:示例自足可跑,换成真 HTTP/SSE 层即可接后端。
// 契约:window.NET = { send(msg)->Promise<resp>, onPush(fn)? };消息 type 为**示例协议名**,非任何真项目协议。
window.MOCK = {
  servers: [
    { id: 1, name: '一区·晨曦', status: 2 },
    { id: 2, name: '二区·薄暮', status: 1 },
    { id: 3, name: '三区·争渡', status: 4 },
    { id: 4, name: '四区·维护中', status: 5 }
  ],
  notice: {
    title: '公告',
    body: '这是 figma2html 的自足示例。\n\n· 三份 screen-*.ui.json 由 make_fixture.py 合成(与真 figma 同一条捕获管线)\n· 交互全部来自 flow.json 声明 + app.js hook\n· 把本文件(net.js mock)换成真通信层即可接后端'
  }
};
window.NET = {
  send: async function (msg) {
    console.log('[mock-net] send', msg);
    if (msg.type === 'selectServer') return { err: 0 };
    if (msg.type === 'enter') return { err: 0, sessionToken: 'demo-token' };
    return { err: 0 };
  },
  onPush: null
};
