import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { headline, STATUS_LABEL } from "../../lib/format";

export function MyIncidents() {
  const { data, isPending, error } = useQuery({ queryKey: ["incidents"], queryFn: () => api.listIncidents() });

  return (
    <main>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] leading-tight font-medium tracking-[-0.022em]">Your incidents</h1>
        <Link to="/employee/report" className="btn btn-go">
          Report an incident
        </Link>
      </div>
      {isPending && <p className="text-fg-2">Loading your incidents</p>}
      {error && <p role="alert" className="text-red">{error.message}</p>}
      {data?.length === 0 && <p className="text-fg-2">Nothing reported yet. Report a problem and track it here.</p>}
      <ul className="grid gap-3">
        {data?.map((incident) => (
          <li key={incident.id}>
            <Link to={`/employee/incidents/${incident.id}`} className="card flex flex-wrap items-center justify-between gap-3 px-6 py-5 hover:bg-raise">
              <div className="min-w-0">
                <p className="text-base wrap-anywhere">{headline(incident.description)}</p>
                <p className="mt-0.5 text-[13px] text-fg-2">
                  <span className="font-mono">{incident.id}</span> · {incident.service}
                </p>
              </div>
              <span className={`text-[13px] ${incident.status === "AWAITING_INFO" || incident.status === "RESOLVED" ? "font-medium text-lime" : "text-fg"}`}>
                {incident.status === "AWAITING_INFO" ? "Needs your reply" : incident.status === "RESOLVED" ? "Check the fix" : STATUS_LABEL[incident.status]}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
