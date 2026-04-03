import { Navigate, Outlet } from "react-router-dom";

// Simple auth check - will be replaced by auth provider in Task 3
function isAuthenticated(): boolean {
  return document.cookie.includes("console_session=");
}

export function ProtectedRoute() {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
