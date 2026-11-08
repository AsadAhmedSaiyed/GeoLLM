// Custom hooks to manage real-time SSE streaming for single or multi-container slots.
// Merges incremental tokens (thinking, text), tool execution lifecycles,
// STAC staging progress, and Vision QA inspection events into reactive state.

import { useState, useEffect, useRef, useCallback } from 'react';
import { TaskState, ActivityItem } from '@/types/task';
import { GeoLLMSSEEvent, TaskStatus } from '@/types/sse';
import { connectTaskStream, TaskStreamSubscription } from '@/services/sse';
import { api } from '@/services/api';
import { SupervisorFeedItem } from '@/components/SupervisorDrawer';

export const DEFAULT_TASK_STATE: TaskState = {
  status: 'idle',
  question: 'Slot idle — awaiting task assignment',
  step: 'Ready',
  elapsed: 0,
  plan: null,
  stacPreview: null,
  artifacts: [],
  attempt: null,
  activities: [],
};

export function reduceTaskSSEEvent(
  prev: TaskState,
  msg: GeoLLMSSEEvent
): TaskState {
  const eventType = msg.type;
  const activities = [...(prev.activities || [])];

  // 0. Start
  if (eventType === 'start') {
    return {
      ...prev,
      status: 'running',
      question: msg.question || prev.question,
      step: 'Starting analysis',
    };
  }

  // 1. Text deltas
  if (eventType === 'text') {
    const delta = msg.delta !== undefined ? msg.delta : msg.text || '';
    if (!delta) return prev;

    const lastAct = activities[activities.length - 1];
    if (lastAct && lastAct.type === 'text' && 'text' in lastAct) {
      activities[activities.length - 1] = {
        ...lastAct,
        text: (lastAct.text || '') + delta,
      };
    } else {
      activities.push({
        type: 'text',
        text: delta,
        timestamp: Date.now(),
      });
    }

    return {
      ...prev,
      step: delta.trim() ? delta.trim().slice(0, 80) : prev.step,
      activities,
    };
  }

  // 2. Thinking deltas
  if (eventType === 'thinking') {
    const delta = msg.delta !== undefined ? msg.delta : msg.text || '';
    if (!delta) return prev;

    const lastAct = activities[activities.length - 1];
    if (lastAct && lastAct.type === 'thinking' && 'text' in lastAct) {
      activities[activities.length - 1] = {
        ...lastAct,
        text: (lastAct.text || '') + delta,
      };
    } else {
      activities.push({
        type: 'thinking',
        text: delta,
        timestamp: Date.now(),
      });
    }

    return {
      ...prev,
      step: 'Thinking…',
      activities,
    };
  }

  // 3. Tool execution start
  if (eventType === 'tool_start') {
    activities.push({
      type: 'tool',
      id: msg.toolCallId,
      toolName: msg.toolName,
      args: msg.args,
      attempt: msg.attempt,
      code_attempt: msg.code_attempt,
      max_attempts: msg.max_attempts,
      running: true,
    });

    return {
      ...prev,
      attempt: msg.attempt || prev.attempt,
      code_attempt: msg.code_attempt || prev.code_attempt,
      max_attempts: msg.max_attempts || prev.max_attempts,
      step: `Running tool: ${msg.toolName}`,
      activities,
    };
  }

  // 4. Tool execution end
  if (eventType === 'tool_end') {
    const updatedActs = activities.map((act) => {
      if (act.type === 'tool' && (act.id === msg.toolCallId || act.running)) {
        return {
          ...act,
          running: false,
          ok: msg.ok,
          exit_code: msg.exit_code,
          duration_s: msg.duration_s,
          error: msg.error,
          stdout: msg.stdout,
        };
      }
      return act;
    });

    return {
      ...prev,
      step: `Tool ${msg.ok ? 'succeeded' : 'failed'} (exit ${msg.exit_code ?? '—'})`,
      activities: updatedActs,
    };
  }

  // 5. STAC Preview Ready (Human Approval Gate)
  if (eventType === 'stac_preview_ready' || eventType === 'stac_preview_proposed') {
    activities.push({
      type: 'stac_preview_ready',
      preview: msg.preview,
    });

    return {
      ...prev,
      status: 'pending_stac_approval',
      stacPreview: msg.preview,
      step: 'STAC satellite preview ready — review required',
      activities,
    };
  }

  // 6. STAC Download start
  if (eventType === 'stac_download_start') {
    activities.push({
      type: 'stac_download',
      filename: msg.filename,
      collection: msg.collection,
      item_id: msg.item_id,
      asset_key: msg.asset_key,
      date: msg.date,
      running: true,
    });

    return {
      ...prev,
      step: `Downloading ${msg.filename} at native resolution…`,
      activities,
    };
  }

  // 7. STAC Download done
  if (eventType === 'stac_download_done') {
    let matched = false;
    const updatedActs = activities.map((act) => {
      if (act.type === 'stac_download' && act.filename === msg.filename && act.running) {
        matched = true;
        return {
          ...act,
          running: false,
          ok: msg.ok,
          path: msg.path,
          size_mb: msg.size_mb,
          width: msg.width,
          height: msg.height,
          resolution: msg.resolution,
          duration_s: msg.duration_s,
          error: msg.error,
        };
      }
      return act;
    });

    if (!matched) {
      updatedActs.push({
        type: 'stac_download',
        filename: msg.filename,
        collection: msg.collection,
        asset_key: msg.asset_key,
        date: msg.date,
        running: false,
        ok: msg.ok,
        path: msg.path,
        size_mb: msg.size_mb,
        width: msg.width,
        height: msg.height,
        resolution: msg.resolution,
        duration_s: msg.duration_s,
        error: msg.error,
      });
    }

    return {
      ...prev,
      step: msg.ok ? `Downloaded ${msg.filename}` : `Failed downloading ${msg.filename}`,
      activities: updatedActs,
    };
  }

  // 8. STAC Staged
  if (eventType === 'stac_staged') {
    activities.push({
      type: 'stac_staged',
      files: msg.files,
    });

    return {
      ...prev,
      files: msg.files,
      step: `Staged ${msg.files.length} native-resolution GeoTIFFs`,
      activities,
    };
  }

  // 9. Plan Ready (Human Approval Gate)
  if (eventType === 'plan_ready' || eventType === 'plan_proposed') {
    return {
      ...prev,
      status: 'pending_approval',
      plan: msg.plan,
      step: 'Plan review required',
    };
  }

  // 10. Status change
  if (eventType === 'status') {
    const nextStatus = (msg.status as TaskStatus) || prev.status;
    return {
      ...prev,
      status: nextStatus,
      step: msg.step || msg.text || prev.step,
    };
  }

  // 11. Artifacts produced
  if (eventType === 'artifacts') {
    return {
      ...prev,
      artifacts: msg.artifacts,
      step: `Produced ${msg.artifacts.length} artifacts`,
    };
  }

  // 12. Finish
  if (eventType === 'finish') {
    const finalStatus = (msg.status as TaskStatus) || (msg.ok ? 'done' : 'failed');
    const textParts = activities
      .filter((a): a is { type: 'text'; text: string; timestamp: number } => a.type === 'text')
      .map((a) => a.text);
    const answer = textParts.length > 0 ? textParts.join('') : prev.answer;

    return {
      ...prev,
      status: finalStatus,
      error: msg.error || null,
      answer: answer || null,
      step: finalStatus === 'done' ? 'Completed' : msg.error || String(finalStatus),
    };
  }

  // 13. Vision check deduplication when re-checking same image
  if (eventType === 'vision_check') {
    let filtered = activities;
    if (msg.state === 'started' && msg.image) {
      const targetBase = msg.image.split(/[/\\]/).pop();
      filtered = activities.filter((a) => {
        if (!a.type || !a.type.startsWith('vision_')) return true;
        const aImg = ('image' in a && a.image) ? String(a.image) : ('file' in a && a.file) ? String(a.file) : '';
        const aBase = aImg.split(/[/\\]/).pop();
        return aBase !== targetBase;
      });
    }
    filtered.push({
      type: 'vision_check',
      image: msg.image,
      state: msg.state,
      verdict: msg.verdict,
      text: msg.text,
      index: msg.index,
      total: msg.total,
    });
    return {
      ...prev,
      step:
        msg.state === 'started'
          ? `Checking ${msg.image} (${msg.index}/${msg.total})`
          : `${msg.image}: ${msg.verdict || 'checked'}`,
      activities: filtered,
    };
  }

  // 14. All other vision_* events and generic fallback
  activities.push(msg as ActivityItem);
  return {
    ...prev,
    step:
      eventType === 'vision_input_gate'
        ? `Input Quality Gate: ${msg.verdict || msg.state || 'checking'}`
        : eventType === 'vision_inspecting_tile'
        ? `Inspecting tile: ${msg.tile_id}`
        : eventType === 'vision_summary'
        ? `Vision QA: ${msg.final_verdict}`
        : prev.step,
    activities,
  };
}

