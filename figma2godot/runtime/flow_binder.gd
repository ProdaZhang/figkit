# flow_binder.gd — flow.json(figma2html IR 交互声明)→ Godot 运行时组装器
# 语义 1:1 对齐 figma2html/runtime/assemble.js:
#   底屏常驻 + 弹窗叠加(非换屏)、事件(click/守卫/toggleFlag/send)、
#   列表行克隆(duplicate 模板行 + 回调填充)、checkbox 双态、域内 action 注册。
# 目标 Godot 4.2+;2026-07-03 于 Godot 4.3-stable 编译冒烟通过(场景渲染已眼比对齐 figma2html;
# 交互链未实机点验)。2026-07-29 实机核验 motion:6 条曲线读成 Curve,sample(0.3) 与 python
# 求解器 + Unity 侧三方一致到小数点后 6 位;转场真播(中途 alpha=0.509/offsetY=942.5 → 终态 1.0/0.0)。
# 注意:新工程先 `godot --headless --import` 一次,否则 class_name 未注册。
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
## ui_to_tscn.py 给了 flow.json 时烘出的 motion.json(转场缓动的采样曲线)。
## 文件不存在 = 全部瞬时显隐,是**声明在案的降级**(见 references/mapping.md),不是静默丢失。
@export var motion_path: String = "res://motion.json"

var flow: Dictionary = {}
var state: Dictionary = {}
var actions: Dictionary = {}     # do 名 -> Callable(对齐 registerActions)
var layers: Dictionary = {}      # "base" / modal 名 -> Control
var modals: Dictionary = {}      # modal 名 -> { "el": Control, "panel": String }
var current: Variant = null      # 当前弹窗名(无 → null)
var _last_pressed: Control = null # 最后被按下的元素(guard 拒绝时抖它)

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

	_load_motion()          # 必须在接线之前:按压要在 _wire_events 里挂上

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


# ── 动效(motion.json)────────────────────────────────────────────────
#
# **GDScript 这边一条曲线都不算。** figma 给的是具体曲线(cubic-bezier / 弹簧三参),
# 而 Godot 的 Tween.EASE_* 是**另一套同名不同形**的曲线 —— 各后端各挑"最像的枚举",
# 同一份 IR 在六个引擎里就是六种手感,而每家测试照样绿。所以曲线在 python 侧解成
# 17 个采样点,这里塞进 Curve 资源只做插值。与 figma2unreal / figma2unity 同一分工。

var curves: Dictionary = {}       # "ev3"/"press"/"stagger" -> { curve, dur, type, direction, from_scale }
var motion_cfg: Dictionary = {}   # flow.motion(press / stagger / guardFail)


func _load_motion() -> void:
	if not FileAccess.file_exists(motion_path):
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(motion_path))
	if not (parsed is Dictionary):
		push_warning("[flow_binder] motion.json 解析失败: " + motion_path)
		return
	for key in (parsed.get("curves", {}) as Dictionary).keys():
		var c: Dictionary = parsed["curves"][key]
		var pts: Array = c.get("points", [])
		if pts.size() < 2:
			continue                                   # unresolved 的曲线没有点
		var cu := Curve.new()
		for p in pts:
			var i := cu.add_point(Vector2(float(p[0]), float(p[1])))
			# 关键帧之间必须是**线性**插值。采样点一致只保证关键帧上一致,
			# 帧间插值模式不对齐,各引擎照样各算各的(Godot 默认切线是 0 = 每段两头压平)。
			cu.set_point_left_mode(i, Curve.TANGENT_LINEAR)
			cu.set_point_right_mode(i, Curve.TANGENT_LINEAR)
		var from_scale := 0.95
		if c.has("fromScale"):
			from_scale = float(c["fromScale"])
		elif c.has("toScale"):
			from_scale = float(c["toScale"])
		curves[key] = {
			"curve": cu,
			"dur": float(c.get("duration", 0)) / 1000.0,
			"type": String(c.get("type", "")),
			"direction": String(c.get("direction", "")),
			"from_scale": from_scale,
		}
	motion_cfg = flow.get("motion", {})


func _curve_for_event(ev: Dictionary) -> Variant:
	# motion.json 的 key 是 flow.events 的下标(ev<i>) —— 与 bake_flow 同一约定。
	var events: Array = flow.get("events", [])
	for i in events.size():
		if events[i] == ev:
			return curves.get("ev%d" % i)
	return null


