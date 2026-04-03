import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../../lib/http/client";
import type { PaginatedResults } from "../../../lib/http/types";

const STATUS_COLORS: Record<string, string> = {
  passed: "#22C55E",
  failed: "#EF4444",
  error: "#F59E0B",
  running: "#3B82F6",
};

const STATUS_LABELS: Record<string, string> = {
  passed: "通过",
  failed: "失败",
  error: "异常",
  running: "运行中",
};

function formatDuration(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function RunResultsPage() {
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const { data, isLoading, error } = useQuery({
    queryKey: ["results", page],
    queryFn: () =>
      apiFetch<PaginatedResults>(`/api/console/results/?page=${page}&page_size=${pageSize}`),
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 1;

  return (
    <div>
      <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, marginBottom: 24 }}>运行结果</h1>

      {isLoading && <div style={{ color: "#94A3B8" }}>加载中...</div>}
      {error && <div style={{ color: "#EF4444" }}>加载失败，请刷新重试</div>}

      {data && (
        <>
          <div style={{
            background: "#0F172A",
            border: "1px solid #334155",
            borderRadius: 8,
            overflow: "hidden",
            marginBottom: 16,
          }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #334155" }}>
                  {["时间", "任务名称", "系统", "状态", "耗时"].map((col) => (
                    <th key={col} style={{
                      padding: "10px 16px",
                      color: "#64748B",
                      fontSize: 12,
                      fontWeight: 600,
                      textAlign: "left",
                    }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={5} style={{ padding: "24px 16px", color: "#64748B", fontSize: 14, textAlign: "center" }}>
                      暂无运行记录
                    </td>
                  </tr>
                ) : (
                  data.items.map((item) => (
                    <tr key={item.id} style={{ borderBottom: "1px solid #1E293B" }}>
                      <td style={{ padding: "12px 16px", color: "#64748B", fontSize: 13 }}>
                        {new Date(item.created_at).toLocaleString("zh-CN")}
                      </td>
                      <td style={{ padding: "12px 16px", color: "#F8FAFC", fontSize: 14 }}>
                        {item.task_name}
                      </td>
                      <td style={{ padding: "12px 16px", color: "#94A3B8", fontSize: 13 }}>
                        {item.system_name}
                      </td>
                      <td style={{ padding: "12px 16px" }}>
                        <span style={{
                          fontSize: 12,
                          padding: "2px 8px",
                          borderRadius: 4,
                          background: `${STATUS_COLORS[item.status] ?? "#64748B"}20`,
                          color: STATUS_COLORS[item.status] ?? "#64748B",
                        }}>
                          {STATUS_LABELS[item.status] ?? item.status}
                        </span>
                      </td>
                      <td style={{ padding: "12px 16px", color: "#94A3B8", fontSize: 13 }}>
                        {formatDuration(item.duration_ms)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, justifyContent: "flex-end" }}>
            <span style={{ color: "#64748B", fontSize: 13 }}>
              共 {data.total} 条，第 {page} / {totalPages} 页
            </span>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              style={{
                padding: "6px 14px",
                background: "transparent",
                color: page <= 1 ? "#334155" : "#94A3B8",
                border: `1px solid ${page <= 1 ? "#1E293B" : "#334155"}`,
                borderRadius: 4,
                fontSize: 13,
                cursor: page <= 1 ? "not-allowed" : "pointer",
              }}
            >
              上一页
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              style={{
                padding: "6px 14px",
                background: "transparent",
                color: page >= totalPages ? "#334155" : "#94A3B8",
                border: `1px solid ${page >= totalPages ? "#1E293B" : "#334155"}`,
                borderRadius: 4,
                fontSize: 13,
                cursor: page >= totalPages ? "not-allowed" : "pointer",
              }}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </div>
  );
}
