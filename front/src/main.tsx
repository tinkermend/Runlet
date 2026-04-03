import { StrictMode } from "react";
import "./index.css";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryProvider } from "./app/providers/query-provider";
import { AuthProvider } from "./app/providers/auth-provider";
import { router } from "./app/router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryProvider>
  </StrictMode>
);
