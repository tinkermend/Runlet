import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { TaskItem } from "../../../lib/http/types";

const STATUS_COLORS: Record<string, string> = {
  running: "#22C55E",
  failed: "#EF4444",
  idle: "#64748B",
  disabled: "#334155",
};

const STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  failed: "失败",
  idle: "空闲",
  disabled: "已禁用",
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

export function TaskListPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiFetch<TaskItem[]>("/api/console/tasks/"),
  });

  const triggerMutation = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/console/tasks/${id}/trigger`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  if (isLoading) return <div style={{ color: "#94A3B8" }}>加载中...</div>;
  if (error || !data) return <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, margin: 0 }}>检查任务</h1>
        <button
          onClick={() => navigate("/tasks/new")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
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
          <Plus size={16} />
          新建检查任务
        </button>
      </div>

      <div style={{ background: "#0F172A", border: "1px solid #334155", borderRadius: 8, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              {["任务名称", "系统", "状态", "上次运行", "操作"].map((h) => (
                <th key={h} style={{ padding: "12px 16px", textAlign: "left", color: "#94A3B8", fontSize: 13, fontWeight: 600 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: "32px 16px", textAlign: "center", color: "#64748B", fontSize: 14 }}>
                  暂无任务
                </td>
              </tr>
            ) : (
              data.map((task, i) => (
                <tr
                  key={task.id}
                  style={{ borderBottom: i < data.length - 1 ? "1px solid #1E293B" : "none" }}
                >
                  <td style={{ padding: "12px 16px" }}>
                    <button
                      onClick={() => navigate(`/tasks/${task.id}`)}
                      style={{ background: "none", border: "none", color: "#F8FAFC", fontSize: 14, cursor: "pointer", padding: 0, fontWeight: 500 }}
                    >
                      {task.name}
                    </button>
                  </td>
                  <td style={{ padding: "12px 16px", color: "#94A3B8", fontSize: 14 }}>{task.system_name}</td>
                  <td style={{ padding: "12px 16px" }}><StatusBadge status={task.status} /></td>
                  <td style={{ padding: "12px 16px", color: "#64748B", fontSize: 13 }}>
                    {task.last_run_at ? new Date(task.last_run_at).toLocaleString("zh-CN") : "—"}
                  </td>
                  <td style={{ padding: "12px 16px" }}>
                    <button
                      onClick={() => triggerMutation.mutate(task.id)}
                      disabled={triggerMutation.isPending}
                      style={{
                        padding: "4px 12px",
                        background: "transparent",
                        color: "#22C55E",
                        border: "1px solid #22C55E",
                        borderRadius: 4,
                        fontSize: 13,
                        cursor: "pointer",
                      }}
                    >
                      立即运行
                    </button>
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
