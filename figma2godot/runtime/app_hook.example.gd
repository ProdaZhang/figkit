# app_hook.example.gd — 域内 hook 接口示例(对齐 figma2html examples/login/app.js 的 APPHOOK)
# 引擎(flow_binder.gd)管结构与机制:底屏/弹窗/事件/守卫/勾选/列表克隆;
# app hook 管域内语义:数据→行、选服回填、状态色 —— 全部通过 action 字典注册,引擎不写死。
# 目标 Godot 4.2+;2026-07-03 于 Godot 4.3-stable 编译冒烟通过(依赖 flow_binder 的 class_name,
# 新工程先 `godot --headless --import` 一次再跑)。
#
# 挂法(比如在主场景脚本的 _ready 里):
#   var binder := FlowBinder.new()
#   binder.flow_path = "res://flow.json"
#   binder.scene_dir = "res://scenes/"
#   var hook := AppHook.new()
#   hook.register(binder)        # ① 先注册 action
#   add_child(binder)            # ② 后入树,binder._ready 组装并回调 onReady
#   hook.init(binder)            # ③ 后置初始化(拉数据、填列表)

extends RefCounted
class_name AppHook


func register(binder: FlowBinder) -> void:
	binder.register_actions({
		# send:守卫通过后的"提交"动作(flow 里 do:"send" 的落点)
		"send": func(arg, _ev): print("[app] send: ", arg),
		# 列表行点击(flow.list.onRowClick 指到这):行携带 set_meta("item") 的数据
		"selectServer": func(row: Control, _e): _select_server(binder, row),
		# 守卫失败提示(如未勾协议/未选服)
		"onGuardFail": func(ev): print("[app] 守卫未过: ", ev.get("guard")),
		# 组装完成回调
		"onReady": func(): print("[app] ready"),
		# 每次 state 变化后的域内回填(binder 已处理完通用 checkbox 才调这里)
		"syncBindings": func(base): _sync(binder, base),
	})


func init(binder: FlowBinder) -> void:
	# 域内数据 → 列表行(引擎克隆模板行,这里只管填内容)
	var servers := [
		{ "id": 1, "name": "一区·晨曦" },
		{ "id": 2, "name": "二区·薄暮" },
		{ "id": 3, "name": "三区·长夜" },
	]
	var row_fn := func(row: Control, item, _idx: int) -> void:
		var lbl := row.find_child(FlowBinder.node_name("3:23"), true, false) as Label
		if lbl != null:
			lbl.text = String(item["name"])
	binder.render_rows("serverlist", "3:20", servers, row_fn)
	# 默认选第一个
	binder.set_value("selected", servers[0])


func _select_server(binder: FlowBinder, row: Control) -> void:
	binder.set_value("selected", row.get_meta("item"))
	binder.close_modal()


func _sync(binder: FlowBinder, _base) -> void:
	# 已选服回填到底屏(figma id 按 flow/夹具:1:11 = server-name 文本)
	var sel = binder.state.get("selected")
	var lbl := binder.base_el("1:11") as Label
	if lbl != null and sel != null:
		lbl.text = String(sel["name"])
