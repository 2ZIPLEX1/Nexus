"use client";
import { PageTitle, Card } from "@/components/ui";

export default function AutoBuyPage() {
  return (
    <div>
      <PageTitle title="Авто-покупка" />
      <Card>
        <div className="text-sm text-muted-foreground">
          Раздел управления списком авто-покупки. Бэкенд-эндпоинты для CRUD списка появятся
          в следующей итерации (сейчас исключения из скана берутся из AutoBuyService на сервере).
        </div>
      </Card>
    </div>
  );
}
