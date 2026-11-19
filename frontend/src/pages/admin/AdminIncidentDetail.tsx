import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Incident, Priority } from "../../api/types";
import { Lifecycle } from "../../components/IncidentBits";
import { Skeleton } from "../../components/Skeleton";
import { SlaTile } from "../../components/SlaTile";
import { useToast } from "../../components/Toast";
import { LEVEL_LABEL, time, titleCase } from "../../lib/format";

export function AdminIncidentDetail() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [technicianId, setTechnicianId] = useState("");
  const [error, setError] = useState("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [reason, setReason] = useState("");

  const { data: incident, isPending, error: loadError } = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.getIncident(id),
    refetchInterval: 5000,
  });
  const technicians = useQuery({ queryKey: ["admin", "technicians"], queryFn: api.admin.listTechnicians });

  const mutation = useMutation({
    mutationFn: (run: () => Promise<Incident>) => run(),
    onSuccess: (updated) => {
      queryClient.setQueryData(["incident", id], updated);
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["admin"] });
      setError("");
    },
    onError: (e) => setError(e.message),
  });

  if (isPending) return <Skeleton label="Loading incident" />;
  if (loadError) return <p role="alert" className="p-4 text-red">{loadError.message}</p>;

  const canAssign = incident.status === "NEW" || incident.status === "CLASSIFIED";

  function assign() {
    if (!technicianId) {
      setError("Choose a technician first.");
      return;
    }
    mutation.mutate(() => api.assignIncident(id, technicianId), { onSuccess: () => toast(`Assigned to ${technicianId}`) });
  }

  const isOpen = !["RESOLVED", "VERIFIED", "CLOSED"].includes(incident.status);

  function changePriority() {
    if (!priority || priority === incident!.priority) {
      setError("Choose a different priority first.");
      return;
    }
    mutation.mutate(() => api.setPriority(id, priority, reason.trim()), {
      onSuccess: () => {
        toast(`Priority changed to ${priority}`);
        setPriority("");
        setReason("");
      },
    });
  }

  return (
    <main className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
      <Link to="/admin/incidents" className="px-1 text-[13px] text-fg-2 hover:text-fg">Back to incidents</Link>
      <SlaTile incident={incident} />
      <Lifecycle status={incident.status} />

      {(canAssign || incident.status === "VERIFIED") && (
        <section className="card px-4 py-3.5">
          {canAssign ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="grid gap-1 text-[13px] text-fg-2">
                Assign to
                <select id="assign-technician" className="field min-w-[260px] text-fg" value={technicianId} onChange={(e) => setTechnicianId(e.target.value)}>
                  <option value="">Choose a technician</option>
                  {technicians.data?.map((t) => (
                    <option key={t.id} value={t.id}>{t.id} {t.name} ({t.activeCount} of {t.maxWorkload})</option>
                  ))}
                </select>
              </label>
              <button className="btn btn-go" disabled={mutation.isPending} onClick={assign}>Assign</button>
            </div>
          ) : (
            <button className="btn btn-go" disabled={mutation.isPending} onClick={() => mutation.mutate(() => api.performAction(id, "close"), { onSuccess: () => toast(`${id} closed`) })}>
              Close incident
            </button>
          )}
          {error && <p role="alert" className="mt-1.5 text-[13px] text-red">{error}</p>}
        </section>
      )}

      {isOpen && (
        <section className="card px-4 py-3.5">
          <div className="flex flex-wrap items-end gap-2">
            <label className="grid gap-1 text-[13px] text-fg-2">
              Override priority (now {incident.priority})
              <select id="override-priority" className="field min-w-[120px] text-fg" value={priority} onChange={(e) => setPriority(e.target.value as Priority | "")}>
                <option value="">Choose</option>
                {(["P1", "P2", "P3", "P4"] as const).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <label className="grid min-w-[220px] flex-1 gap-1 text-[13px] text-fg-2">
              Reason
              <input className="field text-fg" value={reason} maxLength={500} placeholder="Why the calculated priority is wrong" onChange={(e) => setReason(e.target.value)} />
            </label>
            <button className="btn" disabled={mutation.isPending} onClick={changePriority}>Change priority</button>
          </div>
          {!(canAssign || incident.status === "VERIFIED") && error && <p role="alert" className="mt-1.5 text-[13px] text-red">{error}</p>}
        </section>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-2.5 lg:grid-cols-[minmax(0,1fr)_minmax(190px,260px)]">
        <section className="card px-4 py-3.5">
          <h2 className="label">History</h2>
          <ul className="mt-2 grid gap-[7px]">
            {incident.history.map((entry, index) => (
              <li key={`${entry.at}-${index}`} className="grid grid-cols-[44px_minmax(0,1fr)] gap-2.5 text-[13px]">
                <time className="font-mono text-xs leading-5 text-fg-3">{time(entry.at)}</time>
                <span className="wrap-anywhere">{entry.description}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card px-4 py-3.5">
          <h2 className="label">Details</h2>
          <dl className="mt-2 grid gap-[7px] text-[13px]">
            {[
              ["Technician", incident.technician?.name ?? "Unassigned"],
              ["Reporter", incident.reporter.name],
              ["Category", titleCase(incident.category)],
              ...(incident.suggestedCategory
                ? [["AI-suggested category", titleCase(incident.suggestedCategory)]]
                : []),
              ["Impact", LEVEL_LABEL[incident.impact]],
              ["Urgency", LEVEL_LABEL[incident.urgency]],
              ["Affected users", String(incident.affectedUsers)],
              ...(incident.feedback ? [["Feedback", `${incident.feedback.rating} of 5`]] : []),
            ].map(([term, value]) => (
              <div key={term} className="flex justify-between gap-3">
                <dt className="text-fg-3">{term}</dt>
                <dd className="text-right wrap-anywhere">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </main>
  );
}
