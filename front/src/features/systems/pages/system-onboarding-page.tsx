import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../../lib/http/client";

type AuthType = "none" | "username_password" | "cookie";

const inputStyle = {
  width: "100%",
  padding: "8px 12px",
  background: "#1E293B",
  border: "1px solid #334155",
  borderRadius: 6,
  color: "#F8FAFC",
  fontSize: 14,
  boxSizing: "border-box" as const,
};

const labelStyle = {
  display: "block",
  color: "#94A3B8",
  fontSize: 13,
  marginBottom: 6,
};

export function SystemOnboardingPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [authType, setAuthType] = useState<AuthType>("none");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch("/api/console/portal/systems", {
        method: "POST",
        body: JSON.stringify({
          name,
          base_url: baseUrl,
          auth_type: authType,
          ...(authType === "username_password" ? { username, password } : {}),
          notes: notes || undefined,
        }),
      });
      navigate("/systems");
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h1 style={{ color: "#F8FAFC", fontSize: 24, fontWeight: 700, marginBottom: 24 }}>接入新系统</h1>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <label style={labelStyle}>系统名称 *</label>
          <input
            style={inputStyle}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例：OA 系统"
            required
          />
        </div>

        <div>
          <label style={labelStyle}>系统地址 *</label>
          <input
            style={inputStyle}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://example.com"
            required
          />
        </div>

        <div>
          <label style={labelStyle}>登录方式</label>
          <select
            style={inputStyle}
            value={authType}
            onChange={(e) => setAuthType(e.target.value as AuthType)}
          >
            <option value="none">无需登录</option>
            <option value="username_password">用户名 / 密码</option>
            <option value="cookie">Cookie</option>
          </select>
        </div>

        {authType === "username_password" && (
          <>
            <div>
              <label style={labelStyle}>用户名</label>
              <input
                style={inputStyle}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div>
              <label style={labelStyle}>密码</label>
              <input
                type="password"
                style={inputStyle}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
            </div>
          </>
        )}

        <div>
          <label style={labelStyle}>备注</label>
          <textarea
            style={{ ...inputStyle, resize: "vertical", minHeight: 72 }}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="可选"
          />
        </div>

        {error && (
          <div role="alert" style={{ color: "#EF4444", fontSize: 14 }}>{error}</div>
        )}

        <div style={{ display: "flex", gap: 12 }}>
          <button
            type="submit"
            disabled={submitting}
            style={{
              padding: "10px 24px",
              background: "#22C55E",
              color: "#020617",
              border: "none",
              borderRadius: 6,
              fontSize: 14,
              fontWeight: 600,
              cursor: submitting ? "not-allowed" : "pointer",
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? "提交中..." : "确认接入"}
          </button>
          <button
            type="button"
            onClick={() => navigate("/systems")}
            style={{
              padding: "10px 24px",
              background: "transparent",
              color: "#94A3B8",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            取消
          </button>
        </div>
      </form>
    </div>
  );
}
