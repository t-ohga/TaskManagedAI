"use client";

type ExportButtonProps = {
  data: Record<string, unknown>[];
  filename: string;
  format?: "csv" | "json";
};

export function ExportButton({ data, filename, format = "csv" }: ExportButtonProps) {
  function handleExport() {
    let content: string;
    let mime: string;

    if (format === "json") {
      content = JSON.stringify(data, null, 2);
      mime = "application/json";
    } else {
      if (data.length === 0) return;
      const headers = Object.keys(data[0] ?? {});
      const rows = data.map((row) =>
        headers.map((h) => {
          const val = String(row[h] ?? "");
          return val.includes(",") || val.includes('"') ? `"${val.replace(/"/g, '""')}"` : val;
        }).join(",")
      );
      content = [headers.join(","), ...rows].join("\n");
      mime = "text/csv";
    }

    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <button
      type="button"
      onClick={handleExport}
      disabled={data.length === 0}
      className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-slate-50 disabled:opacity-50"
    >
      {format === "json" ? "JSON" : "CSV"} エクスポート
    </button>
  );
}
