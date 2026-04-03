import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../../lib/http/client";
import type { SystemItem } from "../../../lib/http/types";

const STATUS_COLORS: Record<string, string> = {
  ready: "#22C55E",
  onboarding: "#F59E0B",
  failed: "#EF4444",
};

const STATUS_LABELS: Record<string, string> = {
  ready: "已就绪",
  onboarding: "接入中",
  failed: "失败",
};

export function SystemListPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["systems"],
    queryFn: () => apiFetch<SystemItem[]>("/api/console/portal/systems"),
  });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700 }}>系统接入</h1>
        <button
          onClick={() => navigate("/systems/new")}
          style={{
            padding: "8px 16px",
            background: "#22C55E",
            color: "#020617",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          + 接入新系统
        </button>
      </div>

      {isLoading && <div style={{ color: "#94A3B8" }}>加载中...</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
        {(data ?? []).map((sys) => (
          <div key={sys.id} style={{
            background: "#0F172A",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: 20,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
              <span style={{ color: "#F8FAFC", fontSize: 16, fontWeight: 600 }}>{sys.name}</span>
              <span style={{
                fontSize: 12,
                padding: "2px 8px",
                borderRadius: 4,
                background: `${STATUS_COLORS[sys.status] ?? "#64748B"}20`,
                color: STATUS_COLORS[sys.status] ?? "#64748B",
              }}>
                {STATUS_LABELS[sys.status] ?? sys.status}
              </span>
            </div>
            <div style={{ color: "#64748B", fontSize: 13, marginBottom: 12 }}>{sys.task_count} 个任务</div>
            <button
              onClick={() => navigate(`/tasks?system_id=${sys.id}`)}
              style={{
                padding: "6px 12px",
                background: "transparent",
                color: "#94A3B8",
                border: "1px solid #334155",
                borderRadius: 4,
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              查看资产
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
