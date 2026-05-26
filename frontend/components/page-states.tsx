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
        {retry && (
          <button
            type="button"
            onClick={retry}
            className="rounded-md bg-destructive px-4 py-2 text-sm text-white hover:bg-destructive/90"
          >
            再試行
          </button>
        )}
      </CardContent>
    </Card>
  );
}

export function EmptyState({
  title = "データがありません",
  description,
}: {
  title?: string;
  description?: string;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-12 text-center">
        <p className="font-medium text-muted-foreground">{title}</p>
        {description && (
          <p className="text-sm text-muted-foreground/70">{description}</p>
        )}
      </CardContent>
    </Card>
  );
}
