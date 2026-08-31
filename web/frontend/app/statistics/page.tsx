"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, StatCard, Signed } from "@/components/ui";

export default function StatisticsPage() {
  const { rev } = useLive();
  const load = useCallback(() => api.status(), []);
  const { data: st } = usePolling<any>(load, rev["stats"]);
  const s = st?.stats || {};
  const money = (n: number) => `${(n ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`;

  return (
    <div>
      <PageTitle title="Статистика" />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <StatCard label="Всего продаж" value={s.total_sales ?? 0} />
        <StatCard label="Общий профит" value={<Signed value={s.total_profit ?? 0} suffix=" ₽" />} accent />
        <StatCard label="Ср. профит" value={<Signed value={s.avg_profit_pct ?? 0} digits={1} suffix="%" />} />
        <StatCard label="Вложено" value={money(s.total_invested)} />
        <StatCard label="Выручка" value={money(s.total_revenue)} />
        <StatCard label="Стоимость ордеров" value={money(s.total_orders_value)} />
        <StatCard label="Активных ордеров" value={s.active_orders ?? 0} />
        <StatCard label="На холде" value={s.items_on_hold ?? 0} />
        <StatCard label="Готово к продаже" value={s.items_ready_to_sell ?? 0} />
      </div>
    </div>
  );
}
