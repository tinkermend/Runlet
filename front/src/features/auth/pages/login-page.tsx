import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../../app/providers/auth-provider";

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
      login(username);
      navigate("/dashboard", { replace: true });
    } catch {
      setError("网络错误，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#020617",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          background: "#0F172A",
          border: "1px solid #334155",
          borderRadius: 8,
          padding: 32,
          width: 360,
        }}
      >
        <h1
          style={{
            color: "#F8FAFC",
            fontSize: 20,
            fontWeight: 700,
            marginBottom: 24,
            textAlign: "center",
          }}
        >
          登录 Runlet 平台
        </h1>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="username"
              style={{ display: "block", color: "#94A3B8", fontSize: 14, marginBottom: 6 }}
            >
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              style={{
                width: "100%",
                padding: "10px 12px",
                background: "#1E293B",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "#F8FAFC",
                fontSize: 14,
                boxSizing: "border-box",
              }}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="password"
              style={{ display: "block", color: "#94A3B8", fontSize: 14, marginBottom: 6 }}
            >
              密码
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              style={{
                width: "100%",
                padding: "10px 12px",
                background: "#1E293B",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "#F8FAFC",
                fontSize: 14,
                boxSizing: "border-box",
              }}
            />
          </div>
          {error && (
            <div
              role="alert"
              style={{
                color: "#EF4444",
                fontSize: 14,
                marginBottom: 16,
                padding: "8px 12px",
                background: "rgba(239,68,68,0.1)",
                borderRadius: 4,
              }}
            >
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "10px 0",
              background: loading ? "#1A1E2F" : "#22C55E",
              color: loading ? "#64748B" : "#020617",
              border: "none",
              borderRadius: 6,
              fontSize: 14,
              fontWeight: 600,
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
