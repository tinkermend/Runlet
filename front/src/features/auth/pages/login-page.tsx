import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Zap, AlertCircle } from "lucide-react";
import { useAuth } from "../../../app/providers/auth-provider";
import { ApiError } from "../../../lib/http/client";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await fetch("/api/console/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        credentials: "include",
      });
      if (!resp.ok) {
        setError("用户名或密码错误");
        return;
      }
      await login();
      navigate("/dashboard", { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setError("用户名或密码错误");
        return;
      }
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100dvh",
      background: "var(--bg)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
    }}>
      {/* Background glow */}
      <div style={{
        position: "fixed",
        top: "30%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: 600,
        height: 400,
        background: "radial-gradient(ellipse, rgba(34,197,94,.06) 0%, transparent 70%)",
        pointerEvents: "none",
      }} />

      <div style={{
        width: "100%",
        maxWidth: 380,
        position: "relative",
      }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 48,
            height: 48,
            background: "var(--accent)",
            borderRadius: 12,
            marginBottom: 16,
            boxShadow: "0 0 24px var(--accent-glow)",
          }}>
            <Zap size={22} color="#020617" strokeWidth={2.5} />
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--fg)", letterSpacing: "-0.3px" }}>
            登录 Runlet 平台
          </h1>
          <p style={{ fontSize: 13, color: "var(--fg-dim)", marginTop: 6 }}>
            自动化检查执行平台
          </p>
        </div>

        {/* Card */}
        <div style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          padding: "28px 28px 24px",
          boxShadow: "var(--shadow-lg)",
        }}>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="username" className="form-label">用户名</label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                className="form-input"
                placeholder="输入用户名"
              />
            </div>

            <div className="form-group">
              <label htmlFor="password" className="form-label">密码</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="form-input"
                placeholder="输入密码"
              />
            </div>

            {error && (
              <div className="form-alert" role="alert" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <AlertCircle size={14} />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary btn-full btn-lg"
              style={{ marginTop: 4 }}
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
