import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  LayoutDashboard,
  Clock,
  FolderKanban,
  Users,
  LogOut,
  Shield,
  CalendarDays,
  Receipt,
} from "lucide-react";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const onLogout = async () => {
    await logout();
    navigate("/login");
  };

  const navItems = [
    { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, tid: "nav-dashboard" },
    { to: "/timesheet", label: "Timesheet", icon: Clock, tid: "nav-timesheet" },
    { to: "/calendar", label: "Calendar", icon: CalendarDays, tid: "nav-calendar" },
    { to: "/projects", label: "Projects", icon: FolderKanban, tid: "nav-projects" },
  ];
  if (user?.role === "admin") {
    navItems.push({ to: "/admin", label: "Admin", icon: Shield, tid: "nav-admin" });
    navItems.push({ to: "/invoices", label: "Invoices", icon: Receipt, tid: "nav-invoices" });
    navItems.push({ to: "/employees", label: "Employees", icon: Users, tid: "nav-employees" });
  }

  return (
    <div className="min-h-screen bg-white text-gray-900 flex">
      {/* Sidebar */}
      <aside className="w-64 border-r border-gray-200 flex-shrink-0 hidden md:flex flex-col" data-testid="sidebar">
        <div className="px-6 py-6 border-b border-gray-200">
          <div className="font-heading text-2xl font-black tracking-tighter leading-none">
            CHRONO<span className="text-[#34c759]">FLOW</span>
          </div>
          <div className="text-xs uppercase tracking-[0.2em] text-gray-500 mt-1">Time · Tracked</div>
        </div>
        <nav className="flex-1 py-4 px-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.tid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-md border ${
                  isActive
                    ? "bg-black text-white border-black"
                    : "border-transparent text-gray-700 hover:bg-gray-100 hover:text-black"
                }`
              }
            >
              <item.icon size={16} strokeWidth={2} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-gray-200 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.18em] text-gray-500">Signed in as</div>
          <div className="mt-1 text-sm font-semibold truncate" data-testid="current-user-name">{user?.name}</div>
          <div className="text-xs text-gray-500 truncate" data-testid="current-user-email">{user?.email}</div>
          <div className="mt-1 inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.18em] font-bold px-2 py-0.5 border border-gray-300 rounded-sm" data-testid="current-user-role">
            {user?.role}
          </div>
          <button
            onClick={onLogout}
            data-testid="logout-btn"
            className="mt-4 w-full inline-flex items-center justify-center gap-2 text-sm font-medium border border-gray-300 rounded-md px-3 py-2 hover:bg-black hover:text-white hover:border-black transition-colors"
          >
            <LogOut size={14} /> Logout
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="md:hidden fixed top-0 left-0 right-0 bg-white border-b border-gray-200 z-40 px-4 py-3 flex items-center justify-between">
        <div className="font-heading text-lg font-black">CHRONO<span className="text-[#34c759]">FLOW</span></div>
        <button onClick={onLogout} data-testid="logout-btn-mobile" className="text-xs uppercase tracking-wider border border-gray-300 px-3 py-1.5 rounded-md">Logout</button>
      </div>

      <main className="flex-1 min-w-0 md:pt-0 pt-14">
        <div className="px-6 md:px-10 py-8 max-w-[1400px] mx-auto">{children}</div>
        {/* Mobile bottom nav */}
        <div className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 flex z-40">
          {navItems.slice(0, 4).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex-1 flex flex-col items-center justify-center py-2 text-[10px] uppercase tracking-wider ${
                  isActive ? "text-black font-bold" : "text-gray-500"
                }`
              }
            >
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
        </div>
      </main>
    </div>
  );
}
