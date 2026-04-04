import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Shield, Trash2 } from "lucide-react";
import { ApiError, apiFetch } from "../../../lib/http/client";

interface PatListItem {
  id: string;
  name: string;
  token_prefix: string;
  issued_at: string;
  expires_at: string;
  revoked_at: string | null;
}

interface CreatePatResponse extends PatListItem {
  token: string;
}

const TTL_OPTIONS = [3, 7];

function formatTime(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString("zh-CN");
}

export function PatManagementPage() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [ttlDays, setTtlDays] = useState(3);
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["platform-pats"],
    queryFn: () => apiFetch<PatListItem[]>("/api/v1/platform-auth/pats"),
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      return apiFetch<CreatePatResponse>("/api/v1/platform-auth/pats", {
        method: "POST",
        body: JSON.stringify({
          name,
          expires_in_days: ttlDays,
        }),
      });
    },
    onSuccess: (payload) => {
      setIssuedToken(payload.token);
      setError(null);
      setName("");
      qc.invalidateQueries({ queryKey: ["platform-pats"] });
    },
    onError: (cause) => {
      if (cause instanceof ApiError) {
        setError(cause.message);
        return;
      }
      setError("创建 PAT 失败，请稍后重试");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: async (patId: string) => {
      return apiFetch<void>(`/api/v1/platform-auth/pats/${patId}:revoke`, {
        method: "POST",
      });
    },
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["platform-pats"] });
    },
    onError: (cause) => {
      if (cause instanceof ApiError) {
        setError(cause.message);
        return;
      }
      setError("吊销 PAT 失败，请稍后重试");
    },
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setError("请填写 PAT 名称");
      return;
    }
    await createMutation.mutateAsync();
  }

  const sortedItems = useMemo(() => {
    return [...(data ?? [])].sort((a, b) => {
      return Date.parse(b.issued_at) - Date.parse(a.issued_at);
    });
  }, [data]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">PAT 管理</h1>
          <p className="page-subtitle">为 Skills 创建 3 天或 7 天临时令牌，吊销后立即失效</p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-body">
          <form onSubmit={onSubmit} style={{ display: "grid", gridTemplateColumns: "1fr 120px auto", gap: 12 }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="pat-name">Token 名称</label>
              <input
                id="pat-name"
                className="form-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：ai-chat-temp"
                maxLength={128}
              />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="pat-ttl">有效期</label>
              <select
                id="pat-ttl"
                className="form-input"
                value={ttlDays}
                onChange={(event) => setTtlDays(Number(event.target.value))}
              >
                {TTL_OPTIONS.map((days) => (
                  <option key={days} value={days}>
                    {days} 天
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button
                className="btn btn-primary"
                type="submit"
                disabled={createMutation.isPending}
              >
                <KeyRound size={14} />
                创建 PAT
              </button>
            </div>
          </form>

          {error ? (
            <div className="form-alert" role="alert" style={{ marginTop: 12 }}>{error}</div>
          ) : null}
        </div>
      </div>

      {issuedToken ? (
        <div className="card" style={{ marginBottom: 16, borderColor: "rgba(245,158,11,.45)" }}>
          <div className="card-body">
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <Shield size={16} style={{ color: "var(--warning)" }} />
              <strong style={{ fontSize: 14 }}>请立即保存新 PAT（仅展示一次）</strong>
            </div>
            <code
              style={{
                display: "block",
                padding: "10px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--surface-2)",
                color: "var(--fg)",
                fontSize: 13,
                wordBreak: "break-all",
              }}
            >
              {issuedToken}
            </code>
          </div>
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>前缀</th>
              <th>签发时间</th>
              <th>过期时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="cell-muted" style={{ padding: 18 }}>
                  加载中...
                </td>
              </tr>
            ) : sortedItems.length === 0 ? (
              <tr>
                <td colSpan={6} className="cell-muted" style={{ padding: 18 }}>
                  暂无 PAT，创建后可用于 Skills 对话调用。
                </td>
              </tr>
            ) : (
              sortedItems.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td className="cell-dim">{item.token_prefix}</td>
                  <td className="cell-dim">{formatTime(item.issued_at)}</td>
                  <td className="cell-dim">{formatTime(item.expires_at)}</td>
                  <td>
                    {item.revoked_at ? (
                      <span className="badge badge-neutral">已吊销</span>
                    ) : (
                      <span className="badge badge-success">可用</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-danger btn-sm"
                      type="button"
                      onClick={() => revokeMutation.mutate(item.id)}
                      disabled={Boolean(item.revoked_at) || revokeMutation.isPending}
                    >
                      <Trash2 size={12} />
                      吊销
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
