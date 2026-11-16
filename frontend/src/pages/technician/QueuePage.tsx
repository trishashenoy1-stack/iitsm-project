import { useQuery } from "@tanstack/react-query";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Incident } from "../../api/types";
import { PriorityTag, SlaBrief } from "../../components/IncidentBits";
import { headline } from "../../lib/format";
import { remainingSeconds } from "../../lib/sla";
import { IncidentPanel } from "./IncidentPanel";

function urgencyOrder(incidents: Incident[]) {
  const now = Date.now();
  const group = (i: Incident) => (i.sla.resolvedAt ? 2 : i.sla.isPaused ? 1 : 0);
  return [...incidents].sort((a, b) => group(a) - group(b) || remainingSeconds(a.sla, now) - remainingSeconds(b.sla, now));
}

export function QueuePage() {
  const { id } = useParams();
  const { data, isPending, error } = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api.listIncidents(),
    refetchInterval: 15000,
  });

  if (isPending) return <p className="p-4 text-fg-2">Loading your queue</p>;
  if (error) return <p role="alert" className="p-4 text-red">{error.message}</p>;

  const queue = urgencyOrder(data.filter((i) => i.status !== "CLOSED"));
  if (!id && queue.length > 0) return <Navigate to={`/technician/queue/${queue[0].id}`} replace />;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-2.5 md:grid-cols-[minmax(240px,310px)_minmax(0,1fr)]">
      <section aria-label="Assigned incidents" className="card px-2 pt-3 pb-2">
        <h2 className="label flex justify-between px-2 pb-2">
          <span>Assigned to you</span>
          <span className="font-mono">{queue.length}</span>
        </h2>
        {queue.length === 0 && <p className="px-2 pb-2 text-[13px] text-fg-2">Your queue is clear.</p>}
        {queue.map((incident) => (
          <NavLink
            key={incident.id}
            to={`/technician/queue/${incident.id}`}
            className={({ isActive }) =>
              `group grid grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-0.5 rounded-[9px] px-2 py-[9px] hover:bg-raise ${isActive ? "active bg-raise" : ""}`
            }
          >
            <span className="flex items-center gap-1.5">
              <span className="font-mono text-xs text-fg-2 group-[.active]:text-lime">{incident.id}</span>
              <PriorityTag priority={incident.priority} />
            </span>
            <SlaBrief incident={incident} />
            <span className="col-span-2 text-[13px] leading-[1.35] wrap-anywhere">{headline(incident.description)}</span>
          </NavLink>
        ))}
      </section>
      {id ? <IncidentPanel key={id} id={id} /> : null}
    </div>
  );
}
