"use client";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useLive, usePolling } from "@/lib/useLive";
import { PageTitle, Card, Button, Badge, DataTable, Signed } from "@/components/ui";

export default function ScannerPage() {
  const { rev } = useLive();
  const loadStatus = useCallback(() => api.status(), []);
  const { data: st, reload } = usePolling<any>(loadStatus, rev["scanner_state"]);
  const loadItems = useCallback(() => api.profitable(), []);
  const { data: items } = usePolling<any[]>(loadItems, rev["stats"], []);
  const [busy, setBusy] = useState(false);

  const runScan = async () => {
    setBusy(true);
    try { await api.scanRun(15); } finally { setBusy(false); reload(); }
  };

  return (
    <div>
      <PageTitle title="Сканер" right={<Badge ok={st?.scanner_running}>{st?.scanner_running ? "работает" : "остановлен"}</Badge>} />
      <Card className="mb-6">
        <div className="mb-4 text-sm text-muted-foreground">Авто-скан каждые {st?.scan_min ?? "—"} мин. Ручной скан ищет новые профитные предметы сейчас.</div>
        <div className="flex gap-2">
          <Button variant="success" onClick={() => api.scannerStart().then(reload)} disabled={st?.scanner_running}>Старт авто</Button>
          <Button variant="ghost" onClick={() => api.scannerStop().then(reload)} disabled={!st?.scanner_running}>Стоп</Button>
          <Button onClick={runScan} disabled={busy}>{busy ? "Сканирую…" : "Скан сейчас"}</Button>
        </div>
      </Card>
      <h2 className="mb-3 text-lg font-medium">Профитные предметы</h2>
      <DataTable
        rows={items || []}
        columns={[
          { key: "market_hash_name", label: "Предмет" },
          { key: "steam_buy_order", label: "Steam buy", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "csgo_price", label: "CSGO.TM", fmt: (v) => (v ?? 0).toLocaleString("ru-RU") },
          { key: "recommended_profit_pct", label: "Профит %", fmt: (v, r) => <Signed value={Number(v ?? r.profit_pct ?? 0)} digits={1} suffix="%" /> },
        ]}
      />
    </div>
  );
}
