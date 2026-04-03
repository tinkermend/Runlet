import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../../../app/providers/auth-provider";
import { TaskCreatePage } from "./task-create-page";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Mock fetch to return wizard options
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      systems: [{ id: 1, name: "Test System", base_url: "https://example.com", status: "ready", task_count: 0 }],
      check_types: ["menu_completeness", "element_existence"],
    }),
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <AuthProvider>
          <TaskCreatePage />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

it("renders step 1 of wizard", async () => {
  renderPage();
  expect(await screen.findByText("选择检查目标")).toBeInTheDocument();
});
