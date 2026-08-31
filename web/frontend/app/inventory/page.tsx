"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, DataTable } from "@/components/ui";

export default function InventoryPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.inventory(), []);
  const { data } = usePolling<any[]>(load, rev["accounts"], []);
  return (
    <div>
      <PageTitle title="Инвентарь / холд" right={<span className="text-sm text-muted-foreground">{data?.length ?? 0} шт.</span>} />
      <DataTable
        rows={data || []}
        columns={[
          { key: "account_name", label: "Аккаунт" },
          { key: "market_hash_name", label: "Предмет" },
          { key: "purchase_price", label: "Куплено", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "expected_sell_price", label: "Ожид. продажа", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "status", label: "Статус" },
          { key: "unlock_date", label: "Разблок." },
        ]}
      />
    </div>
  );
}
