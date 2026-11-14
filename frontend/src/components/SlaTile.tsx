import type { Incident } from "../api/types";
import { headline, PRIORITY_LABEL, time } from "../lib/format";
import { clock, remainingSeconds, shortDuration, slaState, useNow } from "../lib/sla";
import { PriorityTag } from "./IncidentBits";

function responseSummary({ sla, createdAt }: Incident): string {
  if (!sla.respondedAt) return `Response due ${time(sla.responseDeadline)}`;
  const taken = (Date.parse(sla.respondedAt) - Date.parse(createdAt)) / 1000;
  const late = Date.parse(sla.respondedAt) > Date.parse(sla.responseDeadline);
  return `Response ${late ? "late at" : "met in"} ${shortDuration(taken)}`;
}

export function SlaTile({ incident }: { incident: Incident }) {
  const now = useNow();
  const { sla } = incident;
  const state = slaState(sla, now);
  const left = remainingSeconds(sla, now);
  const stopped = state === "done" || state === "paused";
  const caption = stopped ? "SLA clock" : state === "breached" ? "Overdue by" : "Left to resolve";
  const value = state === "paused" ? "Paused" : state === "done" ? "Stopped" : clock(left);
  const detail =
    state === "done"
      ? left >= 0
        ? `Resolved with ${clock(left)} to spare`
        : `Resolved ${clock(left)} late`
      : state === "paused"
        ? `${clock(left)} remaining`
        : `Due ${time(sla.resolutionDeadline)}`;
  const progress = Math.max(0, Math.min(100, (100 * left) / sla.resolutionTargetSeconds));

  return (
    <section data-state={state} className="sla-tile flex flex-wrap justify-between gap-x-8 gap-y-[18px] rounded-[14px] px-[22px] py-5">
      <div className="flex min-w-0 flex-[1_1_280px] flex-col gap-2">
        <p className="text-[13px] text-fg-2">
          <PriorityTag priority={incident.priority} /> <span className="ml-1">{PRIORITY_LABEL[incident.priority]}</span> ·{" "}
          <span className="font-mono">{incident.id}</span>
        </p>
        <h1 className="text-[clamp(23px,2.7vw,32px)] leading-[1.12] font-medium tracking-[-0.022em] text-balance wrap-anywhere">
          {headline(incident.description)}
        </h1>
        <p className="text-[13px] text-fg-2">
          {incident.service} · reported by <span className="font-mono">{incident.reporter.id}</span>
        </p>
      </div>
      <div className="min-w-0 sm:text-right" role="timer" aria-label={`${caption} ${value}`}>
        <p className="mb-1 text-[13px]">{caption}</p>
        <p
          className={`font-mono leading-none font-medium tabular-nums ${
            stopped ? "text-[clamp(32px,4vw,44px)] tracking-[-0.03em]" : "text-[clamp(54px,7.4vw,88px)] tracking-[-0.05em]"
          }`}
        >
          {value}
        </p>
        <p className="mt-2 text-xs">
          {detail} · {responseSummary(incident)}
        </p>
      </div>
      <div className="h-[3px] flex-[1_1_100%] overflow-hidden rounded-sm bg-white/15">
        <span className="block h-full bg-fg" style={{ width: `${progress}%` }} />
      </div>
    </section>
  );
}
