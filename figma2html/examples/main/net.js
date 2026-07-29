// net.js(mock)— 离线假通信层:示例自足可跑,换成真 HTTP/SSE 层即可接后端。
// 契约:window.NET = { send(msg)->Promise<resp>, onPush(fn)? };消息 type 为**示例协议名**,
// 非任何真项目协议。
window.MOCK = {
  purse: { gem: 1280, coin: 42500 },
  claim: { coin: 1500, count: 8 },        // 领一次给多少 + 飞几个(不是 1500 个,见 catalog「飞向目标」)
  bag: [
    { slot: 0,  tint: '#e2b34a' }, { slot: 1,  tint: '#7fc7a6' }, { slot: 2,  tint: '#c98b8b' },
    { slot: 3,  tint: '#8aa9d6' }, { slot: 4,  tint: '#d8c98a' }, { slot: 5,  tint: '#9fd6c9' },
    { slot: 6,  tint: '#c7a6d6' }, { slot: 7,  tint: '#d69f9f' }
  ],
  codex: [
    { id: 1, name: 'Dawn Sprite',  tint: '#66d9e8' },
    { id: 2, name: 'Dusk Sprite',  tint: '#e8b166' },
    { id: 3, name: 'Tide Sprite',  tint: '#8bc12d' },
    { id: 4, name: 'Ember Sprite', tint: '#e86666' }
  ]
};
window.NET = {
  send: async function (msg) {
    console.log('[mock-net] send', msg);
    if (msg.type === 'claim') return { err: 0, coin: window.MOCK.claim.coin };
    return { err: 0 };
  },
  onPush: null
};
