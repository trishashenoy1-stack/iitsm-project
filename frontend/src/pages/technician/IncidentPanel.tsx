import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import type { Incident, IncidentAction } from "../../api/types";
import { Lifecycle } from "../../components/IncidentBits";
import { SlaTile } from "../../components/SlaTile";
import { useToast } from "../../components/Toast";
import { LEVEL_LABEL, time, titleCase } from "../../lib/format";

type Mode = "note" | "ask" | "resolve";

const MODES: Record<Mode, { tab: string; placeholder: string; submit: string; empty: string }> = {
  note: { tab: "Note", placeholder: "What did you check or change?", submit: "Add note", empty: "Write the note first." },
  ask: { tab: "Ask reporter", placeholder: "What do you need from the reporter?", submit: "Send request", empty: "Write your question first." },
  resolve: { tab: "Resolution", placeholder: "What fixed it, and how can the reporter confirm?", submit: "Mark resolved", empty: "Add the resolution details before resolving." },
};

const NEXT_STEP: Partial<Record<Incident["status"], { action: IncidentAction; label: string }>> = {
  ASSIGNED: { action: "acknowledge", label: "Acknowledge" },
  ACKNOWLEDGED: { action: "start_work", label: "Start work" },
  REOPENED: { action: "start_work", label: "Restart work" },
  VERIFIED: { action: "close", label: "Close incident" },
};

export function IncidentPanel({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("note");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const { data: incident, isPending, error: loadError } = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.getIncident(id),
    refetchInterval: 5000,
  });

  const done = incident?.status === "RESOLVED" || incident?.status === "VERIFIED" || incident?.status === "CLOSED";
  const suggestions = useQuery({
    queryKey: ["suggestions", id],
    queryFn: () => api.suggestions(id),
    enabled: incident !== undefined && !done,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (run: () => Promise<Incident>) => run(),
    onSuccess: (updated) => {
      queryClient.setQueryData(["incident", id], updated);
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => setError(e.message),
  });

  if (isPending) return <p className="p-4 text-fg-2">Loading incident</p>;
  if (loadError) return <p role="alert" className="p-4 text-red">{loadError.message}</p>;

  const modes: Mode[] = incident.status === "IN_PROGRESS" ? ["note", "ask", "resolve"] : ["note"];
  const activeMode = modes.includes(mode) ? mode : "note";
  const next = NEXT_STEP[incident.status];
  const reporter = incident.reporter.id;

  function advance(action: IncidentAction) {
    setError("");
    mutation.mutate(() => api.performAction(id, action));
  }

  function submit() {
    const text = draft.trim();
    if (!text) {
      setError(MODES[activeMode].empty);
      return;
    }
    setError("");
    const run =
      activeMode === "note"
        ? () => api.addNote(id, text)
        : () => api.performAction(id, activeMode === "ask" ? "request_info" : "resolve", text);
    mutation.mutate(run, {
      onSuccess: () => {
        setDraft("");
        setMode("note");
        toast(
          activeMode === "note"
            ? "Note added"
            : activeMode === "ask"
              ? `${reporter} notified. SLA paused.`
              : `${id} resolved. ${reporter} notified.`,
        );
      },
    });
  }

  return (
    <main className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
      <SlaTile incident={incident} />
      <Lifecycle status={incident.status} />

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-2.5 lg:grid-cols-[minmax(0,1fr)_minmax(190px,240px)]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
          {incident.status !== "CLOSED" && <section className="card px-4 py-3.5">
            <div className="mb-2 flex gap-1">
              {modes.map((m) => (
                <button
                  key={m}
                  aria-pressed={m === activeMode}
                  onClick={() => {
                    setMode(m);
                    setError("");
                  }}
                  className={`rounded-[7px] px-2.5 py-1 text-[13px] ${m === activeMode ? "bg-raise text-fg" : "text-fg-2 hover:text-fg"}`}
                >
                  {MODES[m].tab}
                </button>
              ))}
            </div>
            <textarea
              id="incident-composer"
              aria-label={MODES[activeMode].tab}
              className="field block min-h-[74px] resize-y"
              placeholder={MODES[activeMode].placeholder}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                setError("");
              }}
            />
            {error && <p role="alert" className="mt-1.5 text-[13px] text-red">{error}</p>}
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              {next && (
                <button className="btn btn-go" disabled={mutation.isPending} onClick={() => advance(next.action)}>
                  {next.label}
                </button>
              )}
              <button className={`btn ${next ? "" : "btn-go"}`} disabled={mutation.isPending} onClick={submit}>
                {MODES[activeMode].submit}
              </button>
              {incident.status === "AWAITING_INFO" && <span className="text-[13px] text-fg-2">SLA is paused until the reporter answers.</span>}
              {incident.status === "RESOLVED" && <span className="text-[13px] text-fg-2">Waiting for the reporter to verify the fix.</span>}
            </div>
          </section>}

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
        </div>

        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
          <section className="card px-4 py-3.5">
            <h2 className="label">Details</h2>
            <dl className="mt-2 grid gap-[7px] text-[13px]">
              {[
                ["Category", titleCase(incident.category)],
                ["Service", incident.service],
                ["Impact", LEVEL_LABEL[incident.impact]],
                ["Urgency", LEVEL_LABEL[incident.urgency]],
                ["Affected users", String(incident.affectedUsers)],
              ].map(([term, value]) => (
                <div key={term} className="flex justify-between gap-3">
                  <dt className="text-fg-3">{term}</dt>
                  <dd className="text-right wrap-anywhere">{value}</dd>
                </div>
              ))}
            </dl>
          </section>
          {suggestions.data && (
            <section className="card px-4 py-3.5">
              <h2 className="label">Suggested fixes</h2>
              <p className="mt-1 text-xs text-fg-3">
                {suggestions.data.length ? "From similar incidents that were resolved before." : "No similar resolved incidents yet."}
              </p>
              <ul className="mt-2 grid gap-2.5 text-[13px]">
                {suggestions.data.map((s) => (
                  <li key={s.incidentId}>
                    <span className="wrap-anywhere">{s.resolution}</span>
                    <small className="block font-mono text-xs text-fg-3">
                      {s.incidentId} · {Math.round(s.similarity * 100)}% similar
                    </small>
                    {incident.status === "IN_PROGRESS" && (
                      <button
                        className="mt-1 text-xs text-fg-2 underline underline-offset-2 hover:text-fg"
                        onClick={() => {
                          setMode("resolve");
                          setDraft(s.resolution);
                          setError("");
                          document.getElementById("incident-composer")?.focus();
                        }}
                      >
                        Use as resolution
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {incident.possibleDuplicates.length > 0 && (
            <section className="card px-4 py-3.5">
              <h2 className="label">Possible duplicates</h2>
              <ul className="mt-2 grid gap-2 text-[13px]">
                {incident.possibleDuplicates.map((d) => (
                  <li key={d.id}>
                    {d.description}
                    <small className="block font-mono text-xs text-fg-3">
                      {d.id} · {Math.round(d.similarity * 100)}% match
                    </small>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </main>
  );
}
