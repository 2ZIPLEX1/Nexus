"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getToken, wsUrl } from "./api";

/**
 * Подписка на WebSocket live-state. Возвращает счётчик ревизии по ключу
 * (logs/stats/accounts/active_orders/bot_state/scanner_state) + признак connected.
 * Экран сам решает, что перезапросить по REST при изменении нужного ключа.
 */
export function useLive() {
  const [connected, setConnected] = useState(false);
  const [rev, setRev] = useState<Record<string, number>>({});
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: any;

    // Тикет одноразовый и живёт 30 с, поэтому запрашиваем новый на КАЖДОЕ
    // подключение — в том числе при переподключении после обрыва.
    async function connect() {
      if (closed) return;
      // Без сессии тикет не выдадут — не долбим сервер на экране логина.
      if (!getToken()) {
        retry = setTimeout(connect, 3000);
        return;
      }
      try {
        const url = await wsUrl();
        if (closed) return;
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => setConnected(true);
        ws.onclose = () => {
          setConnected(false);
          if (!closed) retry = setTimeout(connect, 3000);
        };
        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            const key = msg.type;
            setRev((r) => ({ ...r, [key]: (r[key] || 0) + 1 }));
          } catch {}
        };
      } catch {
        if (!closed) retry = setTimeout(connect, 3000);
      }
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  return { connected, rev };
}

/** Хелпер: загрузка данных с авто-перезапросом при изменении ключа в live-state. */
export function usePolling<T>(loader: () => Promise<T>, revKey?: number, initial?: T) {
  const [data, setData] = useState<T | undefined>(initial);
  const [error, setError] = useState<string>("");
  const load = useCallback(() => {
    loader()
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(String(e?.message || e)));
  }, [loader]);
  useEffect(() => { load(); }, [load, revKey]);
  return { data, error, reload: load };
}
