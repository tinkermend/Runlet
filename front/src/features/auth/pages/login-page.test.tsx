import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../../app/providers/auth-provider";
import { LoginPage } from "./login-page";

function renderLoginPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

it("renders login form", () => {
  renderLoginPage();
  expect(screen.getByRole("heading", { name: "登录 Runlet 平台" })).toBeInTheDocument();
  expect(screen.getByLabelText("用户名")).toBeInTheDocument();
  expect(screen.getByLabelText("密码")).toBeInTheDocument();
});

it("shows error on failed login", async () => {
  global.fetch = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Not authenticated" }),
    })
    .mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Invalid credentials" }),
    });
  renderLoginPage();
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "wrong");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误");
});

it("reloads /me after successful login", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Not authenticated" }),
    })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ username: "admin" }),
    });
  global.fetch = fetchMock;

  renderLoginPage();
  await userEvent.type(screen.getByLabelText("用户名"), "admin");
  await userEvent.type(screen.getByLabelText("密码"), "admin");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));

  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    "/api/console/auth/me",
    expect.objectContaining({
      credentials: "include",
    }),
  );
});
