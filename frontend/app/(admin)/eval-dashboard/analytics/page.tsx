import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/page-header";

const KPI_DEFINITIONS = [
  { id: "acceptance_pass_rate", label: "合格率", unit: "%", threshold: 60 },
  { id: "time_to_merge", label: "マージ時間", unit: "h", threshold: 2.0 },
  { id: "approval_wait_ms", label: "承認待ち", unit: "h", threshold: 4.0 },
  { id: "citation_coverage", label: "引用カバレッジ", unit: "%", threshold: 90 },
  {
    id: "cost_per_completed_task",
    label: "タスク単価",
    unit: "$",
    threshold: 0.5,
  },
] as const;

function KpiSummaryCard({
  kpi,
}: {
  kpi: (typeof KPI_DEFINITIONS)[number];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {kpi.label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">
          --{kpi.unit}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          閾値: {kpi.threshold}
          {kpi.unit}
        </p>
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  return (
    <section aria-label="KPI Analytics" className="grid gap-6">
      <PageHeader
        title="KPI 分析"
        description="Quality KPIs の時系列推移と drill-down"
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {KPI_DEFINITIONS.map((kpi) => (
          <KpiSummaryCard key={kpi.id} kpi={kpi} />
        ))}
      </div>

      <Tabs defaultValue="7d">
        <TabsList>
          <TabsTrigger value="7d">7日</TabsTrigger>
          <TabsTrigger value="30d">30日</TabsTrigger>
          <TabsTrigger value="90d">90日</TabsTrigger>
        </TabsList>
        <TabsContent value="7d">
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              7日間の推移グラフ (データ接続後に表示)
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="30d">
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              30日間の推移グラフ
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="90d">
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              90日間の推移グラフ
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </section>
  );
}
