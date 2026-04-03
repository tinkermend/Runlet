import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./app-shell";
import { ProtectedRoute } from "./routes/protected-route";
import { LoginPage } from "../features/auth/pages/login-page";

// Placeholder pages - will be replaced in later tasks
function DashboardPage() {
  return <h1>Dashboard</h1>;
}
function TasksPage() {
  return <h1>检查任务</h1>;
}
function AssetsPage() {
  return <h1>采集资产</h1>;
}
function SystemsPage() {
  return <h1>系统接入</h1>;
}
function ResultsPage() {
  return <h1>运行结果</h1>;
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
          { path: "/systems", element: <SystemsPage /> },
          { path: "/results", element: <ResultsPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
