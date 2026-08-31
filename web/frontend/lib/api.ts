"use client";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const TOKEN_KEY = "tm_api_token";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return sessionStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t: string) {
  if (typeof window !== "undefined") sessionStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  if (typeof window !== "undefined") sessionStorage.removeItem(TOKEN_KEY);
}

async function req(path: string, opts: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    // Сессия истекла или отозвана — чистим, чтобы Shell показал форму входа.
    clearToken();
    throw new Error("unauthorized");
  }
  if (res.status === 429) throw new Error("Слишком много запросов, подождите");
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

export const api = {
  health: () => fetch(`${API_BASE}/api/health`).then((r) => r.json()),
  status: () => req("/api/status"),
  accounts: () => req("/api/accounts"),
  orders: () => req("/api/orders"),
  cancelOrder: (orderId: string) =>
    req(`/api/orders/${encodeURIComponent(orderId)}/cancel`, { method: "POST" }),
  inventory: () => req("/api/inventory"),
  profitable: () => req("/api/profitable"),
  sales: () => req("/api/sales"),
  history: () => req("/api/history"),
  logs: (limit = 200) => req(`/api/logs?limit=${limit}`),
  config: () => req("/api/config"),
  saveConfig: (config: any) =>
    req("/api/config", { method: "POST", body: JSON.stringify({ config }) }),
  botStart: () => req("/api/bot/start", { method: "POST" }),
  botStop: () => req("/api/bot/stop", { method: "POST" }),
  salesStart: () => req("/api/sales/start", { method: "POST" }),
  salesStop: () => req("/api/sales/stop", { method: "POST" }),
  scannerStart: () => req("/api/scanner/start", { method: "POST" }),
  scannerStop: () => req("/api/scanner/stop", { method: "POST" }),
  scanRun: (n = 10) => req(`/api/scan/run?max_items=${n}`, { method: "POST" }),
  command: (text: string) => req("/api/command", { method: "POST", body: JSON.stringify({ text }) }),
  logout: () => req("/api/logout", { method: "POST" }),
};

/** Вход по паролю. Возвращает "" при успехе, иначе текст ошибки. */
export async function login(password: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.status === 429) {
      return "Слишком много попыток входа. Попробуйте через 15 минут.";
    }
    if (res.status === 401) return "Неверный пароль";
    if (!res.ok) return `Ошибка сервера (${res.status})`;
    const data = await res.json();
    if (!data?.token) return "Сервер не выдал токен сессии";
    setToken(data.token);
    return "";
  } catch {
    return "Нет связи с сервером";
  }
}

/** Проверка сессии: true если /api/status отвечает (не 401). */
export async function verifyToken(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * URL для WebSocket. Токен сессии в query-строку НЕ кладём — он оседал бы в
 * access-логах nginx и в истории браузера. Вместо него берём одноразовый
 * тикет на 30 секунд.
 */
export async function wsUrl(): Promise<string> {
  const { ticket } = await req("/api/ws-ticket", { method: "POST" });
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/ws?ticket=${encodeURIComponent(ticket)}`;
}
