import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Navigate } from "react-router-dom";
import { AuthProvider } from "./providers/auth-provider";
import { ProtectedRoute } from "./routes/protected-route";

// Minimal login page stub matching the real one
function LoginPage() {
  return <h1>登录 Runlet 平台</h1>;
}

it("redirects anonymous users to /login", async () => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({ detail: "Not authenticated" }),
  });

  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/dashboard" element={<Navigate to="/dashboard" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "登录 Runlet 平台" }),
  ).toBeInTheDocument();
});

it("allows authenticated users to open /auth/pats", async () => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ username: "admin" }),
  });

  render(
    <MemoryRouter initialEntries={["/auth/pats"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/auth/pats" element={<h1>PAT 管理</h1>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("heading", { name: "PAT 管理" })).toBeInTheDocument();
});
