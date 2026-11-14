import type {
  AdminCategory,
  AdminService,
  AdminUser,
  AppNotification,
  AssignmentSettings,
  AssignmentStrategyId,
  AuditEntry,
  HistoryEntry,
  Incident,
  IncidentAction,
  IncidentCluster,
  IncidentFilters,
  Level,
  NewIncident,
  PersonRef,
  Priority,
  ReportOverview,
  ResolutionSuggestion,
  Role,
  SlaPolicy,
  SlaViolation,
  Status,
  TechnicianProfile,
  User,
} from "../api/types";
import { slaState } from "../lib/sla";

export class MockError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;

// Same values as SLAPolicy.default() in domain/sla.py.
const TARGETS: Record<Priority, [response: number, resolution: number]> = {
  P1: [5 * MINUTE, 30 * MINUTE],
  P2: [15 * MINUTE, 2 * HOUR],
  P3: [1 * HOUR, 8 * HOUR],
  P4: [4 * HOUR, 24 * HOUR],
};

// Same transitions as domain/states.py.
const TRANSITIONS: Partial<Record<Status, Partial<Record<IncidentAction, Status>>>> = {
  ASSIGNED: { acknowledge: "ACKNOWLEDGED" },
  ACKNOWLEDGED: { start_work: "IN_PROGRESS" },
  IN_PROGRESS: { request_info: "AWAITING_INFO", resolve: "RESOLVED" },
  AWAITING_INFO: { provide_info: "IN_PROGRESS" },
  RESOLVED: { verify: "VERIFIED", reject_resolution: "REOPENED" },
  VERIFIED: { close: "CLOSED" },
  REOPENED: { start_work: "IN_PROGRESS" },
};

// Same rules as domain/permissions.py.
const TECHNICIAN_ONLY: IncidentAction[] = ["acknowledge", "start_work", "request_info", "resolve"];
const REPORTER_ONLY: IncidentAction[] = ["provide_info", "verify", "reject_resolution"];

export const MOCK_PASSWORD = "demo1234";

const users: User[] = [
  { id: "E102", name: "Priya Nair", email: "employee@iitsm.test", role: "EMPLOYEE" },
  { id: "T205", name: "Arjun Rao", email: "technician@iitsm.test", role: "TECHNICIAN" },
  { id: "A001", name: "Meera Iyer", email: "admin@iitsm.test", role: "ADMIN" },
  { id: "E087", name: "Kabir Shah", email: "kabir@iitsm.test", role: "EMPLOYEE" },
  { id: "E143", name: "Ananya Das", email: "ananya@iitsm.test", role: "EMPLOYEE" },
  { id: "E051", name: "Rohan Gupta", email: "rohan@iitsm.test", role: "EMPLOYEE" },
  { id: "T101", name: "Sana Khan", email: "sana@iitsm.test", role: "TECHNICIAN" },
  { id: "T102", name: "Dev Patel", email: "dev@iitsm.test", role: "TECHNICIAN" },
  { id: "T103", name: "Isha Menon", email: "isha@iitsm.test", role: "TECHNICIAN" },
  { id: "T104", name: "Vikram Joshi", email: "vikram@iitsm.test", role: "TECHNICIAN" },
];

const inactiveUsers = new Set<string>();
const escalationLevels = new Map<string, number>([["A001", 1]]);

type Profile = Omit<TechnicianProfile, "id" | "name" | "activeCount">;

const profiles = new Map<string, Profile>([
  ["T205", { skills: ["APPLICATION", "STORAGE", "SOFTWARE"], experienceYears: 6, maxWorkload: 6, available: true }],
  ["T101", { skills: ["DATABASE", "CLOUD"], experienceYears: 8, maxWorkload: 5, available: true }],
  ["T102", { skills: ["NETWORK", "HARDWARE"], experienceYears: 3, maxWorkload: 5, available: true }],
  ["T103", { skills: ["SECURITY", "AUTHENTICATION"], experienceYears: 5, maxWorkload: 5, available: true }],
  ["T104", { skills: ["HARDWARE", "SOFTWARE"], experienceYears: 2, maxWorkload: 4, available: true }],
]);

const STRATEGIES: AssignmentSettings["options"] = [
  { id: "SKILL", label: "Skill-based", description: "Most experienced technician with the matching skill." },
  { id: "LOAD", label: "Load-based", description: "Whoever has the fewest active incidents." },
  { id: "ROUND_ROBIN", label: "Round-robin", description: "Technicians take turns in ID order." },
];
let strategy: AssignmentStrategyId = "SKILL";
let lastRoundRobinId: string | null = null;

const services: AdminService[] = [
  { id: "SVC-PAY", name: "Payment", criticality: 5, active: true },
  { id: "SVC-AUTH", name: "Authentication", criticality: 5, active: true },
  { id: "SVC-DB", name: "Database", criticality: 4, active: true },
  { id: "SVC-NET", name: "Network", criticality: 4, active: true },
  { id: "SVC-STORE", name: "Cloud storage", criticality: 3, active: true },
  { id: "SVC-MAIL", name: "Email", criticality: 2, active: true },
];

const categories: AdminCategory[] = ["HARDWARE", "SOFTWARE", "NETWORK", "DATABASE", "CLOUD", "SECURITY", "AUTHENTICATION", "APPLICATION", "STORAGE"].map(
  (name) => ({ name, description: "", active: true }),
);

const LEVEL_VALUE: Record<Level, number> = { LOW: 1, MEDIUM: 2, HIGH: 3 };
const MATRIX: Record<number, Record<number, number>> = {
  3: { 3: 1, 2: 2, 1: 3 },
  2: { 3: 2, 2: 3, 1: 4 },
  1: { 3: 3, 2: 4, 1: 4 },
};