## 按采样曲线驱动一段动画。进度 v:0=起点 1=终点;apply 决定往哪儿贴。
func _play(el: Control, c: Dictionary, reverse: bool, apply: Callable, done: Callable) -> void:
	if el == null or c.is_empty() or c["dur"] <= 0.0:
		apply.call(el, 0.0 if reverse else 1.0)
		if done.is_valid():
			done.call()
		return
	var cu: Curve = c["curve"]
	var tw := create_tween()
	apply.call(el, 1.0 if reverse else 0.0)
	tw.tween_method(
		func(x: float) -> void:
			var v := cu.sample(clampf(x, 0.0, 1.0))
			apply.call(el, 1.0 - v if reverse else v),
		0.0, 1.0, c["dur"])
	if done.is_valid():
		tw.finished.connect(func() -> void: done.call())


## 转场类型 → 怎么把进度贴到画面上(与 assemble.js transitionCss 同一张表)。
##
## ⚠️ **位移/缩放只贴面板本体,遮罩只跟着淡。** 早先把 transform 贴在弹窗**层**上,
## 而遮罩是层的子节点 —— 于是遮罩跟着面板一起滑/缩,顶部不变暗、四边缩进露出底屏。
## 数值层面完全看不出来(曲线取值一个不差),是实机截图才抓到的。
func _apply(mname: String, c: Dictionary, v: float) -> void:
	var layer := modals[mname]["el"] as Control
	layer.modulate.a = v                      # 遮罩 + 面板整体淡入淡出
	var panel := find_el(layer, String(modals[mname].get("panel", "")))
	if panel == null:
		return                                # 没声明 panel 就只淡,不猜该动谁
	var t := String(c.get("type", "DISSOLVE"))
	if t == "SCALE_IN" or t == "SCALE_OUT":
		var from_scale := float(c.get("from_scale", 0.95))
		var sc := lerpf(from_scale, 1.0, v)
		panel.pivot_offset = panel.size / 2.0
		panel.scale = Vector2(sc, sc)
	elif t in ["MOVE_IN", "SLIDE_IN", "MOVE_OUT", "SLIDE_OUT"]:
		var ux := 0.0
		var uy := 1.0
		match String(c.get("direction", "BOTTOM")):
			"LEFT": ux = -1.0; uy = 0.0
			"RIGHT": ux = 1.0; uy = 0.0
			"TOP": ux = 0.0; uy = -1.0
			_: ux = 0.0; uy = 1.0
		if not panel.has_meta("home"):
			panel.set_meta("home", panel.position)
		var home: Vector2 = panel.get_meta("home")
		panel.position = home + Vector2(ux * layer.size.x, uy * layer.size.y) * (1.0 - v)


func _reset_panel(mname: String) -> void:
	var layer := modals[mname]["el"] as Control
	layer.modulate.a = 1.0
	var panel := find_el(layer, String(modals[mname].get("panel", "")))
	if panel != null:
		panel.scale = Vector2.ONE
		if panel.has_meta("home"):
			panel.position = panel.get_meta("home")


# ── 弹窗显隐(底屏常驻)────────────────────────────────────────────────

func open_modal(mname: String, c: Variant = null) -> void:
	for k in modals.keys():
		(modals[k]["el"] as Control).visible = false
	current = mname
	if not modals.has(mname):
		return
	var el := modals[mname]["el"] as Control
	el.visible = true
	if c is Dictionary:
		_play(el, c, false, func(_x, v: float) -> void: _apply(mname, c, v), Callable())
	else:
		_reset_panel(mname)


