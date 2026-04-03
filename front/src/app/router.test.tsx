import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Navigate } from "react-router-dom";
import { ProtectedRoute } from "./routes/protected-route";

// Minimal login page stub matching the real one
function LoginPage() {
  return <h1>登录 Runlet 平台</h1>;
}

it("redirects anonymous users to /login", async () => {
  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "登录 Runlet 平台" }),
  ).toBeInTheDocument();
});
