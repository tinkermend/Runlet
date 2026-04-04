import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./app-shell";
import { ProtectedRoute } from "./routes/protected-route";
import { LoginPage } from "../features/auth/pages/login-page";
import { DashboardPage } from "../features/dashboard/pages/dashboard-page";
import { SystemListPage } from "../features/systems/pages/system-list-page";
import { SystemOnboardingPage } from "../features/systems/pages/system-onboarding-page";
import { RunResultsPage } from "../features/results/pages/run-results-page";
import { TaskListPage } from "../features/tasks/pages/task-list-page";
import { TaskCreatePage } from "../features/tasks/pages/task-create-page";
import { TaskDetailPage } from "../features/tasks/pages/task-detail-page";
import { AssetBrowserPage } from "../features/assets/pages/asset-browser-page";
import { AssetDetailPage } from "../features/assets/pages/asset-detail-page";
import { PatManagementPage } from "../features/auth/pages/pat-management-page";

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
          { path: "/tasks", element: <TaskListPage /> },
          { path: "/tasks/new", element: <TaskCreatePage /> },
          { path: "/tasks/:id", element: <TaskDetailPage /> },
          { path: "/assets", element: <AssetBrowserPage /> },
          { path: "/assets/:id", element: <AssetDetailPage /> },
          { path: "/systems", element: <SystemListPage /> },
          { path: "/systems/new", element: <SystemOnboardingPage /> },
          { path: "/results", element: <RunResultsPage /> },
          { path: "/auth/pats", element: <PatManagementPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
