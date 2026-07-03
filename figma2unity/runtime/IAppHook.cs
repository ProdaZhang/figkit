// IAppHook.cs — figma2unity 域内语义钩子接口
// 目标 Unity 2022.3+ / UI Toolkit。2026-07-03 于 Unity 6000.4.8f1 batchmode 编译冒烟通过(零错零警告)。
//
// 分工与 figma2html 的 assemble.js / app.js 完全对齐:
//   引擎(FlowBinder)管结构与机制 —— 底屏/弹窗/事件/守卫/勾选/列表克隆;
//   app(IAppHook 实现)管域内语义 —— 数据→行、选中回填、状态色、send 落地。
//
// 用法:写一个 MonoBehaviour 实现本接口,拖到 FlowBinder.appHookBehaviour 槽
// (或与 FlowBinder 挂同一 GameObject,FlowBinder 会自动 GetComponent 查找)。

namespace Figma2Unity
{
    public interface IAppHook
    {
        /// <summary>
        /// 注册域内 action(对应 app.js 的 APPHOOK.register / registerActions)。
        /// 在事件接线之前调用 —— flow.events 里非内置的 do 名(如 "send"、"selectServer")
        /// 都在这里通过 binder.RegisterAction(name, fn) 落地。
        /// </summary>
        void RegisterActions(FlowBinder binder);

        /// <summary>
        /// 后置初始化(对应 app.js 的 APPHOOK.init / onReady):UI 树已建好、事件已接线。
        /// 典型动作:拉数据 → binder.RenderRows(...)、默认选中、填公告文本。
        /// </summary>
        void Init(FlowBinder binder);
    }
}
