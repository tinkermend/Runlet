import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus, Server, AlertTriangle } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { DashboardSummary } from "../../../lib/http/types";

function StatCard({ label, value, accent, danger }: {
  label: string; value: number; accent?: boolean; danger?: boolean;
}) {
  return (
    <div className={`stat-card${accent ? " accent" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={danger && value > 0 ? { color: "var(--danger)" } : undefined}>
        {value}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div>
      <div className="stat-grid">
        {[1,2,3,4].map(i => (
          <div key={i} className="stat-card">
            <div className="skeleton" style={{ height: 12, width: "60%", marginBottom: 12 }} />
            <div className="skeleton" style={{ height: 32, width: "40%" }} />
          </div>
        ))}
      </div>
      <div className="card">
        <div className="card-body">
          {[1,2,3].map(i => (
            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 14 }}>
              <div className="skeleton" style={{ width: 8, height: 8, borderRadius: "50%", marginTop: 4, flexShrink: 0 }} />
              <div className="skeleton" style={{ height: 14, flex: 1 }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardSummary>("/api/console/portal/dashboard"),
  });

  if (isLoading) return <LoadingSkeleton />;

  if (error || !data) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">
          <AlertTriangle size={22} />
        </div>
        <div className="empty-state-title">加载失败</div>
        <div className="empty-state-desc">无法获取 Dashboard 数据，请刷新重试</div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">平台运行概览</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-outline btn-sm" onClick={() => navigate("/systems/new")}>
            <Server size={14} />
            接入系统
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => navigate("/tasks/new")}>
            <Plus size={14} />
            新建检查任务
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="stat-grid">
        <StatCard label="今日运行次数" value={data.today_runs} />
        <StatCard label="活跃任务数"   value={data.active_tasks} accent />
        <StatCard label="系统数量"     value={data.systems_count} />
        <StatCard label="近24h异常"    value={data.recent_failures_24h} danger />
      </div>

      {/* Recent exceptions */}
      <div className="mb-8">
        <div className="section-title">最近异常</div>
        {data.recent_exceptions.length === 0 ? (
          <div className="card">
            <div style={{ padding: "32px 20px", textAlign: "center", color: "var(--fg-dim)", fontSize: 14 }}>
              近期无异常记录
            </div>
          </div>
        ) : (
          <div className="table-wrap">
            {data.recent_exceptions.map((exc, i) => (
              <div key={i} style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "13px 16px",
                borderBottom: i < data.recent_exceptions.length - 1 ? "1px solid var(--border-subtle)" : "none",
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: "var(--danger)", flexShrink: 0,
                  boxShadow: "0 0 6px rgba(239,68,68,.5)",
                }} />
                <span style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>{exc.task_name}</span>
                <span className="badge badge-neutral" style={{ fontSize: 11 }}>{exc.system_name}</span>
                <span className="text-dim text-xs">
                  {new Date(exc.created_at).toLocaleString("zh-CN")}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
