import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Plus, Play, ClipboardCheck } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { TaskItem } from "../../../lib/http/types";

function statusBadgeClass(status: string) {
  switch (status) {
    case "running":  return "badge badge-success";
    case "failed":   return "badge badge-danger";
    case "disabled": return "badge badge-neutral";
    default:         return "badge badge-neutral";
  }
}

const STATUS_LABELS: Record<string, string> = {
  running: "运行中", failed: "失败", idle: "空闲", disabled: "已禁用",
};

export function TaskListPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiFetch<TaskItem[]>("/api/console/tasks/"),
  });

  const triggerMutation = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/console/tasks/${id}/trigger`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">检查任务</h1>
          <p className="page-subtitle">管理和调度自动化检查任务</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => navigate("/tasks/new")}>
          <Plus size={14} />
          新建检查任务
        </button>
      </div>

      {isLoading ? (
        <div className="table-wrap">
          {[1,2,3].map(i => (
            <div key={i} style={{ display: "flex", gap: 16, padding: "14px 16px", borderBottom: "1px solid var(--border-subtle)" }}>
              <div className="skeleton" style={{ height: 14, width: "25%" }} />
              <div className="skeleton" style={{ height: 14, width: "15%" }} />
              <div className="skeleton" style={{ height: 14, width: "10%" }} />
              <div className="skeleton" style={{ height: 14, width: "20%" }} />
            </div>
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <div className="table-wrap">
          <div className="empty-state">
            <div className="empty-state-icon">
              <ClipboardCheck size={22} />
            </div>
            <div className="empty-state-title">暂无检查任务</div>
            <div className="empty-state-desc">创建第一个检查任务，开始自动化监控</div>
            <button className="btn btn-primary btn-sm" onClick={() => navigate("/tasks/new")}>
              <Plus size={14} />
              新建检查任务
            </button>
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>任务名称</th>
                <th>系统</th>
                <th>状态</th>
                <th>上次运行</th>
                <th>调度</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((task) => (
                <tr key={task.id}>
                  <td>
                    <button
                      onClick={() => navigate(`/tasks/${task.id}`)}
                      style={{
                        background: "none", border: "none", color: "var(--fg)",
                        fontSize: 14, cursor: "pointer", padding: 0, fontWeight: 500,
                        textAlign: "left",
                      }}
                    >
                      {task.name}
                    </button>
                  </td>
                  <td className="cell-muted">{task.system_name}</td>
                  <td>
                    <span className={statusBadgeClass(task.status)}>
                      {STATUS_LABELS[task.status] ?? task.status}
                    </span>
                  </td>
                  <td className="cell-dim">
                    {task.last_run_at
                      ? new Date(task.last_run_at).toLocaleString("zh-CN")
                      : "—"}
                  </td>
                  <td className="cell-dim">{task.schedule_preset}</td>
                  <td>
                    <button
                      className="btn btn-outline btn-sm"
                      onClick={() => triggerMutation.mutate(task.id)}
                      disabled={triggerMutation.isPending}
                      aria-label={`立即运行 ${task.name}`}
                    >
                      <Play size={12} />
                      立即运行
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
