import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { STATUS_LABEL } from "../../lib/format";

const PAGE_SIZE = 40;

const stamp = (iso: string) =>
  new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

export function AuditLog() {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data, isPending, error } = useQuery({ queryKey: ["admin", "audit"], queryFn: api.admin.audit, refetchInterval: 10000 });

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data ?? [];
    return (data ?? []).filter((e) => `${e.incidentId} ${e.actorId} ${e.action} ${e.description}`.toLowerCase().includes(q));
  }, [data, query]);

  return (
    <main className="card px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium tracking-tight">Audit log</h1>
          <p className="text-[13px] text-fg-2">Every action on every incident. Entries can't be edited.</p>
        </div>
        <input
          id="audit-search"
          aria-label="Search the audit log"
          className="field max-w-[280px]"
          placeholder="Search by incident, user or action"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setLimit(PAGE_SIZE);
          }}
        />
      </div>
      {isPending && <p className="mt-3 text-fg-2">Loading audit log</p>}
      {error && <p role="alert" className="mt-3 text-red">{error.message}</p>}
      {data && rows.length === 0 && <p className="mt-3 text-[13px] text-fg-2">No entries match that search.</p>}
      {rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <thead className="text-xs text-fg-3">
              <tr className="border-b border-line">
                {["Time", "User", "Action", "Incident", "State change", "Description"].map((h) => (
                  <th key={h} className="py-2 pr-4 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, limit).map((entry, index) => (
                <tr key={`${entry.incidentId}-${entry.at}-${index}`} className="border-b border-line last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs whitespace-nowrap text-fg-2">{stamp(entry.at)}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{entry.actorId}</td>
                  <td className="py-2 pr-4 font-mono text-xs text-fg-2">{entry.action}</td>
                  <td className="py-2 pr-4 font-mono text-xs"><Link className="underline-offset-2 hover:underline" to={`/admin/incidents/${entry.incidentId}`}>{entry.incidentId}</Link></td>
                  <td className="py-2 pr-4 whitespace-nowrap text-fg-2">
                    {entry.newStatus ? `${entry.previousStatus ? STATUS_LABEL[entry.previousStatus] : "None"} to ${STATUS_LABEL[entry.newStatus]}` : ""}
                  </td>
                  <td className="py-2 wrap-anywhere">{entry.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > limit && <button className="btn mt-3 text-[13px]" onClick={() => setLimit(limit + PAGE_SIZE)}>Show more</button>}
    </main>
  );
}
