"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Users, ScrollText, Boxes, Radar, Tags,
  ShoppingCart, History, BarChart3, Settings, Terminal,
} from "lucide-react";
import { cn, getToken, login, verifyToken } from "@/lib/api";
import { useLive } from "@/lib/useLive";

const NAV = [
  { href: "/", label: "Дашборд", icon: LayoutDashboard },
  { href: "/accounts", label: "Аккаунты", icon: Users },
  { href: "/orders", label: "Ордера", icon: ScrollText },
  { href: "/inventory", label: "Инвентарь", icon: Boxes },
  { href: "/scanner", label: "Сканер", icon: Radar },
  { href: "/sales", label: "Продажи", icon: Tags },
  { href: "/auto-buy", label: "Авто-покупка", icon: ShoppingCart },
  { href: "/history", label: "История", icon: History },
  { href: "/statistics", label: "Статистика", icon: BarChart3 },
  { href: "/settings", label: "Настройки", icon: Settings },
  { href: "/logs", label: "Логи", icon: Terminal },
];

function NavItem({ item, expanded, active }: any) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      style={{ ["--nav-item-accent" as any]: "rgb(var(--uxera-accent-rgb) / 1)" }}
      className={cn(
        "group/navitem relative min-h-10 rounded-[6px] border transition-[border-color,background-color,box-shadow,transform] duration-150 active:scale-[0.99]",
        active
          ? "border-theme-primary-20 bg-theme-primary-10 shadow-[0_0_16px_rgb(var(--uxera-accent-rgb)/0.12)]"
          : "border-border bg-foreground/[0.015] hover:border-foreground/15 hover:bg-foreground/[0.03]"
      )}
    >
      <div className={cn(
        "grid min-h-10 items-center py-1.5 transition-[grid-template-columns,gap,padding] duration-200",
        expanded ? "grid-cols-[24px_minmax(0,1fr)] gap-2.5 pl-1.5 pr-2" : "grid-cols-[24px_0px] gap-0 pl-2 pr-0"
      )}>
        <span className={cn(
          "flex h-6 w-6 items-center justify-center rounded-[5px] border transition-colors duration-200",
          active
            ? "border-[var(--nav-item-accent)] text-[var(--nav-item-accent)] bg-theme-primary-10"
            : "border-border bg-foreground/[0.02] text-muted-foreground group-hover/navitem:text-foreground"
        )}>
          <Icon className="h-3.5 w-3.5 stroke-[1.6]" />
        </span>
        <span className={cn(
          "min-w-0 whitespace-nowrap text-left text-[13px] font-medium transition-opacity duration-150",
          active ? "text-foreground" : "text-foreground/75",
          expanded ? "opacity-100 delay-75" : "pointer-events-none opacity-0"
        )}>
          {item.label}
        </span>
      </div>
    </Link>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { connected } = useLive();
  const [expanded, setExpanded] = useState(false);
  const [authed, setAuthed] = useState<boolean | null>(null); // null = проверка
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  // Проверяем сохранённую сессию при загрузке
  useEffect(() => {
    const t = getToken();
    if (!t) { setAuthed(false); return; }
    verifyToken(t).then((ok) => setAuthed(ok));
  }, []);

  const submit = async () => {
    if (!password) return;
    setChecking(true);
    setError("");
    // Пароль уходит на /api/login и обменивается на сессионный токен с TTL;
    // сам пароль нигде не сохраняется.
    const err = await login(password);
    setChecking(false);
    setPassword("");
    if (!err) { setAuthed(true); }
    else { setError(err); }
  };

  if (authed === null) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Проверка доступа…</div>;
  }

  if (!authed) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="uxera-glass-panel w-full max-w-md p-8">
          <div className="mb-5 flex items-center gap-3">
            <div className="h-9 w-9 rounded-[7px] bg-gradient-to-br from-[#A855F7] to-[#7C3AED] shadow-[0_0_18px_rgb(var(--uxera-accent-rgb)/0.4)]" />
            <span className="text-lg font-bold uppercase tracking-[0.12em]">Steam Bot</span>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">
            Введите пароль доступа.
          </p>
          <input
            type="password"
            autoComplete="current-password"
            className="uxera-glass-field mb-3 w-full rounded-md px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          {error && <div className="mb-3 text-sm text-destructive">{error}</div>}
          <button
            disabled={checking}
            className="w-full rounded-md bg-gradient-to-r from-[#A855F7] to-[#7C3AED] px-3 py-2 text-sm font-semibold text-white shadow-[0_0_20px_rgb(var(--uxera-accent-rgb)/0.35)] disabled:opacity-50"
            onClick={submit}
          >
            {checking ? "Проверка…" : "Войти"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Fixed rail sidebar (uxera): 50px → 292px on hover */}
      <aside
        className={cn("fixed left-0 top-0 z-[60] h-dvh", expanded ? "w-[292px]" : "w-[50px]")}
        onMouseEnter={() => setExpanded(true)}
        onMouseLeave={() => setExpanded(false)}
      >
        <div className={cn(
          "relative h-full overflow-visible py-2 transition-[width] duration-200 ease-out",
          expanded ? "w-[292px] pr-2" : "w-[50px] pr-0"
        )}>
          <div className={cn(
            "h-full rounded-[8px] border border-transparent transition-[border-color,background-color,box-shadow] duration-200",
            expanded && "border-border bg-card/70 shadow-[18px_0_45px_rgba(17,17,26,0.08)] backdrop-blur-[8px]"
          )}>
            <div className="mb-3 grid h-[56px] grid-cols-[42px_minmax(0,1fr)] items-center gap-2 px-1.5">
              <div className="h-[34px] w-[34px] shrink-0 rounded-[7px] bg-gradient-to-br from-[#A855F7] to-[#7C3AED] shadow-[0_0_16px_rgb(var(--uxera-accent-rgb)/0.35)]" />
              <span className={cn(
                "whitespace-nowrap text-xl font-bold uppercase tracking-[0.12em] text-foreground transition-opacity duration-150",
                expanded ? "opacity-100" : "opacity-0"
              )}>
                Steam Bot
              </span>
            </div>

            <div className="h-[calc(100%-64px)] overflow-hidden">
              <div className="no-scrollbar flex h-full flex-col gap-1.5 overflow-y-auto pb-2 pl-1 pr-1">
                {NAV.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname?.startsWith(item.href);
                  return <NavItem key={item.href} item={item} expanded={expanded} active={active} />;
                })}
                <div className={cn(
                  "mt-2 flex items-center gap-2 px-2 py-2 text-[11px] text-muted-foreground transition-opacity",
                  expanded ? "opacity-100" : "opacity-0"
                )}>
                  <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-[rgb(var(--success-rgb))]" : "bg-foreground/25")} />
                  {connected ? "live" : "offline"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <main className="min-h-screen pl-[50px]">
        <div className="mx-auto max-w-[1400px] p-6">{children}</div>
      </main>
    </div>
  );
}
