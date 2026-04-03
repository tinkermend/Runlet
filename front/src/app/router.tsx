import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./app-shell";
import { ProtectedRoute } from "./routes/protected-route";
import { LoginPage } from "../features/auth/pages/login-page";
import { DashboardPage } from "../features/dashboard/pages/dashboard-page";
import { SystemListPage } from "../features/systems/pages/system-list-page";
import { SystemOnboardingPage } from "../features/systems/pages/system-onboarding-page";
import { RunResultsPage } from "../features/results/pages/run-results-page";

// Placeholder pages - will be replaced in later tasks
function TasksPage() {
  return <h1>检查任务</h1>;
}
function AssetsPage() {
  return <h1>采集资产</h1>;
}

export const routes = [
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <Navigate to="/dashboard" replace /> },
          { path: "/dashboard", element: <DashboardPage /> },
          { path: "/tasks", element: <TasksPage /> },
          { path: "/assets", element: <AssetsPage /> },
          { path: "/systems", element: <SystemListPage /> },
          { path: "/systems/new", element: <SystemOnboardingPage /> },
          { path: "/results", element: <RunResultsPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
