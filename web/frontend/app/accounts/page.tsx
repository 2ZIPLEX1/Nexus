"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, DataTable, Badge } from "@/components/ui";

export default function AccountsPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.accounts(), []);
  const { data } = usePolling<any[]>(load, rev["accounts"], []);
  const money = (n: number, c = "") => `${(n ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ${c}`.trim();

  return (
    <div>
      <PageTitle title="Аккаунты" />
      <DataTable
        rows={data || []}
        columns={[
          { key: "name", label: "Аккаунт" },
          { key: "currency", label: "Валюта" },
          { key: "logged_in", label: "Статус", fmt: (v) => <Badge ok={v}>{v ? "онлайн" : "оффлайн"}</Badge> },
          { key: "steam_balance", label: "Steam", fmt: (v, r) => money(v, r.currency) },
          { key: "csgotm_balance", label: "CSGO.TM", fmt: (v) => money(v, "₽") },
          { key: "csgotm_settlement", label: "В холде (TM)", fmt: (v) => money(v, "₽") },
          { key: "enabled", label: "Вкл.", fmt: (v) => (v ? "да" : "нет") },
        ]}
      />
    </div>
  );
}
