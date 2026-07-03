# flow_binder.gd — flow.json(figma2html IR 交互声明)→ Godot 运行时组装器
# 语义 1:1 对齐 figma2html/runtime/assemble.js:
#   底屏常驻 + 弹窗叠加(非换屏)、事件(click/守卫/toggleFlag/send)、
#   列表行克隆(duplicate 模板行 + 回调填充)、checkbox 双态、域内 action 注册。
# 目标 Godot 4.2+;2026-07-03 于 Godot 4.3-stable 编译冒烟通过(场景渲染已眼比对齐 figma2html;
# 交互链未实机点验)。注意:新工程先 `godot --headless --import` 一次,否则 class_name 未注册。
#
# 用法(见 app_hook.example.gd):
#   var binder := FlowBinder.new()
#   binder.flow_path = "res://flow.json"
#   binder.scene_dir = "res://scenes/"        # ui_to_tscn.py 产的 .tscn 所在目录
#   AppHook.new().register(binder)            # 先注册 action,后入树
#   add_child(binder)                         # _ready 触发组装
#
# 弹窗策略(二选一,这里选 A 并说明理由):
#   A. 整场景实例化 + 按 roots 剪枝:instantiate 该屏 .tscn,顶层子里只保留
#      roots 列的节点(其余 + StageBg 释放)。
#      理由:生成场景顶层子几何 = 相对帧的绝对 px,与 render.js subtreeOf
#      "抽出后坐标仍相对帧、叠加即对位"语义完全一致;且整场景实例保住
#      SubResource(StyleBox/渐变)引用,不必运行时重建样式。
#   B. (弃)整场景内按 roots 显隐:会把非弹窗元素(StageBg、别的面板)留在树里
#      吃鼠标事件,还得逐个改 mouse_filter,得不偿失。

extends Control
class_name FlowBinder

@export var flow_path: String = "res://flow.json"
@export var scene_dir: String = "res://"
@export var backdrop_color: Color = Color(0, 0, 0, 0.5)   # 对齐 assemble.js 半透明遮罩

var flow: Dictionary = {}
var state: Dictionary = {}
var actions: Dictionary = {}     # do 名 -> Callable(对齐 registerActions)
var layers: Dictionary = {}      # "base" / modal 名 -> Control
var modals: Dictionary = {}      # modal 名 -> { "el": Control, "panel": String }
var current: Variant = null      # 当前弹窗名(无 → null)

const _FORBIDDEN := [".", ":", "@", "/", "\"", "%"]


# ── 命名/查找(与 ui_to_tscn.py 的 node_name 同规则)──────────────────

static func node_name(id: String) -> String:
	var s := id
	for ch in _FORBIDDEN:
		s = s.replace(ch, "_")
	return s


func find_el(layer, id: String) -> Control:
	if layer == null:
		return null
	return (layer as Control).find_child(node_name(id), true, false) as Control


func base_el(id: String) -> Control:
	return find_el(layers.get("base"), id)


# ── action 注册(域内语义由 app hook 提供,引擎不写死)────────────────

func register_action(name: String, fn: Callable) -> FlowBinder:
	actions[name] = fn
	return self


func register_actions(map: Dictionary) -> FlowBinder:
	for k in map.keys():
		actions[k] = map[k]
	return self


# ── 构建 ─────────────────────────────────────────────────────────────

func _ready() -> void:
	var txt := FileAccess.get_file_as_string(flow_path)
	var parsed = JSON.parse_string(txt)
	if not (parsed is Dictionary):
		push_error("[flow_binder] flow.json 解析失败: " + flow_path)
		return
	flow = parsed
	state = (flow.get("state", {}) as Dictionary).duplicate()

	var stage: Dictionary = flow.get("stage", {})
	size = Vector2(float(stage.get("w", 1080)), float(stage.get("h", 1920)))

	# 底屏(常驻,含自身 StageBg)
	var base_inst := _instantiate_cap(String(flow.get("base", "base")))
	if base_inst != null:
		add_child(base_inst)
		layers["base"] = base_inst

	# 弹窗层(初始隐藏;树序在底屏之后 = 绘制在上)
	var ms: Dictionary = flow.get("modals", {})
	for mname in ms.keys():
		_build_modal(String(mname), ms[mname])

	_wire_events()
	sync_bindings()
	if actions.has("onReady"):
		actions["onReady"].call()


func _instantiate_cap(cap_name: String) -> Control:
	var caps: Dictionary = flow.get("caps", {})
	if not caps.has(cap_name):
		push_warning("[flow_binder] caps 里没有: " + cap_name)
		return null
	# caps 值是 .ui.json 路径 → 同名 .tscn(ui_to_tscn.py 的 <stem>.tscn)
	var stem := String(caps[cap_name]).get_file().replace(".ui.json", "").replace(".json", "")
	var scene_path := scene_dir.path_join(stem + ".tscn")
	var ps := load(scene_path) as PackedScene
	if ps == null:
		push_warning("[flow_binder] 场景未找到: " + scene_path)
		return null
	return ps.instantiate() as Control


