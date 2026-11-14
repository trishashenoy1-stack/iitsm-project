import { useEffect, useState } from "react";
import type { Sla } from "../api/types";

export type SlaState = "ok" | "warning" | "breached" | "paused" | "done";

// SLATracker in domain/sla.py warns once 80% of the target has been used.
const WARNING_REMAINING_RATIO = 0.2;

export function remainingSeconds(sla: Sla, now: number): number {
  if (sla.frozenRemainingSeconds !== null) return sla.frozenRemainingSeconds;
  return Math.floor((Date.parse(sla.resolutionDeadline) - now) / 1000);
}

export function slaState(sla: Sla, now: number): SlaState {
  if (sla.resolvedAt) return "done";
  if (sla.isPaused) return "paused";
  const left = remainingSeconds(sla, now);
  if (left <= 0) return "breached";
  return left / sla.resolutionTargetSeconds <= WARNING_REMAINING_RATIO ? "warning" : "ok";
}

export function clock(seconds: number): string {
  const total = Math.abs(seconds);
  const pad = (n: number) => String(n).padStart(2, "0");
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

export function shortDuration(seconds: number): string {
  const total = Math.abs(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  return total < 60 ? "<1m" : `${m}m`;
}

/** Re-renders the calling component on an interval. Keep it in leaf components. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
