"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, DataTable, Signed } from "@/components/ui";

export default function SalesPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.sales(), []);
  const { data } = usePolling<any[]>(load, rev["stats"], []);
  return (
    <div>
      <PageTitle title="Продажи" />
      <DataTable
        rows={data || []}
        columns={[
          { key: "account_name", label: "Аккаунт" },
          { key: "item_name", label: "Предмет" },
          { key: "purchase_price", label: "Куплено", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "sale_price", label: "Продано", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "profit", label: "Профит", fmt: (_v, r) => <Signed value={(r.sale_price ?? 0) - (r.purchase_price ?? 0)} suffix=" ₽" /> },
          { key: "platform", label: "Площадка" },
          { key: "sold_at", label: "Дата" },
        ]}
      />
    </div>
  );
}