export function useTaskStream(taskId: string, initialTask?: Partial<TaskState>) {
  const [task, setTask] = useState<TaskState>(() => ({
    ...DEFAULT_TASK_STATE,
    ...initialTask,
  }));

  const streamRef = useRef<TaskStreamSubscription | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (task.status === 'running') {
      if (!elapsedTimerRef.current) {
        elapsedTimerRef.current = setInterval(() => {
          setTask((prev) => ({
            ...prev,
            elapsed: (prev.elapsed || 0) + 1,
          }));
        }, 1000);
      }
    } else if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }

    return () => {
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
    };
  }, [task.status]);

  const refreshArtifacts = useCallback(async () => {
    try {
      const data = await api.getArtifacts(taskId);
      if (data.artifacts) {
        setTask((prev) => ({
          ...prev,
          artifacts: data.artifacts,
          answer: data.answer || prev.answer,
        }));
      }
    } catch {
      // ignore
    }
  }, [taskId]);

  const handleSSEEvent = useCallback(
    (msg: GeoLLMSSEEvent) => {
      setTask((prev) => reduceTaskSSEEvent(prev, msg));
      if (
        msg.type === 'tool_end' ||
        msg.type === 'finish' ||
        msg.type === 'vision_summary' ||
        msg.type === 'vision_stopped'
      ) {
        refreshArtifacts();
      }
    },
    [refreshArtifacts]
  );

  const startStream = useCallback(
    (lastId: number = 0) => {
      if (streamRef.current) {
        streamRef.current.close();
      }
      streamRef.current = connectTaskStream(
        taskId,
        {
          onEvent: handleSSEEvent,
          onError: (err) => console.warn(`[Stream:${taskId}] connection event:`, err),
          onClose: () => {
            streamRef.current = null;
          },
        },
        lastId
      );
    },
    [taskId, handleSSEEvent]
  );

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopStream();
      if (elapsedTimerRef.current) {
        clearInterval(elapsedTimerRef.current);
      }
    };
  }, [stopStream]);

  return {
    task,
    setTask,
    startStream,
    stopStream,
    refreshArtifacts,
  };
}

