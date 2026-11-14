import type {
  AdminCategory,
  AdminService,
  AdminUser,
  ApiErrorBody,
  AppNotification,
  AssignmentSettings,
  AssignmentStrategyId,
  AuditEntry,
  Incident,
  IncidentAction,
  IncidentFilters,
  NewIncident,
  ReportOverview,
  Service,
  Session,
  SlaPolicy,
  SlaViolation,
  TechnicianProfile,
  User,
  Workload,
} from "./types";

const TOKEN_KEY = "iitsm.token";

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get();
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, "NETWORK_FAILURE", "Can't reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(
      response.status,
      body?.code ?? "UNKNOWN",
      body?.message ?? "Something went wrong on the server. Try again.",
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

function queryString(filters: IncidentFilters = {}) {
  const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value) as [string, string][]);
  return params.size ? `?${params}` : "";
}

export const api = {
  login: (email: string, password: string) => post<Session>("/auth/login", { email, password }),
  register: (name: string, email: string, password: string) =>
    post<Session>("/auth/register", { name, email, password }),
  me: () => request<User>("/auth/me"),

  listIncidents: (filters?: IncidentFilters) => request<Incident[]>(`/incidents${queryString(filters)}`),
  assignIncident: (id: string, technicianId: string) => post<Incident>(`/incidents/${id}/assign`, { technicianId }),
  myWorkload: () => request<Workload>("/me/workload"),

  admin: {
    listUsers: () => request<AdminUser[]>("/admin/users"),
    createUser: (user: Partial<AdminUser>) => post<AdminUser>("/admin/users", user),
    updateUser: (id: string, changes: Partial<AdminUser>) => patch<AdminUser>(`/admin/users/${id}`, changes),
    listTechnicians: () => request<TechnicianProfile[]>("/admin/technicians"),
    updateTechnician: (id: string, changes: Partial<TechnicianProfile>) => patch<TechnicianProfile>(`/admin/technicians/${id}`, changes),
    listServices: () => request<AdminService[]>("/admin/services"),
    createService: (service: Partial<AdminService>) => post<AdminService>("/admin/services", service),
    updateService: (id: string, changes: Partial<AdminService>) => patch<AdminService>(`/admin/services/${id}`, changes),
    listSlaPolicies: () => request<SlaPolicy[]>("/admin/sla-policies"),
    updateSlaPolicy: (priority: string, changes: Partial<SlaPolicy>) => patch<SlaPolicy>(`/admin/sla-policies/${priority}`, changes),
    listCategories: () => request<AdminCategory[]>("/admin/categories"),
    createCategory: (category: Partial<AdminCategory>) => post<AdminCategory>("/admin/categories", category),
    updateCategory: (name: string, changes: Partial<AdminCategory>) => patch<AdminCategory>(`/admin/categories/${name}`, changes),
    assignment: () => request<AssignmentSettings>("/admin/assignment-strategy"),
    setAssignment: (current: AssignmentStrategyId) => patch<AssignmentSettings>("/admin/assignment-strategy", { current }),
    audit: () => request<AuditEntry[]>("/admin/audit-log"),
    violations: () => request<SlaViolation[]>("/admin/sla-violations"),
    overview: () => request<ReportOverview>("/admin/reports/overview"),
  },

  getIncident: (id: string) => request<Incident>(`/incidents/${id}`),
  performAction: (id: string, action: IncidentAction, message?: string) =>
    post<Incident>(`/incidents/${id}/actions/${action}`, { message }),
  addNote: (id: string, text: string) => post<Incident>(`/incidents/${id}/notes`, { text }),
  createIncident: (incident: NewIncident) => post<Incident>("/incidents", incident),
  addInformation: (id: string, text: string) => post<Incident>(`/incidents/${id}/information`, { text }),
  submitFeedback: (id: string, rating: number, comment: string) =>
    post<Incident>(`/incidents/${id}/feedback`, { rating, comment }),
  listServices: () => request<Service[]>("/services"),
  listCategories: () => request<string[]>("/categories"),

  listNotifications: () => request<AppNotification[]>("/notifications"),
  markNotificationsRead: () => post<void>("/notifications/read-all"),
};
