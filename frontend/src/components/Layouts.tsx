import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { NotificationBell } from "./NotificationBell";

export interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

function Account() {
  const { user, signOut } = useAuth();
  return (
    <div className="text-[13px]">
      {user?.name}
      <small className="block font-mono text-xs text-fg-3">{user?.id}</small>
      <button onClick={signOut} className="mt-1 text-xs text-fg-2 underline underline-offset-2 hover:text-fg">
        Sign out
      </button>
    </div>
  );
}

/** Technician and admin: a persistent sidebar for tools used all day. */
export function SideLayout({ nav }: { nav: NavItem[] }) {
  return (
    <div className="grid min-h-dvh grid-cols-[minmax(0,1fr)] items-start gap-2.5 p-2.5 lg:grid-cols-[196px_minmax(0,1fr)]">
      <nav className="card flex flex-wrap items-center gap-x-4 gap-y-2 px-2.5 py-2 lg:sticky lg:top-2.5 lg:flex-col lg:items-stretch lg:gap-[18px] lg:py-3.5">
        <div className="flex items-center justify-between gap-2.5 px-1.5 font-semibold tracking-tight">
          <span>I-ITSM</span>
          <NotificationBell />
        </div>
        <div className="flex flex-wrap gap-0.5 lg:flex-col">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-[9px] px-2.5 py-[7px] font-medium ${isActive ? "bg-paper text-on-paper" : "text-fg-2 hover:bg-raise hover:text-fg"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="ml-auto px-1.5 lg:ml-0 lg:mt-24">
          <Account />
        </div>
      </nav>
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}

/** Employee: an occasional visitor gets a simple top bar and roomy content. */
export function TopLayout({ nav }: { nav: NavItem[] }) {
  return (
    <div className="mx-auto min-h-dvh max-w-[960px] px-4 py-5 sm:px-6">
      <header className="mb-8 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex items-center gap-2.5 font-semibold tracking-tight">
          <span>I-ITSM</span>
          <NotificationBell />
        </div>
        <nav className="flex flex-wrap gap-4">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `font-medium ${isActive ? "text-lime" : "text-fg-2 hover:text-fg"}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto text-right">
          <Account />
        </div>
      </header>
      <Outlet />
    </div>
  );
}
