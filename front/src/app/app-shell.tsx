import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  ClipboardCheck,
  Database,
  Server,
  Activity,
} from "lucide-react";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/tasks", label: "检查任务", icon: ClipboardCheck },
  { to: "/assets", label: "采集资产", icon: Database },
  { to: "/systems", label: "系统接入", icon: Server },
  { to: "/results", label: "运行结果", icon: Activity },
];

export function AppShell() {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#020617" }}>
      <nav
        style={{
          width: 240,
          background: "#0F172A",
          borderRight: "1px solid #334155",
          padding: "16px 0",
        }}
      >
        <div
          style={{
            padding: "0 16px 24px",
            color: "#F8FAFC",
            fontWeight: 700,
            fontSize: 18,
          }}
        >
          Runlet
        </div>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 16px",
              color: isActive ? "#22C55E" : "#94A3B8",
              textDecoration: "none",
              borderLeft: isActive
                ? "3px solid #22C55E"
                : "3px solid transparent",
              background: isActive ? "#1A1E2F" : "transparent",
            })}
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <main style={{ flex: 1, padding: 24, color: "#F8FAFC" }}>
        <Outlet />
      </main>
    </div>
  );
}
