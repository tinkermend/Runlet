import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus, Server } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { SystemItem } from "../../../lib/http/types";

function statusBadgeClass(status: string) {
  switch (status) {
    case "ready":      return "badge badge-success";
    case "onboarding": return "badge badge-warning";
    case "failed":     return "badge badge-danger";
    default:           return "badge badge-neutral";
  }
}

const STATUS_LABELS: Record<string, string> = {
  ready: "已就绪", onboarding: "接入中", failed: "失败",
};

export function SystemListPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["systems"],
    queryFn: () => apiFetch<SystemItem[]>("/api/console/portal/systems"),
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">系统接入</h1>
          <p className="page-subtitle">管理已接入的目标系统</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => navigate("/systems/new")}>
          <Plus size={14} />
          接入新系统
        </button>
      </div>

      {isLoading ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
          {[1,2,3].map(i => (
            <div key={i} className="card card-body">
              <div className="skeleton" style={{ height: 16, width: "60%", marginBottom: 12 }} />
              <div className="skeleton" style={{ height: 12, width: "40%", marginBottom: 16 }} />
              <div className="skeleton" style={{ height: 30, width: "50%" }} />
            </div>
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <div className="empty-state-icon"><Server size={22} /></div>
            <div className="empty-state-title">暂无接入系统</div>
            <div className="empty-state-desc">接入第一个系统，开始采集资产和创建检查任务</div>
            <button className="btn btn-primary btn-sm" onClick={() => navigate("/systems/new")}>
              <Plus size={14} />
              接入新系统
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
          {data.map((sys) => (
            <div key={sys.id} className="card card-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <span style={{ fontSize: 15, fontWeight: 600, color: "var(--fg)" }}>{sys.name}</span>
                <span className={statusBadgeClass(sys.status)}>
                  {STATUS_LABELS[sys.status] ?? sys.status}
                </span>
              </div>
              <div style={{ fontSize: 12, color: "var(--fg-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {sys.base_url}
              </div>
              <div style={{ fontSize: 13, color: "var(--fg-dim)" }}>{sys.task_count} 个任务</div>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => navigate(`/tasks?system_id=${sys.id}`)}
                style={{ alignSelf: "flex-start", marginTop: 4 }}
              >
                查看任务
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
