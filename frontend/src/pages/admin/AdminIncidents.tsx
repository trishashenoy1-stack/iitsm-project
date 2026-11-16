import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { IncidentFilters, Status } from "../../api/types";
import { PriorityTag, SlaBrief } from "../../components/IncidentBits";
import { headline, STATUS_LABEL, titleCase } from "../../lib/format";

const PAGE_SIZE = 25;
const FILTER_KEYS = ["id", "status", "priority", "category", "service", "technician", "sla", "from", "to"] as const;
const STATUSES = Object.keys(STATUS_LABEL) as Status[];
const SLA_OPTIONS = [
  ["ok", "On track"],
  ["warning", "Warning"],
  ["breached", "Breached"],
  ["paused", "Paused"],
  ["met", "Met"],
];

function Select({ id, label, value, onChange, options }: { id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="grid gap-1 text-xs text-fg-3">
      {label}
      <select id={id} className="field py-1.5 text-[13px] text-fg" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Any</option>
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </label>
  );
}

export function AdminIncidents() {
  const [params, setParams] = useSearchParams();
  const [limit, setLimit] = useState(PAGE_SIZE);
  const filters: IncidentFilters = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""]));

  const { data, isPending, error } = useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => api.listIncidents(filters),
    refetchInterval: 15000,
    // Keep the current rows on screen while a new filter loads, so typing doesn't flicker.
    placeholderData: keepPreviousData,
  });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.listCategories });
  const services = useQuery({ queryKey: ["services"], queryFn: api.listServices });
  const technicians = useQuery({ queryKey: ["admin", "technicians"], queryFn: api.admin.listTechnicians });

  function setFilter(key: keyof IncidentFilters, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setLimit(PAGE_SIZE);
  }

  const v = (key: keyof IncidentFilters) => filters[key] ?? "";
  const rows = data ?? [];

  return (
    <main className="grid grid-cols-[minmax(0,1fr)] gap-2.5">
      <section className="card px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-xl font-medium tracking-tight">Incidents</h1>
          {params.size > 0 && (
            <button className="text-[13px] text-fg-2 underline underline-offset-2 hover:text-fg" onClick={() => setParams({}, { replace: true })}>
              Clear filters
            </button>
          )}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-5">
          <label className="grid gap-1 text-xs text-fg-3">
            Incident ID
            <input id="filter-id" className="field py-1.5 text-[13px] text-fg" placeholder="INC1024" value={v("id")} onChange={(e) => setFilter("id", e.target.value)} />
          </label>
          <Select id="filter-status" label="Status" value={v("status")} onChange={(x) => setFilter("status", x)} options={STATUSES.map((s) => [s, STATUS_LABEL[s]])} />
          <Select id="filter-priority" label="Priority" value={v("priority")} onChange={(x) => setFilter("priority", x)} options={["P1", "P2", "P3", "P4"].map((p) => [p, p])} />
          <Select id="filter-category" label="Category" value={v("category")} onChange={(x) => setFilter("category", x)} options={(categories.data ?? []).map((c) => [c, titleCase(c)])} />
          <Select id="filter-service" label="Service" value={v("service")} onChange={(x) => setFilter("service", x)} options={(services.data ?? []).map((s) => [s.name, s.name])} />
          <Select id="filter-technician" label="Technician" value={v("technician")} onChange={(x) => setFilter("technician", x)} options={(technicians.data ?? []).map((t) => [t.id, `${t.id} ${t.name}`])} />
          <Select id="filter-sla" label="SLA status" value={v("sla")} onChange={(x) => setFilter("sla", x)} options={SLA_OPTIONS as [string, string][]} />
          <label className="grid gap-1 text-xs text-fg-3">
            Created from
            <input id="filter-from" type="date" className="field py-1.5 text-[13px] text-fg" value={v("from")} onChange={(e) => setFilter("from", e.target.value)} />
          </label>
          <label className="grid gap-1 text-xs text-fg-3">
            Created to
            <input id="filter-to" type="date" className="field py-1.5 text-[13px] text-fg" value={v("to")} onChange={(e) => setFilter("to", e.target.value)} />
          </label>
        </div>
      </section>

      <section className="card px-5 py-3">
        {isPending && <p className="py-2 text-fg-2">Loading incidents</p>}
        {error && <p role="alert" className="py-2 text-red">{error.message}</p>}
        {data && <p className="label pb-1">{rows.length} {rows.length === 1 ? "incident" : "incidents"}</p>}
        {data && rows.length === 0 && <p className="py-2 text-[13px] text-fg-2">No incidents match these filters.</p>}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[13px]">
              <thead className="text-xs text-fg-3">
                <tr className="border-b border-line">
                  {["Incident", "Priority", "Summary", "Service", "Status", "Technician", "SLA"].map((h) => (
                    <th key={h} className="py-2 pr-4 font-medium last:pr-0 last:text-right">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, limit).map((incident) => (
                  <tr key={incident.id} className="border-b border-line last:border-0 hover:bg-raise/50">
                    <td className="py-2.5 pr-4 font-mono text-xs">
                      <Link className="underline-offset-2 hover:underline" to={`/admin/incidents/${incident.id}`}>{incident.id}</Link>
                    </td>
                    <td className="py-2.5 pr-4"><PriorityTag priority={incident.priority} /></td>
                    <td className="py-2.5 pr-4">{headline(incident.description)}</td>
                    <td className="py-2.5 pr-4 text-fg-2">{incident.service}</td>
                    <td className="py-2.5 pr-4 text-fg-2">{STATUS_LABEL[incident.status]}</td>
                    <td className="py-2.5 pr-4 font-mono text-xs text-fg-2">{incident.technician?.id ?? "None"}</td>
                    <td className="py-2.5 text-right"><SlaBrief incident={incident} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > limit && (
          <button className="btn mt-3 mb-1 text-[13px]" onClick={() => setLimit(limit + PAGE_SIZE)}>Show more</button>
        )}
      </section>
    </main>
  );
}
