// Conexión con el núcleo Python (core/) por WebSocket.
// El núcleo escucha en ws://127.0.0.1:8765/ws (ver core/src/asistente_core/main.py).

export const CORE_WS_URL = "ws://127.0.0.1:8765/ws";

/** Mensajes que la app envía al núcleo. */
export type ClientMessage =
  | { type: "chat"; text: string }
  | { type: "new_conversation" }
  | { type: "confirm_reply"; id: string; ok: boolean };

/** Mensajes que el núcleo envía a la app. */
export type CoreMessage =
  | { type: "history"; conversation_id: number; messages: { role: "user" | "assistant"; text: string }[] }
  | { type: "token"; text: string } // fragmento de la respuesta en streaming
  | { type: "tool"; name: string; label: string; status: "start" | "end"; ok?: boolean }
  | { type: "confirm"; id: string; question: string } // pedir Sí/No antes de una acción
  | { type: "confirm_closed"; id: string } // la pregunta caducó
  | { type: "done" } // terminó la respuesta
  | { type: "error"; message: string };

export function connectCore(onMessage: (msg: CoreMessage) => void, onStatus: (online: boolean) => void) {
  let ws: WebSocket | null = null;
  let retry: number | undefined;

  const open = () => {
    ws = new WebSocket(CORE_WS_URL);
    ws.onopen = () => onStatus(true);
    ws.onclose = () => {
      onStatus(false);
      retry = window.setTimeout(open, 2000); // reintenta mientras el núcleo arranca
    };
    ws.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data) as CoreMessage);
      } catch {
        /* mensaje inválido: se ignora */
      }
    };
  };
  open();

  return {
    send(msg: ClientMessage) {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    },
    close() {
      window.clearTimeout(retry);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    },
  };
}
