"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Send, ArrowDown } from "lucide-react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle } from "@/components/ui";

export default function LogsPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.logs(500), []);
  const { data, reload } = usePolling<string[]>(load, rev["logs"], []);
  const [cmd, setCmd] = useState("");
  const [sending, setSending] = useState(false);
  const [stick, setStick] = useState(true); // прилипание к низу
  const boxRef = useRef<HTMLDivElement>(null);

  // Автопрокрутка вниз ТОЛЬКО если пользователь уже внизу (не мешаем читать историю)
  useEffect(() => {
    const el = boxRef.current;
    if (el && stick) el.scrollTop = el.scrollHeight;
  }, [data, stick]);

  const onScroll = () => {
    const el = boxRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    setStick(atBottom);
  };

  const toBottom = () => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setStick(true);
  };

  const send = async () => {
    const t = cmd.trim();
    if (!t) return;
    setSending(true);
    try { await api.command(t); setCmd(""); } catch {} finally { setSending(false); reload(); }
  };

  const color = (l: string) =>
    /\[ERROR\]|\bFAIL|упал|❌/i.test(l) ? "text-red-400"
    : /\[WARNING\]|⚠/i.test(l) ? "text-amber-400"
    : /\[SUCCESS\]|\bOK\b|SOLD|✅|\[CMD\]/i.test(l) ? "text-emerald-400"
    : "text-foreground/65";

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <PageTitle title="Логи" right={<span className="text-xs text-muted-foreground">команды: login · scan [N] · balances · guard &lt;код&gt;</span>} />
      <div className="relative flex-1 overflow-hidden">
        <div
          ref={boxRef}
          onScroll={onScroll}
          className="glass h-full overflow-auto p-4 font-mono text-xs leading-relaxed"
        >
          {(data || []).map((l, i) => <div key={i} className={color(l)}>{l}</div>)}
        </div>
        {!stick && (
          <button
            onClick={toBottom}
            className="uxera-btn-white absolute bottom-4 right-4 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium shadow-lg"
          >
            <ArrowDown size={13} /> к новым
          </button>
        )}
      </div>
      <div className="mt-3 flex gap-2">
        <input
          className="uxera-glass-field flex-1 rounded-md px-3 py-2 font-mono text-sm outline-none focus:ring-2 focus:ring-ring"
          placeholder="Введите команду или Steam Guard код…"
          value={cmd}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          onClick={send}
          disabled={sending}
          className="uxera-btn-white flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          <Send size={15} /> Отправить
        </button>
      </div>
    </div>
  );
}