// Same calculation as MatrixPriorityStrategy in domain/priority.py.
function calculatePriority(impact: Level, urgency: Level, criticality: number, affectedUsers: number): Priority {
  const i = LEVEL_VALUE[impact];
  const u = Math.min(LEVEL_VALUE[urgency], i + 1);
  const bump = (criticality >= 4 ? 1 : 0) + (affectedUsers >= 50 ? 1 : 0);
  return `P${Math.max(1, MATRIX[i][u] - bump)}` as Priority;
}

const ref = (id: string): PersonRef => ({ id, name: users.find((u) => u.id === id)?.name ?? id });

interface Row {
  id: string;
  description: string;
  status: Status;
  priority: Priority;
  category: string;
  service: string;
  impact: Level;
  urgency: Level;
  affectedUsers: number;
  reporterId: string;
  technicianId: string | null;
  createdAt: number;
  pausedTotal: number;
  pausedAt: number | null;
  respondedAt: number | null;
  resolvedAt: number | null;
  resolution: string | null;
  infoRequest: string | null;
  feedback: Incident["feedback"];
  history: HistoryEntry[];
  possibleDuplicates: Incident["possibleDuplicates"];
}

type Seed = Pick<Row, "id" | "description" | "status" | "priority" | "category" | "service" | "impact" | "urgency" | "affectedUsers" | "reporterId"> & {
  secondsLeft: number;
  respondedAfterMinutes: number | null;
  events: [minutesAfterCreation: number, actorId: string, action: string, description: string][];
  possibleDuplicates?: Row["possibleDuplicates"];
  infoRequest?: string;
};

function row(seed: Seed): Row {
  const now = Date.now();
  const createdAt = now - (TARGETS[seed.priority][1] - seed.secondsLeft * SECOND);
  const paused = seed.status === "AWAITING_INFO";
  return {
    id: seed.id,
    description: seed.description,
    status: seed.status,
    priority: seed.priority,
    category: seed.category,
    service: seed.service,
    impact: seed.impact,
    urgency: seed.urgency,
    affectedUsers: seed.affectedUsers,
    reporterId: seed.reporterId,
    technicianId: "T205",
    createdAt,
    pausedTotal: 0,
    pausedAt: paused ? now : null,
    respondedAt: seed.respondedAfterMinutes === null ? null : createdAt + seed.respondedAfterMinutes * MINUTE,
    resolvedAt: null,
    resolution: null,
    infoRequest: seed.infoRequest ?? null,
    feedback: null,
    possibleDuplicates: seed.possibleDuplicates ?? [],
    history: seed.events
      .map(([minutes, actorId, action, description]) => ({
        at: new Date(createdAt + minutes * MINUTE).toISOString(),
        actorId,
        action,
        description,
        previousStatus: null,
        newStatus: null,
      }))
      .reverse(),
  };
}

const incidents: Row[] = [
  row({
    id: "INC1024",
    description: "Payment application unavailable. Users cannot complete transactions.",
    status: "IN_PROGRESS",
    priority: "P1",
    category: "APPLICATION",
    service: "Payment",
    impact: "HIGH",
    urgency: "HIGH",
    affectedUsers: 420,
    reporterId: "E102",
    secondsLeft: 330,
    respondedAfterMinutes: 5,
    events: [
      [0, "E102", "created", "Created by E102"],
      [1, "SYSTEM", "classify", "Classified as APPLICATION"],
      [1, "SYSTEM", "set_priority", "Priority calculated as P1"],
      [2, "SYSTEM", "assign", "Assigned to T205 by skill-based strategy"],
      [5, "T205", "acknowledge", "Acknowledged by T205"],
      [15, "T205", "start_work", "Investigation started"],
    ],
    possibleDuplicates: [
      { id: "INC1025", description: "Payment transaction failing", similarity: 0.91 },
      { id: "INC1026", description: "Unable to make payment", similarity: 0.84 },
    ],
  }),
  row({
    id: "INC1019",
    description: "VPN drops every few minutes on floor 4.",
    status: "ACKNOWLEDGED",
    priority: "P2",
    category: "NETWORK",
    service: "Network",
    impact: "MEDIUM",
    urgency: "HIGH",
    affectedUsers: 35,
    reporterId: "E102",
    secondsLeft: 4320,
    respondedAfterMinutes: 9,
    events: [
      [0, "E102", "created", "Created by E102"],
      [1, "SYSTEM", "assign", "Assigned to T205 by load-based strategy"],
      [9, "T205", "acknowledge", "Acknowledged by T205"],
    ],
  }),
  row({
    id: "INC1011",
    description: "Finance shared drive reports a quota error when saving files.",
    status: "ASSIGNED",
    priority: "P3",
    category: "STORAGE",
    service: "Cloud storage",
    impact: "MEDIUM",
    urgency: "MEDIUM",
    affectedUsers: 12,
    reporterId: "E102",
    secondsLeft: 26000,
    respondedAfterMinutes: null,
    events: [
      [0, "E102", "created", "Created by E102"],
      [13, "SYSTEM", "assign", "Assigned to T205 by skill-based strategy"],
    ],
  }),
  row({
    id: "INC1007",
    description: "Calendar not syncing on one laptop.",
    status: "AWAITING_INFO",
    priority: "P4",
    category: "SOFTWARE",
    service: "Email",
    impact: "LOW",
    urgency: "LOW",
    affectedUsers: 1,
    reporterId: "E102",
    secondsLeft: 68400,
    respondedAfterMinutes: 70,
    infoRequest: "Which client version is installed?",
    events: [
      [0, "E102", "created", "Created by E102"],
      [70, "T205", "acknowledge", "Acknowledged by T205"],
      [90, "T205", "request_info", "Requested information: which client version is installed?"],
    ],
  }),
];

