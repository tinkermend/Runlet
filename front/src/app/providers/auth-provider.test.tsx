import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth-provider";

function AuthProbe() {
  const { username, isAuthenticated, isLoadingAuth } = useAuth();
  return (
    <div>
      <div data-testid="username">{username ?? "null"}</div>
      <div data-testid="authenticated">{String(isAuthenticated)}</div>
      <div data-testid="loading">{String(isLoadingAuth)}</div>
    </div>
  );
}

it("boots auth state from /api/console/auth/me", async () => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ username: "admin" }),
  });

  render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );

  await waitFor(() => {
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });
  expect(screen.getByTestId("authenticated")).toHaveTextContent("true");
  expect(screen.getByTestId("username")).toHaveTextContent("admin");
});

it("falls back to anonymous when /me returns 401", async () => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({ detail: "Not authenticated" }),
  });

  render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  );

  await waitFor(() => {
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
  });
  expect(screen.getByTestId("authenticated")).toHaveTextContent("false");
  expect(screen.getByTestId("username")).toHaveTextContent("null");
});
