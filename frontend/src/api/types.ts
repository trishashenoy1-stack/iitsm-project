// Mirrors domain/enums.py. This file is the contract to agree with P2.
export type Role = "EMPLOYEE" | "TECHNICIAN" | "ADMIN";
export type Priority = "P1" | "P2" | "P3" | "P4";
export type Level = "LOW" | "MEDIUM" | "HIGH";
export type Status =
  | "NEW"
  | "CLASSIFIED"
  | "ASSIGNED"
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  | "AWAITING_INFO"
  | "RESOLVED"
  | "VERIFIED"
  | "CLOSED"
  | "REOPENED";

// Action names match the methods on domain/incident.py.
export type IncidentAction =
  | "acknowledge"
  | "start_work"
  | "request_info"
  | "provide_info"
  | "resolve"
  | "verify"
  | "reject_resolution"
  | "close";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
}

export interface PersonRef {
  id: string;
  name: string;
}

export interface Session {
  token: string;
  user: User;
}

export interface Sla {
  responseDeadline: string;
  resolutionDeadline: string;
  resolutionTargetSeconds: number;
  isPaused: boolean;
  respondedAt: string | null;
  resolvedAt: string | null;
  /** Seconds left at the moment the clock stopped. Null while it is running. */
  frozenRemainingSeconds: number | null;
}

export interface HistoryEntry {
  at: string;
  actorId: string;
  action: string;
  description: string;
  previousStatus: Status | null;
  newStatus: Status | null;
}

export interface PossibleDuplicate {
  id: string;
  description: string;
  similarity: number;
}

/** A resolved incident whose fix may apply here (P4's kNN over resolved incidents). */
export interface ResolutionSuggestion {
  incidentId: string;
  similarity: number;
  category: string | null;
  resolution: string;
}

/** Open incidents P4's duplicate detector linked together, for one service. */
export interface IncidentCluster {
  serviceId: string;
  service: string;
  incidents: { id: string; description: string; status: Status; priority: Priority }[];
}

export interface Feedback {
  rating: number;
  comment: string;
}

export interface Service {
  id: string;
  name: string;
}

export interface NewIncident {
  description: string;
  serviceId: string;
  category: string | null;
  impact: Level;
  urgency: Level;
  affectedUsers: number;
}

export interface Incident {
  id: string;
  description: string;
  status: Status;
  priority: Priority;
  category: string;
  service: string;
  impact: Level;
  urgency: Level;
  affectedUsers: number;
  reporter: PersonRef;
  technician: PersonRef | null;
  createdAt: string;
  sla: Sla;
  resolution: string | null;
  /** The technician's open question. Needs P1/P2 support: request_info() has no text today. */
  infoRequest: string | null;
  feedback: Feedback | null;
  /** The API must leave out internal technician notes for employees. */
  history: HistoryEntry[];
  possibleDuplicates: PossibleDuplicate[];
}

export interface AppNotification {
  id: string;
  incidentId: string | null;
  message: string;
  createdAt: string;
  read: boolean;
}

export interface IncidentFilters {
  id?: string;
  status?: string;
  priority?: string;
  category?: string;
  service?: string;
  technician?: string;
  sla?: string;
  from?: string;
  to?: string;
}

export interface AdminUser extends User {
  active: boolean;
  /** Place in the escalation chain: 1 team lead, 2 system admin, 3 IT manager. */
  escalationLevel: number | null;
  /** Write-only: the starting password an admin sets when creating an account. */
  password?: string;
}

export interface TechnicianProfile {
  id: string;
  name: string;
  skills: string[];
  experienceYears: number;
  maxWorkload: number;
  available: boolean;
  activeCount: number;
}

export interface AdminService extends Service {
  criticality: number;
  active: boolean;
}

export interface SlaPolicy {
  priority: Priority;
  responseMinutes: number;
  resolutionMinutes: number;
}

export interface AdminCategory {
  name: string;
  description: string;
  active: boolean;
}

export type AssignmentStrategyId = "SKILL" | "LOAD" | "ROUND_ROBIN";

export interface AssignmentSettings {
  current: AssignmentStrategyId;
  options: { id: AssignmentStrategyId; label: string; description: string }[];
}

export interface AuditEntry extends HistoryEntry {
  incidentId: string;
}

export interface SlaViolation {
  incidentId: string;
  description: string;
  priority: Priority;
  technicianId: string | null;
  type: "Response" | "Resolution";
  deadline: string;
  overBySeconds: number;
  status: Status;
}

export interface ReportOverview {
  total: number;
  open: number;
  critical: number;
  resolved: number;
  slaViolations: number;
  technicianWorkload: { id: string; name: string; active: number; max: number }[];
  serviceAnalysis: { service: string; incidents: number }[];
  dailyCreated: { date: string; incidents: number }[];
}

export interface Workload {
  active: number;
  max: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}