// Resolution text for the seeded history, so suggested fixes have something to show.
const FIXES: Record<string, string> = {
  DATABASE: "Replica was behind on WAL replay; restarted replication and raised max_wal_senders.",
  NETWORK: "Access point firmware bug; rebooted the controller and scheduled the upgrade.",
  AUTHENTICATION: "SAML signing certificate had expired; renewed it on the identity provider.",
  CLOUD: "Backup job lost its storage credentials; rotated the key and reran the job.",
  HARDWARE: "Printer driver queue was stuck; cleared the spooler and reinstalled the driver.",
  SOFTWARE: "Mail relay queue was full; raised the queue limit and flushed deferred mail.",
  APPLICATION: "Export query had no index on invoice date; added the index and retried.",
};

// Older incidents for the dashboards, audit log and search. Deterministic, so reports stay stable.
function seedHistory() {
  const now = Date.now();
  const DAY = 24 * HOUR;
  const reporters = ["E087", "E143", "E051"];
  const techs = ["T101", "T102", "T103", "T104", "T205"];
  const priorities: Priority[] = ["P3", "P2", "P4", "P3", "P1", "P2", "P3"];
  const levels: Level[] = ["MEDIUM", "HIGH", "LOW"];
  const summaries = ["Database replica lag above threshold", "Wi-Fi unstable in the east wing", "Single sign-on loop on the portal", "Backup job failed overnight", "Printer offline on floor 2", "Mail delivery delayed", "Invoice export times out"];
  const serviceOrder = ["Database", "Network", "Authentication", "Cloud storage", "Network", "Email", "Payment"];
  const categoryOrder = ["DATABASE", "NETWORK", "AUTHENTICATION", "CLOUD", "HARDWARE", "SOFTWARE", "APPLICATION"];

  for (let n = 0; n < 84; n++) {
    const k = n % 7;
    const priority = priorities[k];
    const createdAt = now - ((n * 5) % 14) * DAY - (n % 9) * HOUR - 2 * HOUR;
    const late = n % 8 === 3;
    const resolvedAt = createdAt + TARGETS[priority][1] * (late ? 1.3 : 0.4 + (n % 5) * 0.1);
    const respondedAt = createdAt + TARGETS[priority][0] * (n % 11 === 5 ? 1.4 : 0.6);
    const technicianId = techs[n % 5];
    const reporterId = reporters[n % 3];
    const at = (time: number) => new Date(time).toISOString();
    incidents.push({
      id: `INC${900 + n}`,
      description: `${summaries[k]}.`,
      status: "CLOSED",
      priority,
      category: categoryOrder[k],
      service: serviceOrder[k],
      impact: levels[n % 3],
      urgency: levels[(n + 1) % 3],
      affectedUsers: 1 + ((n * 3) % 40),
      reporterId,
      technicianId,
      createdAt,
      pausedTotal: 0,
      pausedAt: null,
      respondedAt,
      resolvedAt,
      resolution: FIXES[categoryOrder[k]] ?? "Fixed and confirmed with the reporter.",
      infoRequest: null,
      feedback: null,
      possibleDuplicates: [],
      history: [
        { at: at(resolvedAt + 30 * MINUTE), actorId: technicianId, action: "close", description: `Closed by ${technicianId}`, previousStatus: "VERIFIED", newStatus: "CLOSED" },
        { at: at(resolvedAt), actorId: technicianId, action: "resolve", description: "Marked resolved", previousStatus: "IN_PROGRESS", newStatus: "RESOLVED" },
        { at: at(respondedAt), actorId: technicianId, action: "acknowledge", description: `Acknowledged by ${technicianId}`, previousStatus: "ASSIGNED", newStatus: "ACKNOWLEDGED" },
        { at: at(createdAt + MINUTE), actorId: "SYSTEM", action: "assign", description: `Assigned to ${technicianId}`, previousStatus: "NEW", newStatus: "ASSIGNED" },
        { at: at(createdAt), actorId: reporterId, action: "created", description: `Created by ${reporterId}`, previousStatus: null, newStatus: "NEW" },
      ],
    });
  }

  const active: [string, Priority, string, string, string, number][] = [
    ["T101", "P2", "Reporting database refuses new connections", "Database", "DATABASE", 3000],
    ["T101", "P3", "Storage bucket permissions reset", "Cloud storage", "CLOUD", 16000],
    ["T101", "P3", "Nightly sync running slowly", "Database", "DATABASE", 22000],
    ["T102", "P2", "Switch flapping in server room", "Network", "NETWORK", -420],
    ["T102", "P4", "Desk phone has no dial tone", "Network", "HARDWARE", 60000],
    ["T103", "P1", "Suspicious sign-ins from one account", "Authentication", "SECURITY", 1100],
    ["T103", "P2", "Password reset emails not arriving", "Authentication", "AUTHENTICATION", 5200],
    ["T103", "P3", "MFA prompts repeat on mobile", "Authentication", "AUTHENTICATION", 20000],
    ["T103", "P3", "Audit export missing yesterday", "Authentication", "SECURITY", 25000],
    ["T103", "P4", "Certificate renewal reminder", "Authentication", "SECURITY", 70000],
    ["T104", "P4", "Laptop battery swelling", "Email", "HARDWARE", 50000],
  ];
  active.forEach(([technicianId, priority, summary, service, category, secondsLeft], index) => {
    const r = row({
      id: `INC${1030 + index}`,
      description: `${summary}.`,
      status: "IN_PROGRESS",
      priority,
      category,
      service,
      impact: "MEDIUM",
      urgency: "MEDIUM",
      affectedUsers: 3 + index,
      reporterId: reporters[index % 3],
      secondsLeft,
      respondedAfterMinutes: 1,
      events: [
        [0, reporters[index % 3], "created", `Created by ${reporters[index % 3]}`],
        [1, technicianId, "start_work", "Investigation started"],
      ],
    });
    r.technicianId = technicianId;
    incidents.push(r);
  });

  const waiting = row({
    id: "INC1050",
    description: "New starter laptop will not enrol in device management.",
    status: "NEW",
    priority: "P3",
    category: "HARDWARE",
    service: "Network",
    impact: "LOW",
    urgency: "HIGH",
    affectedUsers: 1,
    reporterId: "E143",
    secondsLeft: 28000,
    respondedAfterMinutes: null,
    events: [[0, "E143", "created", "Created by E143"]],
  });
  waiting.technicianId = null;
  incidents.push(waiting);
}
seedHistory();

