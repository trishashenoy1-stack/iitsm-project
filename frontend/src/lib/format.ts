import type { Level, Priority, Status } from "../api/types";

export const STATUS_LABEL: Record<Status, string> = {
  NEW: "New",
  CLASSIFIED: "Classified",
  ASSIGNED: "Assigned",
  ACKNOWLEDGED: "Acknowledged",
  IN_PROGRESS: "In progress",
  AWAITING_INFO: "Awaiting info",
  RESOLVED: "Resolved",
  VERIFIED: "Verified",
  CLOSED: "Closed",
  REOPENED: "Reopened",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  P1: "Critical",
  P2: "High",
  P3: "Medium",
  P4: "Low",
};

export const LEVEL_LABEL: Record<Level, string> = { LOW: "Low", MEDIUM: "Medium", HIGH: "High" };

export function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** P1's Incident has no title field, so the first sentence acts as the headline. */
export function headline(description: string): string {
  const first = description.split(/(?<=[.!?])\s/)[0].replace(/\.$/, "");
  return first.length > 90 ? `${first.slice(0, 87)}...` : first;
}

export function titleCase(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}
