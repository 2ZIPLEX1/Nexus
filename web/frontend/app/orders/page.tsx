"use client";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, DataTable } from "@/components/ui";

export default function OrdersPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.orders(), []);
  const { data } = usePolling<any[]>(load, rev["active_orders"], []);

  // Какие ордера сейчас отменяются — чтобы не жать кнопку дважды.
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  // Отменённые в этой сессии: список обновляется по опросу не сразу,
  // и без пометки строка выглядела бы так, будто ничего не произошло.
  const [cancelled, setCancelled] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string>("");

  async function cancel(orderId: string, itemName: string) {
    if (!orderId || busy[orderId]) return;
    if (!confirm(`Снять ордер на «${itemName}»?`)) return;

    setError("");
    setBusy((s) => ({ ...s, [orderId]: true }));
    try {
      await api.cancelOrder(orderId);
      setCancelled((s) => ({ ...s, [orderId]: true }));
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setBusy((s) => ({ ...s, [orderId]: false }));
    }
  }

  const rows = data || [];

  return (
    <div>
      <PageTitle
        title="Активные ордера"
        right={<span className="text-sm text-muted-foreground">{rows.length} шт.</span>}
      />

      {error && (
        <div className="glass mb-3 border-l-2 border-red-500 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <DataTable
        rows={rows}
        columns={[
          { key: "account_name", label: "Аккаунт" },
          { key: "item_name", label: "Предмет" },
          { key: "order_price", label: "Цена", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "quantity", label: "Кол-во" },
          { key: "status", label: "Статус" },
          { key: "created_at", label: "Создан" },
          {
            key: "order_id",
            label: "",
            fmt: (orderId: string, row: any) => {
              if (cancelled[orderId]) {
                return <span className="text-xs text-muted-foreground">снят</span>;
              }
              return (
                <button
                  onClick={() => cancel(orderId, row.item_name || "предмет")}
                  disabled={busy[orderId]}
                  className="rounded-md border border-red-500/40 px-3 py-1 text-xs text-red-400
                             transition hover:bg-red-500/10 disabled:opacity-40"
                >
                  {busy[orderId] ? "Снимаю…" : "Отменить"}
                </button>
              );
            },
          },
        ]}
      />
    </div>
  );
}
