"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, DataTable } from "@/components/ui";

export default function OrdersPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.orders(), []);
  const { data } = usePolling<any[]>(load, rev["active_orders"], []);
  return (
    <div>
      <PageTitle title="Активные ордера" right={<span className="text-sm text-muted-foreground">{data?.length ?? 0} шт.</span>} />
      <DataTable
        rows={data || []}
        columns={[
          { key: "account_name", label: "Аккаунт" },
          { key: "item_name", label: "Предмет" },
          { key: "order_price", label: "Цена", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "quantity", label: "Кол-во" },
          { key: "status", label: "Статус" },
          { key: "created_at", label: "Создан" },
        ]}
      />
    </div>
  );
}