func _build_modal(mname: String, m: Dictionary) -> void:
	var layer := Control.new()
	layer.name = "modal_" + node_name(mname)
	layer.visible = false
	layer.set_anchors_preset(Control.PRESET_FULL_RECT)
	layer.mouse_filter = Control.MOUSE_FILTER_STOP     # @any/@panelOutside 在层上接
	add_child(layer)

	var bd := ColorRect.new()                          # 半透明遮罩(对齐 assemble.js backdrop)
	bd.name = "Backdrop"
	bd.color = backdrop_color
	bd.set_anchors_preset(Control.PRESET_FULL_RECT)
	bd.mouse_filter = Control.MOUSE_FILTER_PASS        # 点击冒泡给层
	layer.add_child(bd)

	var inst := _instantiate_cap(String(m.get("cap", "")))
	if inst != null:
		var keep := {}
		for r in m.get("roots", []):
			keep[node_name(String(r))] = true
		for child in inst.get_children():              # 剪枝:只留 roots 子树(策略 A)
			if not keep.has(String(child.name)):
				child.queue_free()
		inst.mouse_filter = Control.MOUSE_FILTER_PASS
		_pass_through(inst)                            # 弹窗内事件冒泡到层(仿 DOM bubbling)
		layer.add_child(inst)

	layers[mname] = layer
	modals[mname] = { "el": layer, "panel": String(m.get("panel", "")) }


func _pass_through(node: Node) -> void:
	for child in node.get_children():
		if child is Control:
			(child as Control).mouse_filter = Control.MOUSE_FILTER_PASS
		_pass_through(child)


# ── 弹窗显隐(底屏常驻)────────────────────────────────────────────────

func open_modal(mname: String) -> void:
	for k in modals.keys():
		(modals[k]["el"] as Control).visible = false
	if modals.has(mname):
		(modals[mname]["el"] as Control).visible = true
	current = mname


func close_modal() -> void:
	for k in modals.keys():
		(modals[k]["el"] as Control).visible = false
	current = null


# ── 状态/守卫(truthy 判定对齐 assemble.js guardOk)──────────────────

func set_flag(name: String, val) -> void:
	state[name] = val
	sync_bindings()


func set_value(name: String, val) -> void:
	state[name] = val
	sync_bindings()


static func _truthy(v) -> bool:
	if v == null:
		return false
	if v is bool:
		return v
	if v is int or v is float:
		return v != 0
	if v is String:
		return v != ""
	return true


func guard_ok(guards) -> bool:
	for g in (guards if guards is Array else []):
		if not _truthy(state.get(g)):
			return false
	return true


# ── 事件接线 ──────────────────────────────────────────────────────────

static func _clicked(e) -> bool:
	return e is InputEventMouseButton \
		and e.button_index == MOUSE_BUTTON_LEFT and e.pressed


func _wire_events() -> void:
	for ev in flow.get("events", []):
		var sels = ev["el"] if ev["el"] is Array else [ev["el"]]
		for sel in sels:
			var s := String(sel)
			if s.begins_with("@"):                      # @any:<modal> / @panelOutside:<modal>
				var sp := s.substr(1).split(":")
				if sp.size() != 2 or not layers.has(sp[1]):
					push_warning("[flow_binder] 选择器无效: " + s)
					continue
				var layer := layers[sp[1]] as Control
				layer.gui_input.connect(_on_layer_input.bind(sp[0], sp[1], ev))
				continue
			var el := base_el(s)                        # 普通选择器 = 底屏 figma node id
			if el == null:
				push_warning("[flow_binder] 事件元素未找到: " + s)
				continue
			el.mouse_filter = Control.MOUSE_FILTER_STOP # Label 默认 IGNORE,要收点击须 STOP
			el.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
			el.gui_input.connect(_on_el_input.bind(el, ev))


func _on_el_input(e, el: Control, ev: Dictionary) -> void:
	if _clicked(e):
		el.accept_event()                               # 对齐 stopPropagation
		dispatch(ev, e)


func _on_layer_input(e, kind: String, mname: String, ev: Dictionary) -> void:
	if not _clicked(e):
		return
	if kind == "any":
		dispatch(ev, e)
		return
	if kind == "panelOutside":
		var panel := find_el(layers.get(mname), String(modals[mname]["panel"]))
		if panel == null or not panel.get_global_rect().has_point(e.global_position):
			dispatch(ev, e)


