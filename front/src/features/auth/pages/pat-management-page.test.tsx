import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { PatManagementPage } from "./pat-management-page";

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: () => "application/json",
    },
    json: async () => payload,
  };
}

function emptyResponse(status = 204) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: () => null,
    },
    json: async () => {
      throw new Error("no content");
    },
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <PatManagementPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

it("creates PAT with 3-day ttl and shows token once", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse([]))
    .mockResolvedValueOnce(
      jsonResponse({
        id: "11111111-1111-1111-1111-111111111111",
        name: "my-skill",
        token_prefix: "rpat_xxx",
        allowed_channels: ["skills"],
        allowed_actions: null,
        allowed_system_ids: null,
        issued_at: "2026-04-04T10:00:00Z",
        expires_at: "2026-04-07T10:00:00Z",
        last_used_at: null,
        revoked_at: null,
        token: "rpat_xxx-secret",
      }, 201),
    )
    .mockResolvedValueOnce(
      jsonResponse([
        {
          id: "11111111-1111-1111-1111-111111111111",
          name: "my-skill",
          token_prefix: "rpat_xxx",
          allowed_channels: ["skills"],
          allowed_actions: null,
          allowed_system_ids: null,
          issued_at: "2026-04-04T10:00:00Z",
          expires_at: "2026-04-07T10:00:00Z",
          last_used_at: null,
          revoked_at: null,
        },
      ]),
    );
  global.fetch = fetchMock;

  renderPage();
  await screen.findByText("暂无 PAT，创建后可用于 Skills 对话调用。");

  await userEvent.type(screen.getByLabelText("Token 名称"), "my-skill");
  await userEvent.selectOptions(screen.getByLabelText("有效期"), "3");
  await userEvent.click(screen.getByRole("button", { name: "创建 PAT" }));

  expect(await screen.findByText("rpat_xxx-secret")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/platform-auth/pats",
    expect.objectContaining({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({ name: "my-skill", expires_in_days: 3 }),
    }),
  );
});

it("revokes PAT", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      jsonResponse([
        {
          id: "11111111-1111-1111-1111-111111111111",
          name: "to-revoke",
          token_prefix: "rpat_old",
          allowed_channels: ["skills"],
          allowed_actions: null,
          allowed_system_ids: null,
          issued_at: "2026-04-04T10:00:00Z",
          expires_at: "2026-04-07T10:00:00Z",
          last_used_at: null,
          revoked_at: null,
        },
      ]),
    )
    .mockResolvedValueOnce(emptyResponse(204))
    .mockResolvedValueOnce(
      jsonResponse([
        {
          id: "11111111-1111-1111-1111-111111111111",
          name: "to-revoke",
          token_prefix: "rpat_old",
          allowed_channels: ["skills"],
          allowed_actions: null,
          allowed_system_ids: null,
          issued_at: "2026-04-04T10:00:00Z",
          expires_at: "2026-04-07T10:00:00Z",
          last_used_at: null,
          revoked_at: "2026-04-05T10:00:00Z",
        },
      ]),
    );
  global.fetch = fetchMock;

  renderPage();
  await screen.findByText("to-revoke");

  await userEvent.click(screen.getByRole("button", { name: "吊销" }));

  await waitFor(() => {
    expect(screen.getByText("已吊销")).toBeInTheDocument();
  });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/platform-auth/pats/11111111-1111-1111-1111-111111111111:revoke",
    expect.objectContaining({
      method: "POST",
      credentials: "include",
    }),
  );
});
