import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../../lib/http/client";
import type { DashboardSummary } from "../../../lib/http/types";

function SummaryCard({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div style={{
      background: "#0F172A",
      border: `1px solid ${accent ? "#22C55E" : "#334155"}`,
      borderRadius: 8,
      padding: "16px 20px",
      flex: 1,
      minWidth: 140,
    }}>
      <div style={{ color: "#94A3B8", fontSize: 13, marginBottom: 8 }}>{label}</div>
      <div style={{ color: accent ? "#22C55E" : "#F8FAFC", fontSize: 28, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardSummary>("/api/console/portal/dashboard"),
  });

  if (isLoading) {
    return <div style={{ color: "#94A3B8" }}>加载中...</div>;
  }

  if (error || !data) {
    return <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>;
  }

  return (
    <div>
      <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, marginBottom: 24 }}>Dashboard</h1>

      <div style={{ display: "flex", gap: 16, marginBottom: 32, flexWrap: "wrap" }}>
        <SummaryCard label="今日运行次数" value={data.today_runs} />
        <SummaryCard label="活跃任务数" value={data.active_tasks} accent />
        <SummaryCard label="系统数量" value={data.systems_count} />
        <SummaryCard label="近24h异常" value={data.recent_failures_24h} />
      </div>

      <div style={{ marginBottom: 32 }}>
        <h2 style={{ color: "#F8FAFC", fontSize: 16, fontWeight: 600, marginBottom: 12 }}>最近异常</h2>
        {data.recent_exceptions.length === 0 ? (
          <div style={{ color: "#64748B", fontSize: 14 }}>暂无异常记录</div>
        ) : (
          <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, overflow: "hidden" }}>
            {data.recent_exceptions.map((exc, i) => (
              <div key={i} style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 16px",
                borderBottom: i < data.recent_exceptions.length - 1 ? "1px solid #1E293B" : "none",
              }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#EF4444", flexShrink: 0 }} />
                <span style={{ color: "#F8FAFC", fontSize: 14, flex: 1 }}>{exc.task_name}</span>
                <span style={{ color: "#94A3B8", fontSize: 13 }}>{exc.system_name}</span>
                <span style={{ color: "#64748B", fontSize: 12 }}>{new Date(exc.created_at).toLocaleString("zh-CN")}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <button
          onClick={() => navigate("/tasks/new")}
          style={{
            padding: "10px 20px",
            background: "#22C55E",
            color: "#020617",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          新建检查任务
        </button>
        <button
          onClick={() => navigate("/systems/new")}
          style={{
            padding: "10px 20px",
            background: "transparent",
            color: "#22C55E",
            border: "1px solid #22C55E",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          去接入系统
        </button>
      </div>
    </div>
  );
}
