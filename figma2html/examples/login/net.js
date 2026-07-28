// net.js(mock)— 离线假通信层:示例自足可跑,换成真 HTTP/SSE 层即可接后端。
// 契约:window.NET = { send(msg)->Promise<resp>, onPush(fn)? };消息 type 为**示例协议名**,非任何真项目协议。
window.MOCK = {
  servers: [
    { id: 1, name: 'S1 - Dawn',       status: 2 },
    { id: 2, name: 'S2 - Dusk',       status: 1 },
    { id: 3, name: 'S3 - Crossing',   status: 4 },
    { id: 4, name: 'S4 - Maintenance', status: 5 }
  ],
  notice: {
    title: 'Notice',
    body: 'This is the self-contained figma2html demo.\n\n· The three screen-*.ui.json files are synthesized by make_fixture.py, through the same capture pipeline used for real Figma frames\n· Every interaction here comes from flow.json (declaration) + app.js (app hook)\n· Swap this file (net.js mock) for a real transport to talk to a backend'
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
