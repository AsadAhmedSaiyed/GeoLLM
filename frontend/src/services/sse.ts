// Resilient Server-Sent Events (SSE) Client for GeoLLM task streaming.
// Connects to /api/tasks/{task_id}/stream with automatic reconnection and Last-Event-ID tracking.

import { GeoLLMSSEEvent } from '@/types/sse';

export type SSEEventHandler = (event: GeoLLMSSEEvent) => void;
export type SSEErrorHandler = (error: Event | Error) => void;
export type SSECloseHandler = () => void;

export interface TaskStreamSubscription {
  close: () => void;
  isOpen: () => boolean;
  getLastEventId: () => number;
}

export function connectTaskStream(
  taskId: string,
  handlers: {
    onEvent: SSEEventHandler;
    onError?: SSEErrorHandler;
    onClose?: SSECloseHandler;
  },
  initialLastEventId: number = 0
): TaskStreamSubscription {
  let lastEventId = initialLastEventId;
  let eventSource: EventSource | null = null;
  let isManuallyClosed = false;

  const url = `/api/tasks/${encodeURIComponent(taskId)}/stream${
    lastEventId > 0 ? `?last_event_id=${lastEventId}` : ''
  }`;

  try {
    eventSource = new EventSource(url);

    eventSource.onmessage = (e: MessageEvent) => {
      if (isManuallyClosed) return;

      if (e.lastEventId) {
        const parsedId = parseInt(e.lastEventId, 10);
        if (!isNaN(parsedId)) {
          lastEventId = parsedId;
        }
      }

      try {
        const rawData = typeof e.data === 'string' ? JSON.parse(e.data) : e.data;
        if (!rawData || typeof rawData !== 'object') return;

        const sseEvent = rawData as GeoLLMSSEEvent;
        if (sseEvent.id !== undefined && typeof sseEvent.id === 'number') {
          lastEventId = Math.max(lastEventId, sseEvent.id);
        }

        handlers.onEvent(sseEvent);

        // Auto-close on terminal finish event
        if (sseEvent.type === 'finish') {
          cleanup();
          if (handlers.onClose) handlers.onClose();
        }
      } catch (err) {
        console.warn(`[SSE:${taskId}] Failed to parse incoming event JSON:`, err, e.data);
      }
    };

    eventSource.onerror = (err) => {
      if (isManuallyClosed) return;
      if (handlers.onError) {
        handlers.onError(err);
      }
    };
  } catch (err) {
    if (handlers.onError) {
      handlers.onError(err instanceof Error ? err : new Error(String(err)));
    }
  }

  function cleanup() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  return {
    close: () => {
      isManuallyClosed = true;
      cleanup();
      if (handlers.onClose) handlers.onClose();
    },
    isOpen: () => {
      return eventSource !== null && eventSource.readyState === EventSource.OPEN;
    },
    getLastEventId: () => lastEventId,
  };
}