let incidentSeq = 1051;
let notificationSeq = 3;
const notifications: (AppNotification & { userId: string })[] = [
  { id: "n2", userId: "T205", incidentId: "INC1024", message: "SLA warning on INC1024", createdAt: new Date(Date.now() - 2 * MINUTE).toISOString(), read: false },
  { id: "n1", userId: "T205", incidentId: "INC1011", message: "INC1011 was assigned to you", createdAt: new Date(Date.now() - 40 * MINUTE).toISOString(), read: false },
];

function notify(userId: string, incidentId: string, message: string) {
  notifications.unshift({
    id: `n${notificationSeq++}`,
    userId,
    incidentId,
    message,
    createdAt: new Date().toISOString(),
    read: false,
  });
}

function toApi(r: Row, viewer: User): Incident {
  const now = Date.now();
  const [responseTarget, resolutionTarget] = TARGETS[r.priority];
  const paused = r.pausedAt === null ? 0 : now - r.pausedAt;
  const deadline = r.createdAt + resolutionTarget + r.pausedTotal + paused;
  const stoppedAt = r.resolvedAt ?? (r.pausedAt === null ? null : now);
  return {
    id: r.id,
    description: r.description,
    status: r.status,
    priority: r.priority,
    category: r.category,
    service: r.service,
    impact: r.impact,
    urgency: r.urgency,
    affectedUsers: r.affectedUsers,
    reporter: ref(r.reporterId),
    technician: r.technicianId ? ref(r.technicianId) : null,
    createdAt: new Date(r.createdAt).toISOString(),
    resolution: r.resolution,
    infoRequest: r.infoRequest,
    feedback: r.feedback,
    history: viewer.role === "EMPLOYEE" ? r.history.filter((h) => h.action !== "add_note") : r.history,
    possibleDuplicates: r.possibleDuplicates,
    sla: {
      responseDeadline: new Date(r.createdAt + responseTarget).toISOString(),
      resolutionDeadline: new Date(deadline).toISOString(),
      resolutionTargetSeconds: resolutionTarget / SECOND,
      isPaused: r.pausedAt !== null,
      respondedAt: r.respondedAt === null ? null : new Date(r.respondedAt).toISOString(),
      resolvedAt: r.resolvedAt === null ? null : new Date(r.resolvedAt).toISOString(),
      frozenRemainingSeconds: stoppedAt === null ? null : Math.round((deadline - stoppedAt) / SECOND),
    },
  };
}

function find(id: string): Row {
  const r = incidents.find((i) => i.id === id);
  if (!r) throw new MockError(404, "INCIDENT_NOT_FOUND", `Incident ${id} doesn't exist.`);
  return r;
}

function canView(r: Row, user: User) {
  return user.role === "ADMIN" || r.reporterId === user.id || r.technicianId === user.id;
}

const activeCount = (technicianId: string) =>
  incidents.filter((r) => r.technicianId === technicianId && r.status !== "CLOSED").length;

function eligibleTechnicians() {
  return users
    .filter((u) => u.role === "TECHNICIAN" && !inactiveUsers.has(u.id))
    .map((u) => ({ id: u.id, profile: profiles.get(u.id)!, active: activeCount(u.id) }))
    .filter((t) => t.profile.available && t.active < t.profile.maxWorkload);
}

// Same ordering rules as domain/assignment.py, including the load-based fallback.
function selectTechnician(category: string | null): { id: string; via: string } | null {
  const pool = eligibleTechnicians();
  const byLoad = [...pool].sort((a, b) => a.active - b.active || b.profile.experienceYears - a.profile.experienceYears || a.id.localeCompare(b.id));
  if (strategy === "SKILL" && category) {
    const skilled = pool
      .filter((t) => t.profile.skills.includes(category))
      .sort((a, b) => b.profile.experienceYears - a.profile.experienceYears || a.active - b.active || a.id.localeCompare(b.id));
    if (skilled[0]) return { id: skilled[0].id, via: "skill-based strategy" };
  }
  if (strategy === "ROUND_ROBIN" && pool.length) {
    const ordered = [...pool].sort((a, b) => a.id.localeCompare(b.id));
    const chosen = ordered.find((t) => lastRoundRobinId !== null && t.id > lastRoundRobinId) ?? ordered[0];
    lastRoundRobinId = chosen.id;
    return { id: chosen.id, via: "round-robin strategy" };
  }
  return byLoad[0] ? { id: byLoad[0].id, via: "load-based strategy" } : null;
}

function requireId<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new MockError(404, "NOT_FOUND", `${what} doesn't exist.`);
  return value;
}

function checkCriticality(value: unknown) {
  if (!Number.isInteger(value) || (value as number) < 1 || (value as number) > 5) {
    throw new MockError(422, "INVALID_INPUT", "Criticality must be a whole number from 1 to 5.");
  }
}

