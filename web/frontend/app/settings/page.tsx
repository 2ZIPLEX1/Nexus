"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/useLive";
import { PageTitle, Card, Button } from "@/components/ui";

const FIELDS: { key: string; label: string }[] = [
  { key: "cycle_interval_minutes", label: "Интервал buy-цикла (мин)" },
  { key: "scan_interval_minutes", label: "Интервал сканера (мин)" },
  { key: "min_profit_pct", label: "Мин. профит (%)" },
  { key: "trade_min_price", label: "Мин. цена предмета" },
  { key: "trade_max_price", label: "Макс. цена предмета" },
  { key: "scanner_min_profit", label: "Мин. профит сканера (%)" },
  { key: "auto_scan_new_items", label: "Новых за скан" },
  { key: "price_check_threshold_percent", label: "Порог репрайса (%)" },
];

export default function SettingsPage() {
  const load = useCallback(() => api.config(), []);
  const { data } = usePolling<any>(load);
  const [cfg, setCfg] = useState<any>({});
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data) setCfg(data); }, [data]);

  const save = async () => {
    await api.saveConfig(cfg);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="max-w-2xl">
      <PageTitle title="Настройки" right={saved ? <span className="text-sm text-success">Сохранено</span> : null} />
      <Card>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {FIELDS.map((f) => (
            <label key={f.key} className="text-sm">
              <span className="mb-1 block text-muted-foreground">{f.label}</span>
              <input
                className="w-full rounded-md border bg-secondary px-3 py-2 outline-none focus:ring-2 focus:ring-ring"
                value={cfg[f.key] ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setCfg({ ...cfg, [f.key]: v === "" ? "" : isNaN(Number(v)) ? v : Number(v) });
                }}
              />
            </label>
          ))}
        </div>
        <div className="mt-5"><Button onClick={save}>Сохранить</Button></div>
      </Card>
    </div>
  );
}
