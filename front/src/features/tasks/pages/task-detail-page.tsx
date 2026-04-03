import { useQuery, useMutation } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { Play } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { TaskDetail } from "../../../lib/http/types";

const STATUS_COLORS: Record<string, string> = {
  running: "#22C55E",
  failed: "#EF4444",
  idle: "#64748B",
  disabled: "#334155",
  success: "#22C55E",
  error: "#EF4444",
};

const STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  failed: "失败",
  idle: "空闲",
  disabled: "已禁用",
  success: "成功",
  error: "错误",
};

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? "#64748B";
  const label = STATUS_LABELS[status] ?? status;
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: 12,
      fontSize: 12,
      fontWeight: 600,
      background: color + "22",
      color,
      border: `1px solid ${color}44`,
    }}>
      {label}
    </span>
  );
}

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data, isLoading, error } = useQuery({
    queryKey: ["task", id],
    queryFn: () => apiFetch<TaskDetail>(`/api/console/tasks/${id}`),
    enabled: !!id,
  });

  const triggerMutation = useMutation({
    mutationFn: () => apiFetch(`/api/console/tasks/${id}/trigger`, { method: "POST" }),
  });

  if (isLoading) return <div style={{ color: "#94A3B8" }}>加载中...</div>;
  if (error || !data) return <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
        <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, margin: 0 }}>{data.name}</h1>
        <StatusBadge status={data.status} />
        <button
          onClick={() => triggerMutation.mutate()}
          disabled={triggerMutation.isPending}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 14px",
            background: "#22C55E",
            color: "#020617",
            border: "none",
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            marginLeft: "auto",
          }}
        >
          <Play size={14} />
          立即运行
        </button>
      </div>

      <div style={{ color: "#94A3B8", fontSize: 14, marginBottom: 24 }}>
        {data.system_name} · {data.schedule_preset}
      </div>

      <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #334155" }}>
          <span style={{ color: "#94A3B8", fontSize: 13, fontWeight: 600 }}>最近运行记录</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              {["时间", "状态", "耗时"].map((h) => (
                <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#94A3B8", fontSize: 13, fontWeight: 600 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.recent_runs.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: "24px 16px", textAlign: "center", color: "#64748B", fontSize: 14 }}>
                  暂无运行记录
                </td>
              </tr>
            ) : (
              data.recent_runs.map((run, i) => (
                <tr key={run.id} style={{ borderBottom: i < data.recent_runs.length - 1 ? "1px solid #1E293B" : "none" }}>
                  <td style={{ padding: "10px 16px", color: "#94A3B8", fontSize: 13 }}>
                    {new Date(run.created_at).toLocaleString("zh-CN")}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <StatusBadge status={run.status} />
                  </td>
                  <td style={{ padding: "10px 16px", color: "#64748B", fontSize: 13 }}>
                    {run.duration_ms != null ? `${run.duration_ms} ms` : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
