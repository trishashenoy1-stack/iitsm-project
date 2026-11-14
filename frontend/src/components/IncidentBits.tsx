import type { Incident, Priority, Status } from "../api/types";
import { STATUS_LABEL } from "../lib/format";
import { remainingSeconds, shortDuration, slaState, useNow, type SlaState } from "../lib/sla";

export function PriorityTag({ priority }: { priority: Priority }) {
  const strong = priority === "P1";
  return (
    <span
      className={`rounded border px-[5px] font-mono text-[11px] leading-4 font-medium ${
        strong ? "border-fg bg-fg text-on-paper" : "border-line text-fg-2"
      }`}
    >
      {priority}
    </span>
  );
}

const TIME_COLOR: Record<SlaState, string> = {
  ok: "text-fg-2",
  paused: "text-fg-2",
  done: "text-fg-2",
  warning: "text-amber",
  breached: "text-red",
};

export function SlaBrief({ incident }: { incident: Incident }) {
  const now = useNow();
  const state = slaState(incident.sla, now);
  const left = remainingSeconds(incident.sla, now);
  const text =
    state === "done" ? "Done" : state === "paused" ? "Paused" : state === "breached" ? `${shortDuration(left)} over` : shortDuration(left);
  return <span className={`text-right font-mono text-xs font-medium ${TIME_COLOR[state]}`}>{text}</span>;
}

const STEPS: Status[] = ["NEW", "CLASSIFIED", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "VERIFIED", "CLOSED"];

export function Lifecycle({ status }: { status: Status }) {
  const position = status === "AWAITING_INFO" || status === "REOPENED" ? "IN_PROGRESS" : status;
  const at = STEPS.indexOf(position);
  return (
    <ol aria-label="Lifecycle" className="card flex flex-wrap items-center gap-y-1 px-3.5 py-2.5 text-xs text-fg-3">
      {STEPS.map((step, index) => (
        <li key={step} className="flex items-center">
          {index > 0 && <span className="mx-[7px] h-px w-3.5 bg-line" aria-hidden="true" />}
          {index === at ? (
            <span aria-current="step" className="rounded-[5px] bg-fg px-2 py-px font-medium text-on-paper">
              {STATUS_LABEL[status]}
            </span>
          ) : (
            <span className={index < at ? "text-fg-2" : undefined}>{STATUS_LABEL[step]}</span>
          )}
        </li>
      ))}
    </ol>
  );
}
