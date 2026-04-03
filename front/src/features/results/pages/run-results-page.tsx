import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { apiFetch } from "../../../lib/http/client";
import type { PaginatedResults } from "../../../lib/http/types";

function statusBadgeClass(status: string) {
  switch (status) {
    case "passed":  return "badge badge-success";
    case "failed":  return "badge badge-danger";
    case "error":   return "badge badge-warning";
    case "running": return "badge badge-info";
    default:        return "badge badge-neutral";
  }
}

const STATUS_LABELS: Record<string, string> = {
  passed: "通过", failed: "失败", error: "异常", running: "运行中",
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function RunResultsPage() {
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["results", page],
    queryFn: () =>
      apiFetch<PaginatedResults>(`/api/console/results/?page=${page}&page_size=${pageSize}`),
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">运行结果</h1>
          <p className="page-subtitle">查看所有任务的历史执行记录</p>
        </div>
      </div>

      <div className="table-wrap" style={{ marginBottom: 16 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>任务名称</th>
              <th>系统</th>
              <th>状态</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              [1,2,3,4,5].map(i => (
                <tr key={i}>
                  {[1,2,3,4,5].map(j => (
                    <td key={j}><div className="skeleton" style={{ height: 13, width: "80%" }} /></td>
                  ))}
                </tr>
              ))
            ) : !data || data.items.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <div className="empty-state">
                    <div className="empty-state-icon"><Activity size={22} /></div>
                    <div className="empty-state-title">暂无运行记录</div>
                  </div>
                </td>
              </tr>
            ) : (
              data.items.map((item) => (
                <tr key={item.id}>
                  <td className="cell-dim">{new Date(item.created_at).toLocaleString("zh-CN")}</td>
                  <td style={{ fontWeight: 500 }}>{item.task_name}</td>
                  <td className="cell-muted">{item.system_name}</td>
                  <td>
                    <span className={statusBadgeClass(item.status)}>
                      {STATUS_LABELS[item.status] ?? item.status}
                    </span>
                  </td>
                  <td className="cell-dim">{formatDuration(item.duration_ms)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {data && (
        <div style={{ display: "flex", alignItems: "center", gap: 12, justifyContent: "flex-end" }}>
          <span className="text-dim text-sm">
            共 {data.total} 条 · 第 {page} / {totalPages} 页
          </span>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            上一页
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