func dispatch(ev: Dictionary, e = null) -> void:
	if ev.has("guard") and not guard_ok(ev["guard"]):
		if actions.has("onGuardFail"):
			actions["onGuardFail"].call(ev)
		return
	var d := String(ev.get("do", ""))
	match d:
		"openModal":
			open_modal(String(ev.get("arg", "")))
		"closeModal":
			close_modal()
		"toggleFlag":
			var f := String(ev.get("arg", ""))
			set_flag(f, not _truthy(state.get(f)))
		"send":
			if actions.has("send"):
				actions["send"].call(ev.get("arg"), ev)
		_:
			if actions.has(d):                          # 其余 do 名 → app 注册的 action
				actions[d].call(ev, e)
			else:
				push_warning("[flow_binder] 未知 action: " + d)


# ── 通用绑定:checkbox 双态(白底+勾 / 半透+空);其余域内绑定走 app hook ──

func sync_bindings() -> void:
	var b: Dictionary = flow.get("bindings", {})
	if b.has("checkbox") and layers.has("base"):
		var c: Dictionary = b["checkbox"]
		var box := base_el(String(c.get("el", "")))
		if box != null:
			var on := _truthy(state.get(String(c.get("flag", ""))))
			var bg := _css_color(String(c.get("checkedBg" if on else "uncheckedBg", "")),
					Color(1, 1, 1, 1) if on else Color(1, 1, 1, 0.2))
			var sb := box.get_theme_stylebox("panel")   # ui_to_tscn 给 Panel 挂的 StyleBoxFlat
			if sb is StyleBoxFlat:
				(sb as StyleBoxFlat).bg_color = bg
			var mark := box.get_node_or_null("CheckMark") as Label
			if mark == null:
				mark = Label.new()
				mark.name = "CheckMark"
				mark.set_anchors_preset(Control.PRESET_FULL_RECT)
				mark.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
				mark.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
				mark.mouse_filter = Control.MOUSE_FILTER_IGNORE
				mark.add_theme_font_size_override("font_size", 24)
				box.add_child(mark)
			mark.add_theme_color_override("font_color",
					_css_color(String(c.get("markColor", "")), Color(0.106, 0.298, 0.341)))
			mark.text = String(c.get("mark", "✓")) if on else ""
	if actions.has("syncBindings"):
		actions["syncBindings"].call(layers.get("base"))


# ── 列表渲染助手(对齐 FigApp.renderRows:克隆首行模板 + 回调填充)──────

func render_rows(modal_name: String, container_id: String, items: Array, row_fn: Callable) -> void:
	var layer = layers.get(modal_name)
	if layer == null:
		return
	var list := find_el(layer, container_id)
	if list == null:
		push_warning("[flow_binder] 列表容器未找到: " + container_id)
		return
	list.clip_contents = true                           # overflow hidden;滚动条见 mapping.md known-loss
	var rows: Array = []
	for ch in list.get_children():
		if ch is Control:
			rows.append(ch)
	if rows.is_empty():
		push_warning("[flow_binder] 无模板行")
		return
	var tpl := (rows[0] as Control).duplicate() as Control
	var base_top: float = rows[0].offset_top
	var height: float = rows[0].offset_bottom - rows[0].offset_top
	var step: float = (rows[1].offset_top - base_top) if rows.size() > 1 \
			else (height if height > 0.0 else 104.0)
	for r in rows:
		(r as Node).free()
	var on_click := String((flow.get("list", {}) as Dictionary).get("onRowClick", ""))
	for idx in items.size():
		var row := tpl.duplicate() as Control
		row.offset_top = base_top + idx * step
		row.offset_bottom = row.offset_top + height
		row.set_meta("row", idx)
		row.set_meta("item", items[idx])
		row_fn.call(row, items[idx], idx)
		list.add_child(row)
		row.mouse_filter = Control.MOUSE_FILTER_STOP    # 整行收点击
		_ignore_children(row)                           # 行内子节点不抢事件
		if on_click != "":
			row.gui_input.connect(_on_row_input.bind(row, on_click))


func _on_row_input(e, row: Control, action_name: String) -> void:
	if _clicked(e) and actions.has(action_name):
		row.accept_event()
		actions[action_name].call(row, e)


func _ignore_children(node: Node) -> void:
	for child in node.get_children():
		if child is Control:
			(child as Control).mouse_filter = Control.MOUSE_FILTER_IGNORE
		_ignore_children(child)


# ── 工具:CSS rgba 字符串 → Color(flow.json 的颜色值沿用 CSS 写法)────

static func _css_color(s: String, fallback: Color) -> Color:
	var re := RegEx.create_from_string(
			"rgba?\\(\\s*([0-9.]+)\\s*,\\s*([0-9.]+)\\s*,\\s*([0-9.]+)\\s*(?:,\\s*([0-9.]+)\\s*)?\\)")
	var m := re.search(s)
	if m == null:
		return fallback
	var a := 1.0
	if m.get_string(4) != "":
		a = m.get_string(4).to_float()
	return Color(m.get_string(1).to_float() / 255.0,
			m.get_string(2).to_float() / 255.0,
			m.get_string(3).to_float() / 255.0, a)