## **有入场必有出场** —— 只做入场 = 消失时硬闪。没有转场声明就保持瞬时,不自作主张。
func close_modal(c: Variant = null) -> void:
	var cur = current
	current = null
	if not (c is Dictionary) or cur == null or not modals.has(cur):
		for k in modals.keys():
			(modals[k]["el"] as Control).visible = false
		return
	var el := modals[cur]["el"] as Control
	_play(el, c, true, func(_x, v: float) -> void: _apply(cur, c, v), func() -> void:
		if current == null:                          # 期间又开了别的弹窗就别抢着藏
			el.visible = false
			_reset_panel(cur))


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
			# @in:<modal>:<nodeId> —— 弹窗**内部**的元素(v1.1),真实 figma 文件里最常见的
			# 那条连线(弹窗里的 ✗)。节点 id 自带冒号("4:99"),所以 @in: 之后只有第一段是
			# 弹窗名,其余整段都是 id —— 下面那条按冒号 split 的通用分支会把它切成三段。
			if s.begins_with("@in:"):
				var rest := s.substr(4)
				var cut := rest.find(":")
				if cut < 0 or not layers.has(rest.substr(0, cut)):
					push_warning("[flow_binder] 选择器无效: " + s)
					continue
				var inner := find_el(layers[rest.substr(0, cut)], rest.substr(cut + 1))
				if inner == null:
					push_warning("[flow_binder] 弹窗内事件元素未找到: " + s)
					continue
				# _pass_through 把弹窗内全部子节点设成了 PASS(好让点击冒泡给层做
				# @any/@panelOutside);这一个要**收下**点击,所以改回 STOP。
				inner.mouse_filter = Control.MOUSE_FILTER_STOP
				inner.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
				_wire_press(inner)
				inner.gui_input.connect(_on_el_input.bind(inner, ev))
				continue
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
			_wire_press(el)
			el.gui_input.connect(_on_el_input.bind(el, ev))


## 可点元素没有按下态是**缺陷不是风格**:点下去毫无反应,玩家读到的是"卡了"。
func _wire_press(el: Control) -> void:
	if not motion_cfg.has("press"):
		return
	var target := float((motion_cfg["press"] as Dictionary).get("scale", 0.96))
	var c = curves.get("press")
	el.gui_input.connect(func(e) -> void:
		if not (e is InputEventMouseButton and e.button_index == MOUSE_BUTTON_LEFT):
			return
		_last_pressed = el
		el.pivot_offset = el.size / 2.0
		if e.pressed and c is Dictionary:
			_play(el, c, false, func(x: Control, v: float) -> void:
				var sc := lerpf(1.0, target, v)
				x.scale = Vector2(sc, sc), Callable())
		elif not e.pressed:
			el.scale = Vector2.ONE)


## 一个元素说「错了」。guard 拒绝时抖一下 —— 参数来自 flow.motion.guardFail。
func wiggle(el: Control) -> void:
	if el == null or not motion_cfg.has("guardFail"):
		return
	var g: Dictionary = motion_cfg["guardFail"]
	var amp := float(g.get("amp", 6))
	var dur := float(g.get("duration", 120)) / 1000.0
	var x0 := el.position.x
	var tw := create_tween()
	# 一去一回一归零。抖动是一次性、播完即弃的,直接按相位算,不复用转场曲线。
	tw.tween_method(func(t: float) -> void:
		el.position.x = x0 + sin(t * TAU) * amp * (1.0 - t), 0.0, 1.0, dur)
	tw.finished.connect(func() -> void: el.position.x = x0)


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
		# 以前这里对玩家是**彻底的沉默**:协议没勾就点"开始",界面毫无反应。
		wiggle(_last_pressed)
		if actions.has("onGuardFail"):
			actions["onGuardFail"].call(ev)
		return
	var d := String(ev.get("do", ""))
	match d:
		"openModal":
			open_modal(String(ev.get("arg", "")), _curve_for_event(ev))
		"closeModal":
			close_modal(_curve_for_event(ev))
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
		_stagger_in(row, idx)


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


## 逐项入场:全部同时出现 = 一整块东西闪进来,量感全无;错开一点才读得出"有几条"。
func _stagger_in(row: Control, index: int) -> void:
	if not motion_cfg.has("stagger") or not curves.has("stagger"):
		return
	var cfg: Dictionary = motion_cfg["stagger"]
	var step := float(cfg.get("step", 45)) / 1000.0
	var from := float(cfg.get("from", 24))
	var y0 := row.position.y
	row.modulate.a = 0.0
	var tw := create_tween()
	tw.tween_interval(index * step)
	var c: Dictionary = curves["stagger"]
	var cu: Curve = c["curve"]
	tw.tween_method(func(x: float) -> void:
		var v := cu.sample(clampf(x, 0.0, 1.0))
		row.modulate.a = v
		row.position.y = y0 + from * (1.0 - v), 0.0, 1.0, c["dur"])
