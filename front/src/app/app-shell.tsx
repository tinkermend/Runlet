import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  ClipboardCheck,
  Database,
  Server,
  Activity,
  Zap,
  KeyRound,
} from "lucide-react";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/tasks",     label: "检查任务",   icon: ClipboardCheck },
  { to: "/assets",    label: "采集资产",   icon: Database },
  { to: "/systems",   label: "系统接入",   icon: Server },
  { to: "/results",   label: "运行结果",   icon: Activity },
  { to: "/auth/pats", label: "PAT 管理",   icon: KeyRound },
];

export function AppShell() {
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-mark">
            <Zap size={14} color="#020617" strokeWidth={2.5} />
          </div>
          <span className="sidebar-logo-text">Runlet</span>
          <span className="sidebar-logo-badge">Console</span>
        </div>

        <div className="nav-section-label">导航</div>

        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            <Icon size={16} className="nav-icon" />
            {label}
          </NavLink>
        ))}
      </nav>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
