import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { PriorityTag } from "../../components/IncidentBits";
import { headline, STATUS_LABEL } from "../../lib/format";
import { shortDuration } from "../../lib/sla";

export function SlaViolations() {
  const { data, isPending, error } = useQuery({ queryKey: ["admin", "violations"], queryFn: api.admin.violations, refetchInterval: 15000 });

  return (
    <main className="card px-5 py-4">
      <h1 className="text-xl font-medium tracking-tight">SLA violations</h1>
      <p className="text-[13px] text-fg-2">
        {data ? `${data.length} missed ${data.length === 1 ? "target" : "targets"}, most recent first.` : "Every missed response or resolution target."}
      </p>
      {isPending && <p className="mt-3 text-fg-2">Loading violations</p>}
      {error && <p role="alert" className="mt-3 text-red">{error.message}</p>}
      {data?.length === 0 && <p className="mt-3 text-[13px] text-fg-2">No targets have been missed.</p>}
      {data && data.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[13px]">
            <thead className="text-xs text-fg-3">
              <tr className="border-b border-line">
                {["Incident", "Priority", "Summary", "Missed", "Over by", "Technician", "Status"].map((h) => (
                  <th key={h} className="py-2 pr-4 font-medium last:pr-0">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((v) => (
                <tr key={`${v.incidentId}-${v.type}`} className="border-b border-line last:border-0">
                  <td className="py-2.5 pr-4 font-mono text-xs"><Link className="underline-offset-2 hover:underline" to={`/admin/incidents/${v.incidentId}`}>{v.incidentId}</Link></td>
                  <td className="py-2.5 pr-4"><PriorityTag priority={v.priority} /></td>
                  <td className="py-2.5 pr-4">{headline(v.description)}</td>
                  <td className="py-2.5 pr-4 text-fg-2">{v.type}</td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-red">{shortDuration(v.overBySeconds)}</td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-fg-2">{v.technicianId ?? "None"}</td>
                  <td className="py-2.5 text-fg-2">{STATUS_LABEL[v.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
