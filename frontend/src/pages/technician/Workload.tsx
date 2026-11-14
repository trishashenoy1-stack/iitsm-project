import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Priority } from "../../api/types";

const PRIORITIES: Priority[] = ["P1", "P2", "P3", "P4"];

export function Workload() {
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: () => api.listIncidents() });
  const workload = useQuery({ queryKey: ["workload"], queryFn: api.myWorkload });
  if (incidents.isPending || workload.isPending) return <p className="p-4 text-fg-2">Loading workload</p>;
  if (incidents.error || workload.error) return <p role="alert" className="p-4 text-red">{(incidents.error ?? workload.error)?.message}</p>;

  const active = incidents.data.filter((i) => i.status !== "CLOSED");
  const counts = PRIORITIES.map((p) => ({ priority: p, count: active.filter((i) => i.priority === p).length }));

  return (
    <main className="card grid max-w-[620px] gap-3.5 px-5 py-4">
      <div>
        <p className="label">Current workload</p>
        <h1 className="text-[28px] leading-tight font-medium tracking-[-0.022em]">
          {workload.data.active} of {workload.data.max} active incidents
        </h1>
      </div>
      <ul className="grid gap-2">
        {counts.map(({ priority, count }) => (
          <li key={priority} className="grid grid-cols-[26px_minmax(0,1fr)_18px] items-center gap-2.5 font-mono text-xs font-medium">
            {priority}
            <span className="block rounded-sm bg-raise">
              <span className="block h-2.5 rounded-sm bg-fg-2" style={{ width: `${Math.min(100, (100 * count) / workload.data.max)}%` }} />
            </span>
            {count}
          </li>
        ))}
      </ul>
    </main>
  );
}
