import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { PriorityTag } from "../../components/IncidentBits";
import { STATUS_LABEL } from "../../lib/format";

const TICK = { fill: "var(--color-fg-2)", fontSize: 12 };
const BAR = "var(--color-fg-2)";
const AT_CAPACITY = "var(--color-amber)";

interface TipProps {
  active?: boolean;
  payload?: { payload: { tip: string; tipValue: string } }[];
}

function ChartTip({ active, payload }: TipProps) {
  if (!active || !payload?.[0]) return null;
  const { tip, tipValue } = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-raise px-2.5 py-1.5 text-xs">
      <p className="text-fg-2">{tip}</p>
      <p className="font-mono font-medium text-fg">{tipValue}</p>
    </div>
  );
}

function Panel({ title, finding, table, children, className = "" }: { title: string; finding: string; table: [string, string][]; children: ReactNode; className?: string }) {
  return (
    <section className={`card min-w-0 px-5 py-4 ${className}`}>
      <h2 className="text-[15px] font-medium">{title}</h2>
      <p className="mb-3 text-[13px] text-fg-2">{finding}</p>
      {children}
      <details className="mt-2 text-[13px]">
        <summary className="cursor-pointer text-xs text-fg-3 hover:text-fg-2">View as table</summary>
        <table className="mt-2 w-full">
          <tbody>
            {table.map(([name, value]) => (
              <tr key={name} className="border-b border-line last:border-0">
                <td className="py-1 text-fg-2">{name}</td>
                <td className="py-1 text-right font-mono text-xs">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function Metric({ label, value, tone, to }: { label: string; value: number; tone?: string; to?: string }) {
  const body = (
    <>
      <span className="block text-xs text-fg-3">{label}</span>
      <span className={`mt-0.5 block font-mono text-[28px] leading-tight font-medium tracking-tight tabular-nums ${tone ?? ""}`}>{value}</span>
    </>
  );
  return to ? <Link to={to} className="rounded-lg hover:opacity-80">{body}</Link> : <div>{body}</div>;
}

const shortDate = (iso: string) => new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });

function Clusters() {
  const { data, error } = useQuery({ queryKey: ["admin", "clusters"], queryFn: api.admin.clusters, refetchInterval: 30000 });
  return (
    <section className="card min-w-0 px-5 py-4 xl:col-span-5">
      <h2 className="text-[15px] font-medium">Possible duplicates</h2>
      <p className="mb-3 text-[13px] text-fg-2">
        {error
          ? error.message
          : !data
            ? "Loading"
            : data.length
              ? `${data.length} ${data.length === 1 ? "group" : "groups"} of open incidents that look like the same problem.`
              : "No open incidents look like duplicates of each other."}
      </p>
      {data && data.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {data.map((cluster) => (
            <li key={cluster.incidents.map((i) => i.id).join()} className="rounded-lg border border-line px-3.5 py-3">
              <p className="text-xs text-fg-3">
                {cluster.service} · {cluster.incidents.length} incidents
              </p>
              <ul className="mt-1.5 grid gap-1.5 text-[13px]">
                {cluster.incidents.map((incident) => (
                  <li key={incident.id} className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2">
                    <PriorityTag priority={incident.priority} />
                    <span className="min-w-0">
                      <Link to={`/admin/incidents/${incident.id}`} className="font-mono text-xs underline-offset-2 hover:underline">
                        {incident.id}
                      </Link>{" "}
                      <span className="text-fg-2">{incident.description}</span>{" "}
                      <span className="text-xs text-fg-3">({STATUS_LABEL[incident.status]})</span>
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Overview() {
  const { data, isPending, error } = useQuery({ queryKey: ["admin", "overview"], queryFn: api.admin.overview, refetchInterval: 15000 });
  if (isPending) return <p className="p-4 text-fg-2">Loading overview</p>;
  if (error) return <p role="alert" className="p-4 text-red">{error.message}</p>;

  const workload = data.technicianWorkload.map((t) => {
    const full = t.active >= t.max;
    return { ...t, full, bar: t.active, label: `${t.active} of ${t.max}${full ? " · full" : ""}`, tip: t.name, tipValue: `${t.active} of ${t.max} active` };
  });
  const atCapacity = workload.filter((t) => t.full);
  const services = data.serviceAnalysis.map((s) => ({ ...s, tip: s.service, tipValue: `${s.incidents} incidents` }));
  const daily = data.dailyCreated.map((d) => ({ ...d, day: shortDate(d.date), tip: shortDate(d.date), tipValue: `${d.incidents} created` }));
  const recent = daily.reduce((sum, d) => sum + d.incidents, 0);
  const busiest = daily.reduce((top, d) => (d.incidents > top.incidents ? d : top), daily[0]);
  const maxWorkload = Math.max(...workload.map((t) => Math.max(t.max, t.active)));

  return (
    <main className="grid grid-cols-[minmax(0,1fr)] gap-2.5 xl:grid-cols-5">
      <section aria-label="Incident overview" className="card flex flex-wrap items-center gap-x-10 gap-y-3 px-6 py-5 xl:col-span-5">
        <div className="mr-4">
          <span className="block text-[13px] text-fg-2">Open incidents</span>
          <span className="block font-mono text-[56px] leading-none font-medium tracking-[-0.04em] tabular-nums">{data.open}</span>
        </div>
        <Metric label="Critical open" value={data.critical} />
        <Metric label="SLA violations" value={data.slaViolations} tone={data.slaViolations > 0 ? "text-red" : ""} to="/admin/sla-violations" />
        <Metric label="Resolved" value={data.resolved} />
        <Metric label="Total" value={data.total} />
      </section>

      <Panel
        className="xl:col-span-3"
        title="Technician workload"
        finding={atCapacity.length ? `${atCapacity.map((t) => t.name).join(", ")} ${atCapacity.length === 1 ? "is" : "are"} at full capacity.` : "Every technician has spare capacity."}
        table={workload.map((t) => [`${t.id} ${t.name}`, `${t.active} of ${t.max}`])}
      >
        <ResponsiveContainer width="100%" height={workload.length * 38 + 4}>
          <BarChart layout="vertical" data={workload} margin={{ top: 0, right: 76, bottom: 0, left: 0 }}>
            <XAxis type="number" hide domain={[0, maxWorkload]} />
            <YAxis type="category" dataKey="name" width={100} interval={0} axisLine={false} tickLine={false} tick={TICK} />
            <Tooltip cursor={{ fill: "var(--color-raise)" }} content={<ChartTip />} />
            <Bar dataKey="bar" barSize={12} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {workload.map((t) => <Cell key={t.id} fill={t.full ? AT_CAPACITY : BAR} />)}
              <LabelList dataKey="label" position="right" fill="var(--color-fg)" fontSize={12} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel
        className="xl:col-span-2"
        title="Service analysis"
        finding={services[0] ? `${services[0].service} has the most incidents.` : "No incidents yet."}
        table={services.map((s) => [s.service, String(s.incidents)])}
      >
        <ResponsiveContainer width="100%" height={services.length * 34 + 4}>
          <BarChart layout="vertical" data={services} margin={{ top: 0, right: 32, bottom: 0, left: 0 }}>
            <XAxis type="number" hide domain={[0, "dataMax"]} />
            <YAxis type="category" dataKey="service" width={100} interval={0} axisLine={false} tickLine={false} tick={TICK} />
            <Tooltip cursor={{ fill: "var(--color-raise)" }} content={<ChartTip />} />
            <Bar dataKey="incidents" fill={BAR} barSize={12} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              <LabelList dataKey="incidents" position="right" fill="var(--color-fg)" fontSize={12} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel
        className="xl:col-span-5"
        title="Incidents created, last 14 days"
        finding={`${recent} created in 14 days. The busiest day was ${busiest.day}, with ${busiest.incidents}.`}
        table={daily.map((d) => [d.day, String(d.incidents)])}
      >
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={daily} margin={{ top: 4, right: 0, bottom: 0, left: -24 }}>
            <CartesianGrid vertical={false} stroke="var(--color-line)" />
            <XAxis dataKey="day" axisLine={false} tickLine={false} tick={TICK} interval="preserveStartEnd" minTickGap={24} />
            <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={TICK} />
            <Tooltip cursor={{ fill: "var(--color-raise)" }} content={<ChartTip />} />
            <Bar dataKey="incidents" fill={BAR} maxBarSize={22} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Clusters />
    </main>
  );
}
