import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AssetBrowserPage } from "./asset-browser-page";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => [],
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <AssetBrowserPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

it("renders asset browser heading", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "采集资产" })).toBeInTheDocument();
});
