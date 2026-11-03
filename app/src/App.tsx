import { useEffect, useRef, useState } from "react";
import { connectCore, type CoreMessage } from "./lib/core";

type Msg = { role: "user" | "assistant"; text: string };

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const core = useRef<ReturnType<typeof connectCore> | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onMessage = (msg: CoreMessage) => {
      if (msg.type === "token") {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant") {
            return [...prev.slice(0, -1), { ...last, text: last.text + msg.text }];
          }
          return [...prev, { role: "assistant", text: msg.text }];
        });
      } else if (msg.type === "done") {
        setBusy(false);
      } else if (msg.type === "error") {
        setBusy(false);
        setMessages((prev) => [...prev, { role: "assistant", text: `⚠️ ${msg.message}` }]);
      }
    };
    core.current = connectCore(onMessage, setOnline);
    return () => core.current?.close();
  }, []);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !online || busy) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setBusy(true);
    core.current?.send({ type: "chat", text });
  };

  return (
    <main className="flex h-full flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h1 className="text-lg font-semibold">Asistente</h1>
        <span className={`text-xs ${online ? "text-emerald-400" : "text-amber-400"}`}>
          {online ? "● Núcleo conectado" : "● Esperando al núcleo…"}
        </span>
      </header>

      <section className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            Escribe algo para empezar. Si dice "Esperando al núcleo", ejecuta <code>scripts\dev.bat</code>.
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
        <div ref={bottom} />
      </section>

      <form onSubmit={send} className="flex gap-2 border-t border-slate-800 p-3">
        <input
          className="flex-1 rounded-lg bg-slate-900 px-3 py-2 text-sm outline-none ring-cyan-600 focus:ring-2"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Pídele algo al asistente…"
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
