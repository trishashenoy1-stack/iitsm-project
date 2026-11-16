import { delay, http, HttpResponse } from "msw";
import type { AssignmentStrategyId, IncidentAction, IncidentFilters, NewIncident, Priority, User } from "../api/types";
import { db, MockError } from "./db";

const TOKEN_PREFIX = "mock-token-";

function currentUser(request: Request): User {
  const header = request.headers.get("Authorization") ?? "";
  const user = db.findUser(header.replace(`Bearer ${TOKEN_PREFIX}`, ""));
  if (!user) throw new MockError(401, "NOT_AUTHENTICATED", "Your session expired. Sign in again.");
  return user;
}

type Resolver = (args: { request: Request; params: Record<string, string> }) => unknown | Promise<unknown>;

// Runs a handler with realistic latency and turns MockError into the API's error shape.
function route(resolve: Resolver) {
  return async ({ request, params }: { request: Request; params: Record<string, unknown> }) => {
    await delay(120);
    try {
      const body = await resolve({ request, params: params as Record<string, string> });
      return body === undefined ? new HttpResponse(null, { status: 204 }) : HttpResponse.json(body as never);
    } catch (error) {
      if (error instanceof MockError) {
        return HttpResponse.json({ code: error.code, message: error.message }, { status: error.status });
      }
      throw error;
    }
  };
}

const session = (user: User) => ({ token: `${TOKEN_PREFIX}${user.id}`, user });

function requireAdmin(request: Request): User {
  const user = currentUser(request);
  if (user.role !== "ADMIN") throw new MockError(403, "UNAUTHORIZED_ACTION", "Only administrators can do this.");
  return user;
}

function adminRoutes() {
  const a = db.admin;
  const list = (path: string, read: () => unknown) =>
    http.get(`/api/admin/${path}`, route(({ request }) => {
      requireAdmin(request);
      return read();
    }));
  const create = (path: string, write: (body: never) => unknown) =>
    http.post(`/api/admin/${path}`, route(async ({ request }) => {
      requireAdmin(request);
      return write((await request.json()) as never);
    }));
  const update = (path: string, write: (id: string, body: never, actor: User) => unknown) =>
    http.patch(`/api/admin/${path}/:id`, route(async ({ request, params }) => {
      const actor = requireAdmin(request);
      return write(params.id, (await request.json()) as never, actor);
    }));

  return [
    list("users", a.listUsers),
    create("users", a.createUser),
    update("users", a.updateUser),
    list("technicians", a.listTechnicians),
    update("technicians", a.updateTechnician),
    list("services", a.listServices),
    create("services", a.createService),
    update("services", a.updateService),
    list("sla-policies", a.listSlaPolicies),
    update("sla-policies", (id, body) => a.updateSlaPolicy(id as Priority, body)),
    list("categories", a.listCategories),
    create("categories", a.createCategory),
    update("categories", a.updateCategory),
    list("assignment-strategy", a.assignment),
    http.patch("/api/admin/assignment-strategy", route(async ({ request }) => {
      requireAdmin(request);
      const { current } = (await request.json()) as { current: AssignmentStrategyId };
      return a.setAssignment(current);
    })),
    list("audit-log", a.audit),
    list("sla-violations", a.violations),
    list("reports/overview", a.overview),
    list("reports/clusters", a.clusters),
  ];
}

export const handlers = [
  http.post("/api/auth/login", route(async ({ request }) => {
    const { email, password } = (await request.json()) as { email: string; password: string };
    return session(db.login(email, password));
  })),
  http.post("/api/auth/register", route(async ({ request }) => {
    const { name, email, password } = (await request.json()) as { name: string; email: string; password: string };
    return session(db.register(name, email, password));
  })),
  http.get("/api/auth/me", route(({ request }) => currentUser(request))),

  http.get("/api/services", route(({ request }) => {
    currentUser(request);
    return db.listServices();
  })),
  http.get("/api/categories", route(({ request }) => {
    currentUser(request);
    return db.listCategories();
  })),

  http.get("/api/me/workload", route(({ request }) => db.workload(currentUser(request)))),

  ...adminRoutes(),

  http.get("/api/incidents", route(({ request }) => {
    const filters = Object.fromEntries(new URL(request.url).searchParams) as IncidentFilters;
    return db.listIncidents(currentUser(request), filters);
  })),
  http.post("/api/incidents/:id/assign", route(async ({ request, params }) => {
    const { technicianId } = (await request.json()) as { technicianId: string };
    return db.assign(params.id, currentUser(request), technicianId);
  })),
  http.post("/api/incidents", route(async ({ request }) =>
    db.createIncident(currentUser(request), (await request.json()) as NewIncident),
  )),
  http.post("/api/incidents/:id/information", route(async ({ request, params }) => {
    const { text } = (await request.json()) as { text: string };
    return db.addInformation(params.id, currentUser(request), text);
  })),
  http.post("/api/incidents/:id/feedback", route(async ({ request, params }) => {
    const { rating, comment } = (await request.json()) as { rating: number; comment: string };
    return db.submitFeedback(params.id, currentUser(request), rating, comment);
  })),
  http.get("/api/incidents/:id/suggestions", route(({ request, params }) => db.suggestions(params.id, currentUser(request)))),
  http.get("/api/incidents/:id", route(({ request, params }) => db.getIncident(params.id, currentUser(request)))),
  http.post("/api/incidents/:id/actions/:action", route(async ({ request, params }) => {
    const { message } = (await request.json()) as { message?: string };
    return db.act(params.id, currentUser(request), params.action as IncidentAction, message);
  })),
  http.post("/api/incidents/:id/notes", route(async ({ request, params }) => {
    const { text } = (await request.json()) as { text: string };
    return db.addNote(params.id, currentUser(request), text);
  })),

  http.get("/api/notifications", route(({ request }) => db.listNotifications(currentUser(request)))),
  http.post("/api/notifications/read-all", route(({ request }) => {
    db.markNotificationsRead(currentUser(request));
  })),
];
