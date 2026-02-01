import React from "react";
import { Outlet, NavLink } from "react-router-dom";
import { Cpu, FileText, Database, Activity } from "lucide-react";
import { cn } from "@/lib/utils"; // Hàm utility của shadcn

// Component con hiển thị từng link trong sidebar
const SidebarItem = ({ to, icon: Icon, label }) => (
  <NavLink
    to={to}
    className={({ isActive }) =>
      cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all hover:text-primary",
        isActive
          ? "bg-muted text-primary"
          : "text-muted-foreground hover:bg-muted/50",
      )
    }
  >
    <Icon className="h-4 w-4" />
    {label}
  </NavLink>
);

const RootLayout = () => {
  return (
    <div className="grid min-h-screen w-full md:grid-cols-[220px_1fr] lg:grid-cols-[280px_1fr]">
      {/* Sidebar (Cột bên trái) */}
      <div className="hidden border-r bg-muted/40 md:block">
        <div className="flex h-full max-h-screen flex-col gap-2">
          {/* Logo / Tiêu đề */}
          <div className="flex h-14 items-center border-b px-4 lg:h-[60px] lg:px-6">
            <div className="flex items-center gap-2 font-semibold">
              <Activity className="h-6 w-6" />
              <span className="">Auto-scale Demo</span>
            </div>
          </div>

          {/* Menu Navigation */}
          <div className="flex-1">
            <nav className="grid items-start px-2 text-sm font-medium lg:px-4 mt-4">
              <SidebarItem to="/prime" icon={Cpu} label="Số nguyên tố" />
              <SidebarItem to="/text" icon={FileText} label="Xử lý text" />
              <SidebarItem to="/io" icon={Database} label="Đợi I/O" />
            </nav>
          </div>

          {/* Footer Sidebar */}
          <div className="mt-auto p-4">
            <div className="text-xs text-muted-foreground text-center">
              Thesis Project 2026
            </div>
          </div>
        </div>
      </div>

      {/* Main Content (Phần nội dung bên phải) */}
      <div className="flex flex-col">
        {/* Header Mobile (Có thể thêm nút toggle sidebar ở đây) */}
        <header className="flex h-14 items-center gap-4 border-b bg-muted/40 px-6 lg:h-[60px]">
          <h1 className="text-lg font-semibold">Dashboard Monitor</h1>
        </header>

        {/* Nơi nội dung thay đổi sẽ hiển thị */}
        <main className="flex flex-1 flex-col gap-4 p-4 lg:gap-6 lg:p-6">
          <div className="rounded-lg border border-dashed shadow-sm p-4 min-h-[500px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

export default RootLayout;
