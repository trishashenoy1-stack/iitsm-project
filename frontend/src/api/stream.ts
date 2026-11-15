import { tokenStore } from "./client";
import type { AppNotification } from "./types";

interface SseFrame {
  id: string | null;
  data: string;
}

/** Incremental parser: network chunks can split a frame anywhere. */
export function createSseParser(onFrame: (frame: SseFrame) => void) {
  let buffer = "";
  return (chunk: string) => {
    // Normalise the whole buffer: a CRLF can be split across two chunks.
    buffer = (buffer + chunk).replace(/\r\n/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let id: string | null = null;
      const data: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("id:")) id = line.slice(3).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (data.length) onFrame({ id, data: data.join("\n") });
    }
  };
}

const MAX_RETRY_MS = 30000;
// The server sends a keep-alive every 15 s. Three missed in a row means the connection
// is dead even if the browser hasn't noticed (sleep, Wi-Fi change, a proxy that keeps
// the browser side open after the server went away), so drop it and reconnect.
const SILENCE_LIMIT_MS = 45000;

interface StreamHandlers {
  onConnected: () => void;
  onNotification: (notification: AppNotification) => void;
}

/**
 * Opens the notification stream and keeps it open.
 * Uses fetch because the browser's EventSource can't send an Authorization header.
 * Returns a function that closes it.
 */
export function openNotificationStream({ onConnected, onNotification }: StreamHandlers): () => void {
  const controller = new AbortController();
  let lastEventId: string | null = null;
  let retryMs = 1000;

  async function connect() {
    while (!controller.signal.aborted) {
      // One controller per attempt, so the watchdog can drop this connection only.
      const attempt = new AbortController();
      const stop = () => attempt.abort();
      controller.signal.addEventListener("abort", stop);
      let watchdog = setTimeout(stop, SILENCE_LIMIT_MS);
      const heard = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(stop, SILENCE_LIMIT_MS);
      };
      try {
        const token = tokenStore.get();
        const response = await fetch("/api/notifications/stream", {
          signal: attempt.signal,
          headers: {
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
          },
        });
        if (response.status === 401 || response.status === 403) return;
        if (response.ok && response.body) {
          retryMs = 1000;
          onConnected();
          const decoder = new TextDecoder();
          const parse = createSseParser((frame) => {
            if (frame.id) lastEventId = frame.id;
            onNotification(JSON.parse(frame.data) as AppNotification);
          });
          const reader = response.body.getReader();
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            heard();
            parse(decoder.decode(value, { stream: true }));
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      } finally {
        clearTimeout(watchdog);
        controller.signal.removeEventListener("abort", stop);
      }
      await new Promise((resolve) => setTimeout(resolve, retryMs));
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    }
  }

  void connect();
  return () => controller.abort();
}
