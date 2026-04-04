import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../providers/auth-provider";

export function ProtectedRoute() {
  const { isAuthenticated, isLoadingAuth } = useAuth();
  if (isLoadingAuth) {
    return null;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
