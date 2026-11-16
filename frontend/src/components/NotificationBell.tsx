import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { openNotificationStream } from "../api/stream";
import { time } from "../lib/format";

const usingMock = import.meta.env.VITE_USE_MOCK !== "false";

export function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  // The mock has no stream, so it polls. The real API pushes over SSE.
  const { data = [] } = useQuery({
    queryKey: ["notifications"],
    queryFn: api.listNotifications,
    refetchInterval: usingMock ? 5000 : false,
  });
  const unread = data.filter((n) => !n.read).length;

  useEffect(() => {
    if (usingMock) return;
    const refresh = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
    // Refreshing on connect covers anything sent between the first load and the stream opening.
    return openNotificationStream({ onConnected: refresh, onNotification: refresh });
  }, [queryClient]);

  const markRead = useMutation({
    mutationFn: api.markNotificationsRead,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function toggle() {
    if (!open && unread > 0) markRead.mutate();
    setOpen(!open);
  }

  return (
    <div className="relative" ref={root}>
      <button
        onClick={toggle}
        aria-expanded={open}
        aria-label={`Notifications, ${unread} unread`}
        className="relative grid size-[30px] place-items-center rounded-lg text-fg-2 hover:bg-raise hover:text-fg"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="size-[17px]" aria-hidden="true">
          <path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7 2.5 7h-17S6 15 6 9" />
          <path d="M10 20a2.2 2.2 0 0 0 4 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-px top-0 h-[15px] min-w-[15px] rounded-full bg-lime px-[3px] font-mono text-[10px] leading-[15px] font-medium text-on-lime">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute -left-16 top-9 z-10 w-[min(310px,calc(100vw-40px))] lg:left-0 rounded-xl border border-line bg-raise p-1.5">
          {data.length === 0 && <p className="px-2.5 py-2 text-[13px] text-fg-2">You're all caught up.</p>}
          <ul>
            {data.map((n) => (
              <li key={n.id} className="px-2.5 py-2 text-[13px]">
                {n.message}
                <time className="block font-mono text-xs text-fg-3">{time(n.createdAt)}</time>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
