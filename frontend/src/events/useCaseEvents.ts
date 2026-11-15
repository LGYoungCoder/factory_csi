import { useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { keys } from "@/api/queries";
import { initialLive, liveReducer, REFRESH_TYPES, KNOWN_TYPES } from "./reducer";

/** EventSource with reconnect from the last seq; refetches the case snapshot on relevant events. */
export function useCaseEvents(caseId: string | null) {
  const [state, dispatch] = useReducer(liveReducer, initialLive);
  const qc = useQueryClient();
  const lastSeq = useRef(0);

  useEffect(() => {
    dispatch({ type: "reset" });
    lastSeq.current = 0;
    if (!caseId) return;
    let es: EventSource | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let refetchTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleRefetch = () => {
      if (refetchTimer) return;
      refetchTimer = setTimeout(() => {
        refetchTimer = null;
        qc.invalidateQueries({ queryKey: keys.case(caseId) });
        qc.invalidateQueries({ queryKey: keys.mcp(caseId) });
      }, 250);
    };

    const connect = () => {
      es = new EventSource(`/api/cases/${caseId}/events?after=${lastSeq.current}`);
      const handler = (ev: MessageEvent) => {
        attempt = 0;
        const data = JSON.parse(ev.data);
        const seq = Number(data._seq ?? ev.lastEventId);
        lastSeq.current = Math.max(lastSeq.current, seq);
        dispatch({ type: "event", event: { seq, type: ev.type, payload: data, ts: data._ts } });
        if (REFRESH_TYPES.has(ev.type) || ev.type === "mcp_call") scheduleRefetch();
        if (ev.type === "completed") {
          closed = true;
          es?.close();
        }
      };
      KNOWN_TYPES.forEach((t) => es!.addEventListener(t, handler as EventListener));
      es.onerror = () => {
        es?.close();
        if (closed) return;
        const delay = [1000, 2000, 4000, 8000, 16000, 30000][Math.min(attempt, 5)];
        attempt += 1;
        timer = setTimeout(() => {
          scheduleRefetch();
          connect();
        }, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      es?.close();
      if (timer) clearTimeout(timer);
      if (refetchTimer) clearTimeout(refetchTimer);
    };
  }, [caseId, qc]);

  return state;
}
