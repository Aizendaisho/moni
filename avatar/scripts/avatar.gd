extends Node2D
## Avatar 2D del asistente (sprint S4).
## Se conecta al núcleo por WebSocket y muestra en qué estado está.
## Pendiente en S4: sprites del personaje, lip sync y expresiones.

const CORE_WS_URL := "ws://127.0.0.1:8765/ws"

var _ws := WebSocketPeer.new()
var _conectado := false

@onready var _estado: Label = $Estado


func _ready() -> void:
	_ws.connect_to_url(CORE_WS_URL)


func _process(_delta: float) -> void:
	_ws.poll()
	var state := _ws.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN:
		if not _conectado:
			_conectado = true
			_estado.text = "Listo"
		while _ws.get_available_packet_count() > 0:
			_on_mensaje(_ws.get_packet().get_string_from_utf8())
	elif state == WebSocketPeer.STATE_CLOSED and _conectado:
		_conectado = false
		_estado.text = "Sin conexión con el núcleo"


func _on_mensaje(texto: String) -> void:
	var msg = JSON.parse_string(texto)
	if typeof(msg) != TYPE_DICTIONARY:
		return
	match msg.get("type", ""):
		"token":
			_estado.text = "Hablando…"
		"done":
			_estado.text = "Listo"


func _draw() -> void:
	# Marcador provisional hasta tener el personaje: una cara simple.
	draw_circle(Vector2(200, 230), 120, Color("#1f6f7a"))
	draw_circle(Vector2(160, 200), 14, Color.WHITE)
	draw_circle(Vector2(240, 200), 14, Color.WHITE)
	draw_arc(Vector2(200, 260), 40, 0.2, PI - 0.2, 24, Color.WHITE, 6)
