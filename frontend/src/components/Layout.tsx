import { Link, useLocation } from "react-router-dom";
import { FolderOpen, LayoutGrid, Settings, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Projects", icon: FolderOpen },
  { href: "/runs", label: "All runs", icon: LayoutGrid },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className="w-56 shrink-0 flex flex-col fixed inset-y-0 left-0 z-20"
        style={{ background: "hsl(var(--sidebar-bg))", borderRight: "1px solid hsl(var(--sidebar-border))" }}
      >
        {/* Logo */}
        <div className="px-4 py-5 mb-2">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="h-7 w-7 rounded-lg bg-blue-500 flex items-center justify-center shrink-0">
              <span className="text-white font-bold text-xs">GS</span>
            </div>
            <span className="font-semibold text-white text-sm tracking-tight">GrainSift</span>
          </Link>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 space-y-0.5">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/"
                ? pathname === "/" || pathname.startsWith("/projects")
                : href === "/runs"
                ? pathname === "/runs"
                : pathname.startsWith(href);
            return (
              <Link key={href} to={href} className={cn("sidebar-item", active && "active")}>
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-4 py-4 border-t" style={{ borderColor: "hsl(var(--sidebar-border))" }}>
          <p className="text-xs" style={{ color: "hsl(var(--sidebar-fg))" }}>v0.1.0</p>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col ml-56">
        <main className="flex-1 p-8">{children}</main>
      </div>
    </div>
  );
}

/* Breadcrumb for run sub-pages */
export function PageHeader({
  title,
  subtitle,
  action,
  breadcrumb,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  breadcrumb?: { label: string; href: string }[];
}) {
  return (
    <div className="mb-7">
      {breadcrumb && breadcrumb.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
          {breadcrumb.map((b, i) => (
            <span key={b.href} className="flex items-center gap-1.5">
              {i > 0 && <ChevronRight className="h-3 w-3" />}
              <Link to={b.href} className="hover:text-foreground transition-colors">{b.label}</Link>
            </span>
          ))}
          <ChevronRight className="h-3 w-3" />
          <span className="text-foreground">{title}</span>
        </div>
      )}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  );
}
