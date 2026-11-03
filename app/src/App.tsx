import { useEffect, useRef, useState } from "react";
import { connectCore, type CoreMessage } from "./lib/core";

type Msg = { role: "user" | "assistant"; text: string };

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tool, setTool] = useState<string | null>(null); // herramienta en uso
  const core = useRef<ReturnType<typeof connectCore> | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onMessage = (msg: CoreMessage) => {
      switch (msg.type) {
        case "history":
          setMessages(msg.messages);
          setBusy(false);
          setTool(null);
          break;
        case "token":
          setTool(null);
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, text: last.text + msg.text }];
            }
            return [...prev, { role: "assistant", text: msg.text }];
          });
          break;
        case "tool":
          setTool(msg.status === "start" ? msg.label : null);
          break;
        case "done":
          setBusy(false);
          setTool(null);
          break;
        case "error":
          setBusy(false);
          setTool(null);
          setMessages((prev) => [...prev, { role: "assistant", text: `⚠️ ${msg.message}` }]);
          break;
      }
    };
    core.current = connectCore(onMessage, (ok) => {
      setOnline(ok);
      if (!ok) setBusy(false);
    });
    return () => core.current?.close();
  }, []);

  // Llaves obligatorias: en Chromium/WebView2 recientes scrollIntoView devuelve una Promise,
  // y si el efecto la devuelve React la trata como función de limpieza y la app entera se cae.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, tool]);

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !online || busy) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setBusy(true);
    core.current?.send({ type: "chat", text });
  };

  const newConversation = () => {
    if (!online || busy) return;
    core.current?.send({ type: "new_conversation" });
  };

  const waiting = busy && messages[messages.length - 1]?.role === "user";

  return (
    <main className="flex h-full flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <h1 className="text-lg font-semibold">Moni</h1>
        <div className="flex items-center gap-3">
          <span className={`text-xs ${online ? "text-emerald-400" : "text-amber-400"}`}>
            {online ? "● Núcleo conectado" : "● Esperando al núcleo…"}
          </span>
          <button
            onClick={newConversation}
            disabled={!online || busy || messages.length === 0}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
          >
            Nueva conversación
          </button>
        </div>
      </header>

      <section className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            Escribe algo para empezar. Prueba: "¿qué programas están usando más memoria?" o "¿cómo
            está la batería?".
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[80%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${
              m.role === "user" ? "ml-auto bg-cyan-700" : "bg-slate-800"
            }`}
          >
            {m.text}
          </div>
        ))}
        {(tool || waiting) && (
          <div className="w-fit animate-pulse rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-400">
            {tool ? `🔧 ${tool}…` : "Moni está pensando…"}
          </div>
        )}
        <div ref={bottom} />
      </section>

      <form onSubmit={send} className="flex gap-2 border-t border-slate-800 p-3">
        <input
          className="flex-1 rounded-lg bg-slate-900 px-3 py-2 text-sm outline-none ring-cyan-600 focus:ring-2"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Pídele algo a Moni…"
        />
        <button
          type="submit"
          disabled={!online || busy}
          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold disabled:opacity-40"
        >
          Enviar
        </button>
      </form>
    </main>
  );
}