// Same rule as the API: 0 or empty removes the user from the chain.
function setEscalationLevel(id: string, level: number | null) {
  if (level === null || level === 0) {
    escalationLevels.delete(id);
    return;
  }
  if (!Number.isInteger(level) || level < 1 || level > 3) {
    throw new MockError(422, "INVALID_INPUT", "Escalation level must be 0 (none), 1, 2 or 3.");
  }
  escalationLevels.set(id, level);
}

const toAdminUser = (u: User): AdminUser => ({
  ...u,
  active: !inactiveUsers.has(u.id),
  escalationLevel: escalationLevels.get(u.id) ?? null,
});

function toTechnician(id: string): TechnicianProfile {
  return { id, name: ref(id).name, activeCount: activeCount(id), ...profiles.get(id)! };
}

function toPolicy(priority: Priority): SlaPolicy {
  return { priority, responseMinutes: TARGETS[priority][0] / MINUTE, resolutionMinutes: TARGETS[priority][1] / MINUTE };
}

function matchesFilters(r: Row, f: IncidentFilters): boolean {
  const api = toApi(r, users[2]);
  const state = slaState(api.sla, Date.now());
  const late = state === "done" && (api.sla.frozenRemainingSeconds ?? 0) < 0;
  const slaBucket = state === "done" ? (late ? "breached" : "met") : state;
  const created = r.createdAt;
  return (
    (!f.id || r.id.toLowerCase().includes(f.id.trim().toLowerCase())) &&
    (!f.status || r.status === f.status) &&
    (!f.priority || r.priority === f.priority) &&
    (!f.category || r.category === f.category) &&
    (!f.service || r.service === f.service) &&
    (!f.technician || r.technicianId === f.technician) &&
    (!f.sla || slaBucket === f.sla) &&
    (!f.from || created >= Date.parse(`${f.from}T00:00:00`)) &&
    (!f.to || created <= Date.parse(`${f.to}T23:59:59`))
  );
}

function violationsOf(r: Row): SlaViolation[] {
  const [responseTarget, resolutionTarget] = TARGETS[r.priority];
  const now = Date.now();
  const list: SlaViolation[] = [];
  const add = (type: SlaViolation["type"], deadline: number, end: number) => {
    if (end > deadline) {
      list.push({
        incidentId: r.id,
        description: r.description,
        priority: r.priority,
        technicianId: r.technicianId,
        type,
        deadline: new Date(deadline).toISOString(),
        overBySeconds: Math.round((end - deadline) / SECOND),
        status: r.status,
      });
    }
  };
  add("Response", r.createdAt + responseTarget, r.respondedAt ?? now);
  if (r.pausedAt === null) add("Resolution", r.createdAt + resolutionTarget + r.pausedTotal, r.resolvedAt ?? now);
  return list;
}

function log(r: Row, user: Pick<User, "id">, action: string, description: string, previous: Status | null = null) {
  r.history.unshift({
    at: new Date().toISOString(),
    actorId: user.id,
    action,
    description,
    previousStatus: previous,
    newStatus: previous ? r.status : null,
  });
}

function authorize(r: Row, user: User, action: IncidentAction) {
  if (REPORTER_ONLY.includes(action) && r.reporterId !== user.id) {
    throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the reporter can do this.");
  }
  if (TECHNICIAN_ONLY.includes(action) && (user.role !== "TECHNICIAN" || r.technicianId !== user.id)) {
    throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the assigned technician can do this.");
  }
  if (action === "close" && user.role === "EMPLOYEE") {
    throw new MockError(403, "UNAUTHORIZED_ACTION", "Only staff can close an incident.");
  }
}

