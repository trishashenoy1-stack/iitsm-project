import { api } from "../../api/client";
import type { AdminCategory, AdminService, AdminUser, SlaPolicy, TechnicianProfile } from "../../api/types";
import { PriorityTag } from "../../components/IncidentBits";
import { OnOff, ResourcePage } from "../../components/ResourcePage";
import { PRIORITY_LABEL, titleCase } from "../../lib/format";

const a = api.admin;

export function UsersPage() {
  return (
    <ResourcePage<AdminUser>
      title="Users"
      description="Everyone who can sign in. New technicians appear under Technicians."
      noun="User"
      queryKey="users"
      load={a.listUsers}
      rowId={(u) => u.id}
      create={a.createUser}
      update={a.updateUser}
      toggle={{ key: "active", on: "Activate", off: "Deactivate" }}
      columns={[
        { header: "ID", cell: (u) => u.id, mono: true },
        { header: "Name", cell: (u) => u.name },
        { header: "Email", cell: (u) => u.email },
        { header: "Role", cell: (u) => titleCase(u.role) },
        { header: "Status", cell: (u) => <OnOff on={u.active} /> },
      ]}
      fields={[
        { key: "name", label: "Full name", required: true },
        { key: "email", label: "Email", kind: "email", required: true, createOnly: true },
        { key: "password", label: "Starting password", kind: "password", required: true, createOnly: true },
        {
          key: "role",
          label: "Role",
          kind: "select",
          createOnly: true,
          options: [
            { value: "EMPLOYEE", label: "Employee" },
            { value: "TECHNICIAN", label: "Technician" },
            { value: "ADMIN", label: "Admin" },
          ],
        },
      ]}
    />
  );
}

export function TechniciansPage() {
  return (
    <ResourcePage<TechnicianProfile>
      title="Technicians"
      description="Skills, experience and capacity drive automatic assignment."
      noun="Technician"
      queryKey="technicians"
      load={a.listTechnicians}
      rowId={(t) => t.id}
      update={a.updateTechnician}
      toggle={{ key: "available", on: "Mark available", off: "Mark unavailable" }}
      columns={[
        { header: "ID", cell: (t) => t.id, mono: true },
        { header: "Name", cell: (t) => t.name },
        { header: "Skills", cell: (t) => t.skills.map(titleCase).join(", ") || "None" },
        { header: "Experience", cell: (t) => `${t.experienceYears} yrs` },
        { header: "Workload", cell: (t) => `${t.activeCount} of ${t.maxWorkload}`, mono: true },
        { header: "Status", cell: (t) => <OnOff on={t.available} labels={["Available", "Unavailable"]} /> },
      ]}
      fields={[
        { key: "skills", label: "Skills, separated by commas", kind: "list" },
        { key: "experienceYears", label: "Experience in years", kind: "number", min: 0, required: true },
        { key: "maxWorkload", label: "Maximum workload", kind: "number", min: 1, required: true },
      ]}
    />
  );
}

export function ServicesPage() {
  return (
    <ResourcePage<AdminService>
      title="IT services"
      description="Business criticality from 1 to 5 feeds the priority calculation."
      noun="Service"
      queryKey="services"
      load={a.listServices}
      rowId={(s) => s.id}
      create={a.createService}
      update={a.updateService}
      toggle={{ key: "active", on: "Activate", off: "Deactivate" }}
      columns={[
        { header: "ID", cell: (s) => s.id, mono: true },
        { header: "Name", cell: (s) => s.name },
        { header: "Criticality", cell: (s) => `${s.criticality} of 5`, mono: true },
        { header: "Status", cell: (s) => <OnOff on={s.active} /> },
      ]}
      fields={[
        { key: "name", label: "Service name", required: true },
        { key: "criticality", label: "Criticality", kind: "number", min: 1, max: 5, required: true },
      ]}
    />
  );
}

export function SlaPoliciesPage() {
  return (
    <ResourcePage<SlaPolicy>
      title="SLA policies"
      description="Response and resolution targets for each priority."
      noun="Policy"
      queryKey="sla-policies"
      load={a.listSlaPolicies}
      rowId={(p) => p.priority}
      update={a.updateSlaPolicy}
      columns={[
        { header: "Priority", cell: (p) => <><PriorityTag priority={p.priority} /> <span className="ml-1">{PRIORITY_LABEL[p.priority]}</span></> },
        { header: "Response target", cell: (p) => `${p.responseMinutes} min`, mono: true },
        { header: "Resolution target", cell: (p) => `${p.resolutionMinutes} min`, mono: true },
      ]}
      fields={[
        { key: "responseMinutes", label: "Response target in minutes", kind: "number", min: 1, required: true },
        { key: "resolutionMinutes", label: "Resolution target in minutes", kind: "number", min: 1, required: true },
      ]}
    />
  );
}

export function CategoriesPage() {
  return (
    <ResourcePage<AdminCategory>
      title="Incident categories"
      description="Active categories appear on the employee report form."
      noun="Category"
      queryKey="categories"
      load={a.listCategories}
      rowId={(c) => c.name}
      create={a.createCategory}
      update={a.updateCategory}
      toggle={{ key: "active", on: "Activate", off: "Deactivate" }}
      columns={[
        { header: "Name", cell: (c) => titleCase(c.name) },
        { header: "Description", cell: (c) => c.description || <span className="text-fg-3">None</span> },
        { header: "Status", cell: (c) => <OnOff on={c.active} /> },
      ]}
      fields={[
        { key: "name", label: "Category name", required: true, createOnly: true },
        { key: "description", label: "Description" },
      ]}
    />
  );
}
