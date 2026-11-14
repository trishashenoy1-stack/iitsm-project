import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Incident, Status } from "../../api/types";
import { useToast } from "../../components/Toast";
import { headline, time } from "../../lib/format";
import { slaState, useNow } from "../../lib/sla";

function plainStatus(incident: Incident): string {
  const name = incident.technician?.name ?? "A technician";
  const text: Record<Status, string> = {
    NEW: "We've received this and are finding the right technician.",
    CLASSIFIED: "We've received this and are finding the right technician.",
    ASSIGNED: `${name} has been assigned to this.`,
    ACKNOWLEDGED: `${name} has picked this up.`,
    IN_PROGRESS: `${name} is working on this.`,
    AWAITING_INFO: `${name} needs more information from you.`,
    RESOLVED: `${name} says this is fixed. Check it and let us know.`,
    VERIFIED: "You confirmed the fix. This will be closed soon.",
    CLOSED: "This incident is closed.",
    REOPENED: `You said it's still broken, so it's back with ${name}.`,
  };
  return text[incident.status];
}

const JOURNEY = ["Reported", "Assigned", "Being fixed", "Resolved", "Closed"];
const JOURNEY_STEP: Record<Status, number> = {
  NEW: 0, CLASSIFIED: 0, ASSIGNED: 1, ACKNOWLEDGED: 2, IN_PROGRESS: 2, AWAITING_INFO: 2, REOPENED: 2, RESOLVED: 3, VERIFIED: 3, CLOSED: 4,
};