export const db = {
  findUser: (id: string) => users.find((u) => u.id === id),

  login(email: string, password: string) {
    const user = users.find((u) => u.email === email.trim().toLowerCase());
    if (!user || password !== MOCK_PASSWORD) {
      throw new MockError(401, "INVALID_LOGIN", "That email and password don't match. Try again.");
    }
    if (inactiveUsers.has(user.id)) {
      throw new MockError(403, "UNAUTHORIZED_ACTION", "This account has been deactivated. Contact your administrator.");
    }
    return user;
  },

  register(name: string, email: string, password: string) {
    const normalized = email.trim().toLowerCase();
    if (!name.trim() || !normalized.includes("@") || password.length < 8) {
      throw new MockError(422, "INVALID_INPUT", "Enter your name, a valid email, and a password of at least 8 characters.");
    }
    if (users.some((u) => u.email === normalized)) {
      throw new MockError(409, "EMAIL_TAKEN", "An account with that email already exists. Sign in instead.");
    }
    const user: User = { id: `E${100 + users.length}`, name: name.trim(), email: normalized, role: "EMPLOYEE" };
    users.push(user);
    return user;
  },

  listIncidents: (user: User, filters: IncidentFilters = {}) =>
    incidents.filter((r) => canView(r, user) && matchesFilters(r, filters)).map((r) => toApi(r, user)),

  workload(user: User) {
    if (user.role !== "TECHNICIAN") throw new MockError(403, "UNAUTHORIZED_ACTION", "Only technicians have a workload.");
    return { active: activeCount(user.id), max: profiles.get(user.id)?.maxWorkload ?? 5 };
  },

  assign(id: string, actor: User, technicianId: string) {
    const r = find(id);
    if (actor.role === "EMPLOYEE") throw new MockError(403, "UNAUTHORIZED_ACTION", "Only staff can assign incidents.");
    if (r.status !== "NEW" && r.status !== "CLASSIFIED") {
      throw new MockError(409, "INVALID_STATE_TRANSITION", "Only new or classified incidents can be assigned.");
    }
    const profile = requireId(profiles.get(technicianId), "That technician");
    if (inactiveUsers.has(technicianId) || !profile.available) {
      throw new MockError(409, "TECHNICIAN_UNAVAILABLE", "That technician isn't available right now. Choose someone else.");
    }
    if (activeCount(technicianId) >= profile.maxWorkload) {
      throw new MockError(409, "TECHNICIAN_WORKLOAD_EXCEEDED", "That technician is at full capacity. Choose someone else.");
    }
    const previous = r.status;
    r.status = "ASSIGNED";
    r.technicianId = technicianId;
    log(r, actor, "assign", `Assigned to ${technicianId} by ${actor.id}`, previous);
    notify(technicianId, r.id, `${r.id} was assigned to you`);
    notify(r.reporterId, r.id, `${r.id} was assigned to ${ref(technicianId).name}`);
    return toApi(r, actor);
  },

  admin: {
    listUsers: () => users.map(toAdminUser),
    createUser(input: Partial<AdminUser>) {
      const name = input.name?.trim();
      const email = input.email?.trim().toLowerCase();
      const role = input.role as Role | undefined;
      if (!name || !email?.includes("@") || !role) throw new MockError(422, "INVALID_INPUT", "Enter a name, a valid email, and a role.");
      if (users.some((u) => u.email === email)) throw new MockError(409, "EMAIL_TAKEN", "An account with that email already exists.");
      const prefix = role[0];
      const id = `${prefix}${String(300 + users.length)}`;
      const user: User = { id, name, email, role };
      users.push(user);
      if (role === "TECHNICIAN") profiles.set(id, { skills: [], experienceYears: 0, maxWorkload: 5, available: true });
      if (input.escalationLevel !== undefined) setEscalationLevel(id, input.escalationLevel);
      return toAdminUser(user);
    },
    updateUser(id: string, changes: Partial<AdminUser>, actor: User) {
      const user = requireId(users.find((u) => u.id === id), "That user");
      if (changes.active === false && id === actor.id) throw new MockError(409, "INVALID_INPUT", "You can't deactivate your own account.");
      if (changes.name !== undefined) {
        if (!changes.name.trim()) throw new MockError(422, "INVALID_INPUT", "Name is required.");
        user.name = changes.name.trim();
      }
      if (changes.active === false) inactiveUsers.add(id);
      if (changes.active === true) inactiveUsers.delete(id);
      if (changes.escalationLevel !== undefined) setEscalationLevel(id, changes.escalationLevel);
      return toAdminUser(user);
    },

    listTechnicians: () => [...profiles.keys()].map(toTechnician),
    updateTechnician(id: string, changes: Partial<TechnicianProfile>) {
      const profile = requireId(profiles.get(id), "That technician");
      if (changes.maxWorkload !== undefined && (!Number.isInteger(changes.maxWorkload) || changes.maxWorkload < 1)) {
        throw new MockError(422, "INVALID_INPUT", "Maximum workload must be at least 1.");
      }
      if (changes.experienceYears !== undefined && (!Number.isInteger(changes.experienceYears) || changes.experienceYears < 0)) {
        throw new MockError(422, "INVALID_INPUT", "Experience can't be negative.");
      }
      Object.assign(profile, {
        ...(changes.skills && { skills: changes.skills.map((s) => s.trim().toUpperCase()).filter(Boolean) }),
        ...(changes.experienceYears !== undefined && { experienceYears: changes.experienceYears }),
        ...(changes.maxWorkload !== undefined && { maxWorkload: changes.maxWorkload }),
        ...(changes.available !== undefined && { available: changes.available }),
      });
      return toTechnician(id);
    },

    listServices: () => services,
    createService(input: Partial<AdminService>) {
      const name = input.name?.trim();
      if (!name) throw new MockError(422, "INVALID_INPUT", "Service name is required.");
      checkCriticality(input.criticality);
      if (services.some((s) => s.name.toLowerCase() === name.toLowerCase())) throw new MockError(409, "INVALID_INPUT", "A service with that name already exists.");
      const service: AdminService = { id: `SVC-${services.length + 1}`, name, criticality: input.criticality!, active: true };
      services.push(service);
      return service;
    },
    updateService(id: string, changes: Partial<AdminService>) {
      const service = requireId(services.find((s) => s.id === id), "That service");
      if (changes.name !== undefined && !changes.name.trim()) throw new MockError(422, "INVALID_INPUT", "Service name is required.");
      if (changes.criticality !== undefined) checkCriticality(changes.criticality);
      Object.assign(service, changes);
      return service;
    },

    listSlaPolicies: () => (Object.keys(TARGETS) as Priority[]).map(toPolicy),
    updateSlaPolicy(priority: Priority, changes: Partial<SlaPolicy>) {
      requireId(TARGETS[priority], "That priority");
      const response = changes.responseMinutes ?? TARGETS[priority][0] / MINUTE;
      const resolution = changes.resolutionMinutes ?? TARGETS[priority][1] / MINUTE;
      if (!(response > 0) || !(resolution > 0)) throw new MockError(422, "INVALID_INPUT", "Targets must be greater than zero.");
      if (response >= resolution) throw new MockError(422, "INVALID_INPUT", "The response target must be shorter than the resolution target.");
      TARGETS[priority] = [response * MINUTE, resolution * MINUTE];
      return toPolicy(priority);
    },

    listCategories: () => categories,
    createCategory(input: Partial<AdminCategory>) {
      const name = input.name?.trim().toUpperCase();
      if (!name) throw new MockError(422, "INVALID_INPUT", "Category name is required.");
      if (categories.some((c) => c.name === name)) throw new MockError(409, "INVALID_INPUT", "That category already exists.");
      const category: AdminCategory = { name, description: input.description?.trim() ?? "", active: true };
      categories.push(category);
      return category;
    },
    updateCategory(name: string, changes: Partial<AdminCategory>) {
      const category = requireId(categories.find((c) => c.name === name), "That category");
      if (changes.description !== undefined) category.description = changes.description.trim();
      if (changes.active !== undefined) category.active = changes.active;
      return category;
    },

    assignment: (): AssignmentSettings => ({ current: strategy, options: STRATEGIES }),
    setAssignment(current: AssignmentStrategyId): AssignmentSettings {
      if (!STRATEGIES.some((s) => s.id === current)) throw new MockError(422, "INVALID_INPUT", "Choose a valid strategy.");
      strategy = current;
      return { current: strategy, options: STRATEGIES };
    },

    audit: (): AuditEntry[] =>
      incidents
        .flatMap((r) => r.history.map((h) => ({ ...h, incidentId: r.id })))
        .sort((a, b) => Date.parse(b.at) - Date.parse(a.at)),

    violations: () =>
      incidents.flatMap(violationsOf).sort((a, b) => Date.parse(b.deadline) - Date.parse(a.deadline)),

    // Mirrors P4's duplicate clusters: open incidents linked as possible duplicates.
    clusters(): IncidentCluster[] {
      const open = incidents.filter((r) => !["RESOLVED", "VERIFIED", "CLOSED"].includes(r.status));
      return open
        .filter((r) => r.possibleDuplicates.length > 0)
        .map((r) => ({
          serviceId: services.find((s) => s.name === r.service)?.id ?? r.service,
          service: r.service,
          incidents: [r, ...r.possibleDuplicates.map((d) => incidents.find((i) => i.id === d.id) ?? { ...r, id: d.id, description: d.description })].map((i) => ({
            id: i.id,
            description: i.description,
            status: i.status,
            priority: i.priority,
          })),
        }));
    },

    overview(): ReportOverview {
      const closedSet: Status[] = ["RESOLVED", "VERIFIED", "CLOSED"];
      const open = incidents.filter((r) => !closedSet.includes(r.status));
      const byService = new Map<string, number>();
      incidents.forEach((r) => byService.set(r.service, (byService.get(r.service) ?? 0) + 1));
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const dailyCreated = Array.from({ length: 14 }, (_, index) => {
        const start = today.getTime() - (13 - index) * 24 * HOUR;
        return {
          date: new Date(start).toISOString(),
          incidents: incidents.filter((r) => r.createdAt >= start && r.createdAt < start + 24 * HOUR).length,
        };
      });
      return {
        total: incidents.length,
        open: open.length,
        critical: open.filter((r) => r.priority === "P1").length,
        resolved: incidents.length - open.length,
        slaViolations: incidents.filter((r) => violationsOf(r).length > 0).length,
        technicianWorkload: [...profiles.keys()]
          .map((id) => ({ id, name: ref(id).name, active: activeCount(id), max: profiles.get(id)!.maxWorkload }))
          .sort((a, b) => b.active - a.active),
        serviceAnalysis: [...byService].map(([service, count]) => ({ service, incidents: count })).sort((a, b) => b.incidents - a.incidents),
        dailyCreated,
      };
    },
  },

  // Mirrors P4's suggested resolutions: resolved incidents in the same category.
  suggestions(id: string, user: User): ResolutionSuggestion[] {
    const r = find(id);
    if (user.role === "EMPLOYEE" || !canView(r, user)) {
      throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the assigned technician can see suggestions.");
    }
    const seen = new Set<string>();
    return incidents
      .filter((other) => other.id !== r.id && other.category === r.category && other.resolution)
      .filter((other) => !seen.has(other.resolution!) && seen.add(other.resolution!))
      .slice(0, 3)
      .map((other, index) => ({ incidentId: other.id, similarity: 0.82 - index * 0.07, category: other.category, resolution: other.resolution! }));
  },

  getIncident(id: string, user: User) {
    const r = find(id);
    if (!canView(r, user)) throw new MockError(403, "UNAUTHORIZED_ACTION", "You don't have access to this incident.");
    return toApi(r, user);
  },

  listServices: () => services.filter((s) => s.active).map(({ id, name }) => ({ id, name })),
  listCategories: () => categories.filter((c) => c.active).map((c) => c.name),

  // Mirrors IncidentFactory.create, followed by automatic assignment.
  createIncident(user: User, input: NewIncident) {
    const description = input.description?.trim();
    if (!description) throw new MockError(422, "INVALID_INPUT", "Describe the problem first.");
    if (description.length > 2000) throw new MockError(422, "INVALID_INPUT", "Keep the description under 2,000 characters.");
    const service = services.find((s) => s.id === input.serviceId && s.active);
    if (!service) throw new MockError(404, "SERVICE_NOT_FOUND", "Choose the affected service.");
    if (!Number.isInteger(input.affectedUsers) || input.affectedUsers < 1) {
      throw new MockError(422, "INVALID_INPUT", "Enter how many people are affected, as a whole number.");
    }
    const priority = calculatePriority(input.impact, input.urgency, service.criticality, input.affectedUsers);
    const now = Date.now();
    const chosen = selectTechnician(input.category);
    const r: Row = {
      id: `INC${incidentSeq++}`,
      description,
      status: chosen ? "ASSIGNED" : "NEW",
      priority,
      category: input.category ?? "UNCLASSIFIED",
      service: service.name,
      impact: input.impact,
      urgency: input.urgency,
      affectedUsers: input.affectedUsers,
      reporterId: user.id,
      technicianId: chosen?.id ?? null,
      createdAt: now,
      pausedTotal: 0,
      pausedAt: null,
      respondedAt: null,
      resolvedAt: null,
      resolution: null,
      infoRequest: null,
      feedback: null,
      possibleDuplicates: [],
      history: [],
    };
    incidents.unshift(r);
    log(r, user, "created", `Created by ${user.id}`);
    log(r, { id: "SYSTEM" }, "set_priority", `Priority calculated as ${priority}`);
    notify(user.id, r.id, `We received ${r.id}`);
    if (chosen) {
      log(r, { id: "SYSTEM" }, "assign", `Assigned to ${chosen.id} by ${chosen.via}`, "NEW");
      notify(chosen.id, r.id, `${r.id} was assigned to you`);
      notify(user.id, r.id, `${r.id} was assigned to ${ref(chosen.id).name}`);
    } else {
      log(r, { id: "SYSTEM" }, "assign_failed", "No technician has spare capacity. Waiting for an administrator.");
    }
    return toApi(r, user);
  },

  // Not in P1's domain yet: only the assigned technician can add notes there.
  addInformation(id: string, user: User, text: string) {
    const r = find(id);
    if (r.reporterId !== user.id) throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the reporter can add information.");
    if (!text?.trim()) throw new MockError(422, "INVALID_INPUT", "Write the extra information first.");
    if (r.status === "CLOSED") throw new MockError(409, "INVALID_STATE_TRANSITION", "This incident is closed.");
    log(r, user, "add_information", `${user.id} added information: ${text.trim()}`);
    if (r.technicianId) notify(r.technicianId, r.id, `${user.id} added information to ${r.id}`);
    return toApi(r, user);
  },

  // Same checks as Incident.submit_feedback.
  submitFeedback(id: string, user: User, rating: number, comment: string) {
    const r = find(id);
    if (r.reporterId !== user.id) throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the reporter can give feedback.");
    if (!["RESOLVED", "VERIFIED", "CLOSED"].includes(r.status)) {
      throw new MockError(409, "INVALID_STATE_TRANSITION", "You can give feedback once the incident is resolved.");
    }
    if (r.feedback) throw new MockError(409, "INVALID_INPUT", "You've already given feedback on this incident.");
    if (!Number.isInteger(rating) || rating < 1 || rating > 5) throw new MockError(422, "INVALID_INPUT", "Choose a rating from 1 to 5.");
    r.feedback = { rating, comment: (comment ?? "").trim() };
    log(r, user, "submit_feedback", `Feedback submitted: ${rating} out of 5`);
    return toApi(r, user);
  },

  addNote(id: string, user: User, text: string) {
    const r = find(id);
    if (user.role !== "TECHNICIAN" || r.technicianId !== user.id) {
      throw new MockError(403, "UNAUTHORIZED_ACTION", "Only the assigned technician can add notes.");
    }
    if (!text?.trim()) throw new MockError(422, "INVALID_INPUT", "Write the note first.");
    if (r.status === "CLOSED") throw new MockError(409, "INVALID_STATE_TRANSITION", "Closed incidents can't take new notes.");
    log(r, user, "add_note", `Note: ${text.trim()}`);
    return toApi(r, user);
  },

  act(id: string, user: User, action: IncidentAction, message?: string) {
    const r = find(id);
    authorize(r, user, action);
    const next = TRANSITIONS[r.status]?.[action];
    if (!next) {
      throw new MockError(409, "INVALID_STATE_TRANSITION", `This incident is ${r.status.toLowerCase().replace("_", " ")}, so that action isn't available.`);
    }
    if ((action === "resolve" || action === "request_info" || action === "provide_info") && !message?.trim()) {
      throw new MockError(422, "INVALID_INPUT", "Add the details first.");
    }

    const previous = r.status;
    const now = Date.now();
    r.status = next;
    if (action === "acknowledge") r.respondedAt ??= now;
    if (action === "request_info") {
      r.pausedAt = now;
      r.infoRequest = message!.trim();
    }
    if (action === "provide_info" && r.pausedAt !== null) {
      r.pausedTotal += now - r.pausedAt;
      r.pausedAt = null;
      r.infoRequest = null;
    }
    if (action === "resolve") {
      r.resolvedAt = now;
      r.resolution = message!.trim();
    }
    if (action === "reject_resolution") r.resolvedAt = null;

    const text: Record<IncidentAction, string> = {
      acknowledge: `Acknowledged by ${user.id}`,
      start_work: "Investigation started",
      request_info: `Requested information: ${message?.trim()}`,
      provide_info: `${user.id} replied: ${message?.trim()}`,
      resolve: `Marked resolved: ${message?.trim()}`,
      verify: `Resolution verified by ${user.id}`,
      reject_resolution: `Resolution rejected by ${user.id}`,
      close: `Closed by ${user.id}`,
    };
    log(r, user, action, text[action], previous);

    if (action === "request_info") notify(r.reporterId, r.id, `${r.id} needs more information from you`);
    if (action === "resolve") notify(r.reporterId, r.id, `${r.id} was resolved. Check the fix and confirm.`);
    if (action === "close") notify(r.reporterId, r.id, `${r.id} was closed`);
    if (r.technicianId) {
      if (action === "provide_info") notify(r.technicianId, r.id, `${r.reporterId} replied on ${r.id}`);
      if (action === "verify") notify(r.technicianId, r.id, `${r.reporterId} confirmed the fix on ${r.id}`);
      if (action === "reject_resolution") notify(r.technicianId, r.id, `${r.reporterId} says ${r.id} is still broken`);
    }
    return toApi(r, user);
  },

  listNotifications: (user: User) =>
    notifications.filter((n) => n.userId === user.id).map(({ userId: _userId, ...n }) => n),

  markNotificationsRead(user: User) {
    notifications.filter((n) => n.userId === user.id).forEach((n) => (n.read = true));
  },
};
