"use client";
import { cn } from "@/lib/api";

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("glass p-5", className)}>{children}</div>;
}

export function PageTitle({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {right}
    </div>
  );
}

export function StatCard({ label, value, sub, accent }: { label: string; value: React.ReactNode; sub?: string; accent?: boolean }) {
  return (
    <Card className={cn(accent && "shadow-theme-glow")}>
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

export function Button({
  children, onClick, variant = "default", disabled,
}: {
  children: React.ReactNode; onClick?: () => void;
  variant?: "default" | "ghost" | "danger" | "success"; disabled?: boolean;
}) {
  // Кнопки в стиле uxera: primary — белая, вторичная — прозрачное стекло
  const styles = {
    default: "uxera-btn-white",
    ghost: "uxera-glass-button",
    success: "uxera-btn-white",
    danger: "border border-destructive/40 bg-destructive/15 text-destructive hover:bg-destructive/25",
  }[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn("rounded-md px-4 py-2 text-sm font-medium transition disabled:opacity-50", styles)}
    >
      {children}
    </button>
  );
}

export function Badge({ ok, children }: { ok?: boolean; children: React.ReactNode }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-full px-2 py-0.5 text-xs",
      ok ? "bg-[rgb(var(--success-rgb)/0.15)] text-success" : "bg-muted text-muted-foreground"
    )}>
      {children}
    </span>
  );
}

/** Число со знаковой окраской: >0 зелёное, <0 красное, 0 — приглушённое. */
export function Signed({ value, digits = 0, suffix = "", showPlus = true }: { value: number; digits?: number; suffix?: string; showPlus?: boolean }) {
  const n = Number(value ?? 0);
  const cls = n > 0 ? "text-emerald-400" : n < 0 ? "text-red-400" : "text-muted-foreground";
  const sign = n > 0 && showPlus ? "+" : "";
  return <span className={cn("font-medium tabular-nums", cls)}>{sign}{n.toLocaleString("ru-RU", { maximumFractionDigits: digits })}{suffix}</span>;
}

export function money(n: number, c = "") {
  return `${Number(n ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 })}${c ? " " + c : ""}`;
}

export function DataTable({ rows, columns }: { rows: any[]; columns: { key: string; label: string; fmt?: (v: any, row: any) => React.ReactNode }[] }) {
  if (!rows?.length) return <Card><div className="text-sm text-muted-foreground">Нет данных</div></Card>;
  return (
    <div className="glass overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[12px] uppercase tracking-wide text-muted-foreground">
            {columns.map((c) => <th key={c.key} className="px-4 py-3 font-medium">{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border/40 last:border-0 hover:bg-white/[0.03]">
              {columns.map((c, ci) => (
                <td key={c.key} className={cn(
                  "px-4 py-3 tabular-nums",
                  ci === 0 ? "font-medium text-foreground" : "text-foreground/70"
                )}>
                  {c.fmt ? c.fmt(row[c.key], row) : String(row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
