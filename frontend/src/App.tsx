import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import type { Role } from "./api/types";
import { homeFor, useAuth } from "./auth/AuthContext";
import { SideLayout, TopLayout, type NavItem } from "./components/Layouts";
import { AdminIncidentDetail } from "./pages/admin/AdminIncidentDetail";
import { AdminIncidents } from "./pages/admin/AdminIncidents";
import { AssignmentPage } from "./pages/admin/AssignmentPage";
import { AuditLog } from "./pages/admin/AuditLog";
import { CategoriesPage, ServicesPage, SlaPoliciesPage, TechniciansPage, UsersPage } from "./pages/admin/Management";
import { Overview } from "./pages/admin/Overview";
import { SlaViolations } from "./pages/admin/SlaViolations";
import { EmployeeIncident } from "./pages/employee/EmployeeIncident";
import { MyIncidents } from "./pages/employee/MyIncidents";
import { ReportIncident } from "./pages/employee/ReportIncident";
import { Login } from "./pages/Login";
import { QueuePage } from "./pages/technician/QueuePage";
import { Workload } from "./pages/technician/Workload";

const TECHNICIAN_NAV: NavItem[] = [
  { to: "/technician/queue", label: "Queue" },
  { to: "/technician/workload", label: "Workload" },
];

const ADMIN_NAV: NavItem[] = [
  { to: "/admin", label: "Overview", end: true },
  { to: "/admin/incidents", label: "Incidents" },
  { to: "/admin/sla-violations", label: "SLA violations" },
  { to: "/admin/audit-log", label: "Audit log" },
  { to: "/admin/users", label: "Users" },
  { to: "/admin/technicians", label: "Technicians" },
  { to: "/admin/services", label: "Services" },
  { to: "/admin/sla-policies", label: "SLA policies" },
  { to: "/admin/categories", label: "Categories" },
  { to: "/admin/assignment", label: "Assignment" },
];

const EMPLOYEE_NAV: NavItem[] = [
  { to: "/employee", label: "My incidents", end: true },
  { to: "/employee/report", label: "Report an incident" },
];

function RequireRole({ role }: { role: Role }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={homeFor(user.role)} replace />;
  return <Outlet />;
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <Navigate to={user ? homeFor(user.role) : "/login"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<RequireRole role="EMPLOYEE" />}>
        <Route element={<TopLayout nav={EMPLOYEE_NAV} />}>
          <Route path="/employee" element={<MyIncidents />} />
          <Route path="/employee/report" element={<ReportIncident />} />
          <Route path="/employee/incidents/:id" element={<EmployeeIncident />} />
        </Route>
      </Route>

      <Route element={<RequireRole role="TECHNICIAN" />}>
        <Route element={<SideLayout nav={TECHNICIAN_NAV} />}>
          <Route path="/technician/queue" element={<QueuePage />} />
          <Route path="/technician/queue/:id" element={<QueuePage />} />
          <Route path="/technician/workload" element={<Workload />} />
        </Route>
      </Route>

      <Route element={<RequireRole role="ADMIN" />}>
        <Route element={<SideLayout nav={ADMIN_NAV} />}>
          <Route path="/admin" element={<Overview />} />
          <Route path="/admin/incidents" element={<AdminIncidents />} />
          <Route path="/admin/incidents/:id" element={<AdminIncidentDetail />} />
          <Route path="/admin/sla-violations" element={<SlaViolations />} />
          <Route path="/admin/audit-log" element={<AuditLog />} />
          <Route path="/admin/users" element={<UsersPage />} />
          <Route path="/admin/technicians" element={<TechniciansPage />} />
          <Route path="/admin/services" element={<ServicesPage />} />
          <Route path="/admin/sla-policies" element={<SlaPoliciesPage />} />
          <Route path="/admin/categories" element={<CategoriesPage />} />
          <Route path="/admin/assignment" element={<AssignmentPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Home />} />
    </Routes>
  );
}