function Expected({ incident }: { incident: Incident }) {
  const now = useNow(30000);
  const state = slaState(incident.sla, now);
  if (state === "done") return null;
  if (state === "paused") return <p className="mt-1 text-[13px] text-fg-2">The timer is paused until you reply.</p>;
  if (state === "breached") return <p className="mt-1 text-[13px] text-amber">This is taking longer than expected.</p>;
  const due = new Date(incident.sla.resolutionDeadline);
  const today = due.toDateString() === new Date(now).toDateString();
  return (
    <p className="mt-1 text-[13px] text-fg-2">
      Expected by {today ? time(incident.sla.resolutionDeadline) : due.toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit", hour12: false })}
    </p>
  );
}

export function EmployeeIncident() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [reply, setReply] = useState("");
  const [extra, setExtra] = useState("");
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<{ area: string; message: string } | null>(null);

  const { data: incident, isPending, error: loadError } = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.getIncident(id),
    refetchInterval: 5000,
  });

  const mutation = useMutation({
    mutationFn: ({ run }: { run: () => Promise<Incident>; area: string; done: string }) => run(),
    onSuccess: (updated, { done }) => {
      queryClient.setQueryData(["incident", id], updated);
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      setError(null);
      toast(done);
    },
    onError: (e, { area }) => setError({ area, message: e.message }),
  });

  if (isPending) return <p className="text-fg-2">Loading incident</p>;
  if (loadError) return <p role="alert" className="text-red">{loadError.message}</p>;

  const areaError = (area: string) =>
    error?.area === area && <p role="alert" className="mt-1.5 text-[13px] text-red">{error.message}</p>;
  const step = JOURNEY_STEP[incident.status];
  const canGiveFeedback = ["RESOLVED", "VERIFIED", "CLOSED"].includes(incident.status) && !incident.feedback;

  function requireText(area: string, text: string, message: string) {
    if (text.trim()) return true;
    setError({ area, message });
    return false;
  }

  return (
    <main className="grid max-w-[720px] gap-4">
      <Link to="/employee" className="text-[13px] text-fg-2 hover:text-fg">Back to your incidents</Link>

      <section className="py-1">
        <p className="font-mono text-xs text-fg-2">{incident.id} · {incident.service}</p>
        <h1 className="mt-1.5 text-[32px] leading-[1.15] font-medium tracking-[-0.022em] text-balance wrap-anywhere">{headline(incident.description)}</h1>
        <p className="mt-3 text-base">{plainStatus(incident)}</p>
        <Expected incident={incident} />
      </section>

      <ol aria-label="Progress" className="grid grid-cols-5 gap-1.5">
        {JOURNEY.map((label, index) => (
          <li key={label} aria-current={index === step ? "step" : undefined}>
            <span className={`block h-1 rounded-full ${index <= step ? "bg-fg" : "bg-raise"}`} />
            <span className={`mt-1.5 block text-xs ${index === step ? "font-medium text-fg" : "text-fg-3"}`}>{label}</span>
          </li>
        ))}
      </ol>

      {incident.status === "AWAITING_INFO" && (
        <section className="card px-6 py-5">
          <h2 className="text-base font-medium">{incident.technician?.name ?? "Your technician"} asked</h2>
          <p className="mt-1 text-fg-2 wrap-anywhere">{incident.infoRequest ?? "Can you share more details?"}</p>
          <textarea id="reply" aria-label="Your reply" className="field mt-3 block min-h-[84px] resize-y" placeholder="Version 16.2, installed last week." value={reply} onChange={(e) => setReply(e.target.value)} />
          {areaError("reply")}
          <button
            className="btn btn-go mt-3"
            disabled={mutation.isPending}
            onClick={() => {
              if (!requireText("reply", reply, "Write your reply first.")) return;
              mutation.mutate(
                { run: () => api.performAction(id, "provide_info", reply.trim()), area: "reply", done: "Reply sent" },
                { onSuccess: () => setReply("") },
              );
            }}
          >
            Send reply
          </button>
        </section>
      )}

      {incident.resolution && (
        <section className="card px-6 py-5">
          <h2 className="text-base font-medium">How it was fixed</h2>
          <p className="mt-1 text-fg-2 wrap-anywhere">{incident.resolution}</p>
          {incident.status === "RESOLVED" && (
            <>
              <div className="mt-4 flex flex-wrap gap-2">
                <button className="btn btn-go" disabled={mutation.isPending} onClick={() => mutation.mutate({ run: () => api.performAction(id, "verify"), area: "verify", done: "Thanks for confirming" })}>
                  It's fixed
                </button>
                <button className="btn" disabled={mutation.isPending} onClick={() => mutation.mutate({ run: () => api.performAction(id, "reject_resolution"), area: "verify", done: "Sent back to the technician" })}>
                  It's still broken
                </button>
              </div>
              {areaError("verify")}
            </>
          )}
        </section>
      )}

      {canGiveFeedback && (
        <section className="card px-6 py-5">
          <h2 className="text-base font-medium">How did we do?</h2>
          <div role="radiogroup" aria-label="Rating from 1 to 5" className="mt-3 flex gap-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                role="radio"
                aria-checked={rating === n}
                aria-label={`${n} out of 5`}
                onClick={() => setRating(n)}
                className={`size-10 rounded-[10px] border font-mono ${rating === n ? "border-lime text-fg" : "border-line text-fg-2 hover:border-fg-3"}`}
              >
                {n}
              </button>
            ))}
          </div>
          <textarea id="feedback" aria-label="Comment, optional" className="field mt-3 block min-h-[64px] resize-y" placeholder="Anything we could have done better? (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          {areaError("feedback")}
          <button
            className="btn mt-3"
            disabled={mutation.isPending}
            onClick={() => {
              if (!rating) {
                setError({ area: "feedback", message: "Choose a rating first." });
                return;
              }
              mutation.mutate({ run: () => api.submitFeedback(id, rating, comment), area: "feedback", done: "Thanks for your feedback" });
            }}
          >
            Send feedback
          </button>
        </section>
      )}

      {incident.feedback && (
        <p className="text-[13px] text-fg-2">You rated this {incident.feedback.rating} out of 5.</p>
      )}

      {incident.status !== "CLOSED" && incident.status !== "AWAITING_INFO" && (
        <section className="card px-6 py-5">
          <h2 className="text-base font-medium">Add more information</h2>
          <textarea id="extra" aria-label="More information" className="field mt-3 block min-h-[64px] resize-y" placeholder="It also fails on the mobile site." value={extra} onChange={(e) => setExtra(e.target.value)} />
          {areaError("extra")}
          <button
            className="btn mt-3"
            disabled={mutation.isPending}
            onClick={() => {
              if (!requireText("extra", extra, "Write the extra information first.")) return;
              mutation.mutate(
                { run: () => api.addInformation(id, extra.trim()), area: "extra", done: "Information added" },
                { onSuccess: () => setExtra("") },
              );
            }}
          >
            Add information
          </button>
        </section>
      )}

      <section className="px-1 py-2">
        <h2 className="label">What's happened</h2>
        <ul className="mt-2 grid gap-[7px]">
          {incident.history.map((entry, index) => (
            <li key={`${entry.at}-${index}`} className="grid grid-cols-[44px_minmax(0,1fr)] gap-2.5 text-[13px]">
              <time className="font-mono text-xs leading-5 text-fg-3">{time(entry.at)}</time>
              <span className="wrap-anywhere">{entry.description}</span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
