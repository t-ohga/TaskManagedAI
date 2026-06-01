import type { Route } from "next";
import Link from "next/link";

import { Card, CardContent } from "@/components/ui/card";

export function LoadingState({ label = "読み込み中..." }: { label?: string }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center py-12">
        <div className="flex items-center gap-3 text-muted-foreground">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          <span>{label}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function ErrorState({
  message = "データの取得に失敗しました",
  retry,
}: {
  message?: string;
  retry?: () => void;
}) {
  return (
    <Card className="border-destructive/50">
      <CardContent className="flex flex-col items-center gap-3 py-12">
        <p className="text-destructive font-medium">{message}</p>
        {retry ? <button
            type="button"
            onClick={retry}
            className="rounded-md bg-destructive px-4 py-2 text-sm text-white hover:bg-destructive/90"
          >
            再試行
          </button> : null}
      </CardContent>
    </Card>
  );
}

// O-5 (UI 監査 fix): 空状態に「次に何をすればよいか」を示す CTA を任意で表示できるようにする。
// action は内部 route への遷移のみ (typed Route)。外部 URL は受け取らない。
export function EmptyState({
  title = "データがありません",
  description,
  action,
}: {
  title?: string;
  description?: string;
  action?: { label: string; href: Route };
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
        <p className="font-medium text-muted-foreground">{title}</p>
        {description ? <p className="text-sm text-muted-foreground/70">{description}</p> : null}
        {action ? <Link
            href={action.href}
            className="mt-3 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          >
            {action.label}
          </Link> : null}
      </CardContent>
    </Card>
  );
}
