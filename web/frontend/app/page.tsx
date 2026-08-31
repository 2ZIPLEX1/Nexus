"use client";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { Card, PageTitle, StatCard, Button, Badge, Signed } from "@/components/ui";

export default function Dashboard() {
  const { rev } = useLive();
  const loadStatus = useCallback(() => api.status(), []);
  const { data: st, reload } = usePolling<any>(loadStatus, (rev["stats"] || 0) + (rev["bot_state"] || 0) + (rev["scanner_state"] || 0));

  const stats = st?.stats || {};
  const money = (n: number) => (n ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 });

  const ctl = async (fn: () => Promise<any>) => { await fn(); reload(); };

  return (
    <div>
      <PageTitle
        title="Дашборд"
        right={<Badge ok={st?.ready}>{st?.ready ? `${st?.accounts_logged_in}/${st?.accounts_total} онлайн` : "загрузка…"}</Badge>}
      />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Активных ордеров" value={stats.active_orders ?? "—"} accent />
        <StatCard label="На холде" value={stats.items_on_hold ?? "—"} />
        <StatCard label="Готово к продаже" value={stats.items_ready_to_sell ?? "—"} />
        <StatCard label="Общий профит" value={<Signed value={stats.total_profit ?? 0} suffix=" ₽" />} sub={`продаж: ${stats.total_sales ?? 0}`} />
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <SubsystemCard
          title="Buy-цикл" running={st?.buy_running}
          sub={`каждые ${st?.cycle_min ?? "—"} мин`}
          onStart={() => ctl(api.botStart)} onStop={() => ctl(api.botStop)}
        />
        <SubsystemCard
          title="Продажи (CSGO.TM)" running={st?.sales_running}
          sub="ping + листинг + подтверждения"
          onStart={() => ctl(api.salesStart)} onStop={() => ctl(api.salesStop)}
        />
        <SubsystemCard
          title="Сканер" running={st?.scanner_running}
          sub={`каждые ${st?.scan_min ?? "—"} мин`}
          onStart={() => ctl(api.scannerStart)} onStop={() => ctl(api.scannerStop)}
        />
      </div>

      <Card>
        <div className="text-sm text-muted-foreground">Финансы</div>
        <div className="mt-2 grid grid-cols-2 gap-4 md:grid-cols-4">
          <div><div className="text-xs text-muted-foreground">Вложено</div><div className="text-lg tabular-nums">{money(stats.total_invested)} ₽</div></div>
          <div><div className="text-xs text-muted-foreground">Выручка</div><div className="text-lg tabular-nums">{money(stats.total_revenue)} ₽</div></div>
          <div><div className="text-xs text-muted-foreground">Стоимость ордеров</div><div className="text-lg tabular-nums">{money(stats.total_orders_value)} ₽</div></div>
          <div><div className="text-xs text-muted-foreground">Ср. профит</div><div className="text-lg"><Signed value={stats.avg_profit_pct ?? 0} digits={1} suffix="%" /></div></div>
        </div>
      </Card>
    </div>
  );
}

function SubsystemCard({ title, running, sub, onStart, onStop }: any) {
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium">{title}</span>
        <Badge ok={running}>{running ? "работает" : "остановлен"}</Badge>
      </div>
      <div className="mb-4 text-xs text-muted-foreground">{sub}</div>
      <div className="flex gap-2">
        <Button variant="success" onClick={onStart} disabled={running}>Старт</Button>
        <Button variant="ghost" onClick={onStop} disabled={!running}>Стоп</Button>
      </div>
    </Card>
  );
}