export function useMultiTaskStreams(options?: { onStacStaged?: () => void }) {
  const [tasks, setTasks] = useState<Record<string, TaskState>>({
    task_1: { ...DEFAULT_TASK_STATE },
    task_2: { ...DEFAULT_TASK_STATE },
    task_3: { ...DEFAULT_TASK_STATE },
  });

  const [feedItems, setFeedItems] = useState<SupervisorFeedItem[]>([
    {
      type: 'assistant',
      text: 'GeoLLM Supervisor connected. I oversee all 3 container sandboxes.',
    },
  ]);

  const streamsRef = useRef<Record<string, TaskStreamSubscription | null>>({});
  const onStacStagedRef = useRef(options?.onStacStaged);
  onStacStagedRef.current = options?.onStacStaged;

  const fetchArtifacts = useCallback(async (taskId: string) => {
    try {
      const data = await api.getArtifacts(taskId);
      if (data.artifacts) {
        setTasks((prev) => ({
          ...prev,
          [taskId]: {
            ...(prev[taskId] || DEFAULT_TASK_STATE),
            artifacts: data.artifacts,
            answer: data.answer || prev[taskId]?.answer || null,
          },
        }));
      }
    } catch {
      // ignore
    }
  }, []);

  const appendFeedFromSSE = useCallback((taskId: string, msg: GeoLLMSSEEvent) => {
    const t = msg.type;
    if (t === 'text') {
      const delta = msg.delta !== undefined ? msg.delta : msg.text || '';
      if (!delta) return;
      setFeedItems((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.taskId === taskId && last.type === 'text') {
          const updated = [...prev];
          updated[updated.length - 1] = { ...last, text: (last.text || '') + delta };
          return updated;
        }
        return [...prev, { type: 'text', taskId, text: delta }];
      });
    } else if (t === 'thinking') {
      const delta = msg.delta !== undefined ? msg.delta : msg.text || '';
      if (!delta) return;
      setFeedItems((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.taskId === taskId && last.type === 'thinking') {
          const updated = [...prev];
          updated[updated.length - 1] = { ...last, text: (last.text || '') + delta };
          return updated;
        }
        return [...prev, { type: 'thinking', taskId, text: delta }];
      });
    } else if (t === 'tool_start') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'tool_start',
          taskId,
          toolName: msg.toolName,
          args: msg.args,
          attempt: msg.attempt,
        },
      ]);
    } else if (t === 'tool_end') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'tool_end',
          taskId,
          toolName: msg.toolName || 'tool',
          ok: msg.ok,
          exit_code: msg.exit_code,
          duration_s: msg.duration_s,
          error: msg.error,
        },
      ]);
    } else if (t === 'vision_check') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'vision_check',
          taskId,
          image: msg.image,
          state: msg.state,
          verdict: msg.verdict,
          text: msg.text,
        },
      ]);
    } else if (t === 'vision_input_gate') {
      const gateText =
        msg.state === 'started'
          ? `🛡️ Input Quality Gate: inspecting ${msg.raster_count || ''} input raster(s)…`
          : `🛡️ Input Quality Gate [${(msg.verdict || 'done').toUpperCase()}]: ${
              msg.reason || 'Inputs checked'
            }`;
      setFeedItems((prev) => [...prev, { type: 'progress', taskId, text: gateText }]);
    } else if (t === 'stac_preview_ready' || t === 'stac_preview_proposed') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'progress',
          taskId,
          text: '🛰️ Satellite scene previews ready — awaiting user approval',
        },
      ]);
    } else if (t === 'stac_download_start') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'progress',
          taskId,
          text: `⬇️ Downloading STAC band ${msg.filename} (native resolution)…`,
        },
      ]);
    } else if (t === 'stac_staged') {
      setFeedItems((prev) => [
        ...prev,
        {
          type: 'progress',
          taskId,
          text: `📥 Staged ${(msg.files || []).length} native-resolution GeoTIFFs`,
        },
      ]);
    } else if (t === 'plan_ready' || t === 'plan_proposed') {
      setFeedItems((prev) => [...prev, { type: 'plan_ready', taskId, plan: msg.plan }]);
    } else if (t === 'artifacts') {
      setFeedItems((prev) => [
        ...prev,
        { type: 'artifacts', taskId, artifacts: msg.artifacts },
      ]);
    } else if (t === 'finish') {
      const finalStatus = msg.status || (msg.ok ? 'done' : 'failed');
      setFeedItems((prev) => [
        ...prev,
        { type: 'finish', taskId, status: String(finalStatus), error: msg.error },
      ]);
    }
  }, []);

  const startSlotStream = useCallback(
    (taskId: string, lastId: number = 0) => {
      if (streamsRef.current[taskId]) {
        streamsRef.current[taskId]?.close();
      }

      streamsRef.current[taskId] = connectTaskStream(
        taskId,
        {
          onEvent: (msg) => {
            setTasks((prev) => ({
              ...prev,
              [taskId]: reduceTaskSSEEvent(prev[taskId] || DEFAULT_TASK_STATE, msg),
            }));
            appendFeedFromSSE(taskId, msg);

            if (msg.type === 'stac_staged') {
              onStacStagedRef.current?.();
            }
            if (
              msg.type === 'tool_end' ||
              msg.type === 'finish' ||
              msg.type === 'vision_summary' ||
              msg.type === 'vision_stopped'
            ) {
              fetchArtifacts(taskId);
            }
          },
          onError: () => {
            // EventSource handles transient reconnects
          },
          onClose: () => {
            streamsRef.current[taskId] = null;
          },
        },
        lastId
      );
    },
    [appendFeedFromSSE, fetchArtifacts]
  );

  const stopSlotStream = useCallback((taskId: string) => {
    if (streamsRef.current[taskId]) {
      streamsRef.current[taskId]?.close();
      streamsRef.current[taskId] = null;
    }
  }, []);

  const resetSlotState = useCallback(
    (taskId: string) => {
      stopSlotStream(taskId);
      setTasks((prev) => ({
        ...prev,
        [taskId]: { ...DEFAULT_TASK_STATE },
      }));
    },
    [stopSlotStream]
  );

  // Restore active tasks on mount & run 1s elapsed timer + 5s fallback polling
  useEffect(() => {
    (async () => {
      try {
        const list = await api.getTasks();
        setTasks((prev) => {
          const next = { ...prev };
          list.forEach((t) => {
            next[t.task_id] = {
              ...(next[t.task_id] || DEFAULT_TASK_STATE),
              status: t.status,
              question: t.question || DEFAULT_TASK_STATE.question,
              step: t.step || 'Ready',
              elapsed: t.elapsed || 0,
              error: t.error || null,
              plan: t.plan || null,
              stacPreview: t.stac_preview || null,
            };
          });
          return next;
        });

        list.forEach((t) => {
          if (t.status && t.status !== 'idle') {
            startSlotStream(t.task_id, 0);
            fetchArtifacts(t.task_id);
          }
        });
      } catch {
        // ignore initial restore error
      }
    })();

    const timerInterval = setInterval(() => {
      setTasks((prev) => {
        let changed = false;
        const updated = { ...prev };
        Object.keys(updated).forEach((tid) => {
          if (updated[tid].status === 'running') {
            updated[tid] = {
              ...updated[tid],
              elapsed: (updated[tid].elapsed || 0) + 1,
            };
            changed = true;
          }
        });
        return changed ? updated : prev;
      });
    }, 1000);

    const pollInterval = setInterval(async () => {
      try {
        const list = await api.getTasks();
        setTasks((prev) => {
          const next = { ...prev };
          list.forEach((t) => {
            const current = next[t.task_id];
            if (!current || current.status === 'idle') return;
            const isNowTerminal = ['done', 'partial', 'failed'].includes(t.status);
            if (isNowTerminal && streamsRef.current[t.task_id]) {
              streamsRef.current[t.task_id]?.close();
              streamsRef.current[t.task_id] = null;
            }
            next[t.task_id] = {
              ...current,
              status: t.status,
              question: t.question || current.question,
              step: t.step || current.step,
              error: t.error || current.error,
              plan: t.plan !== undefined ? t.plan : current.plan,
              stacPreview:
                t.stac_preview !== undefined ? t.stac_preview : current.stacPreview,
            };
          });
          return next;
        });
      } catch {
        // ignore fallback poll error
      }
    }, 5000);

    const currentStreams = streamsRef.current;
    return () => {
      clearInterval(timerInterval);
      clearInterval(pollInterval);
      Object.values(currentStreams).forEach((s) => s?.close());
    };
  }, [fetchArtifacts, startSlotStream]);

  return {
    tasks,
    setTasks,
    feedItems,
    setFeedItems,
    startSlotStream,
    stopSlotStream,
    resetSlotState,
    fetchArtifacts,
  };
}
