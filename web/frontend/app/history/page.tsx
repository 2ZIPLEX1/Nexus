"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/useLive";
import { PageTitle, DataTable } from "@/components/ui";

export default function HistoryPage() {
  const load = useCallback(() => api.history(), []);
  const { data } = usePolling<any[]>(load, undefined, []);
  return (
    <div>
      <PageTitle title="История" />
      <DataTable
        rows={data || []}
        columns={[
          { key: "account_name", label: "Аккаунт" },
          { key: "item_name", label: "Предмет" },
          { key: "type", label: "Тип" },
          { key: "price", label: "Цена", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "date", label: "Дата" },
        ]}
      />
    </div>
  );
}
