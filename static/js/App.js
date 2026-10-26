// Astryx Main Application Shell (React 18 Component)
import { html, React } from '/static/js/html.js';
const { useState, useEffect, useRef } = React;

import { TaskTabs } from '/static/js/components/TaskTabs.js?v=20261025_3';
import { GlobeView } from '/static/js/components/GlobeView.js?v=20261025_3';
import { SingleWorkerSlot } from '/static/js/components/SingleWorkerSlot.js?v=20261025_3';
import { StacModal } from '/static/js/components/StacModal.js?v=20261025_4';
import { SupervisorDrawer } from '/static/js/components/SupervisorDrawer.js?v=20261025_3';
import { DatasetSidebar } from '/static/js/components/DatasetSidebar.js?v=20261025_2';
import { QueryConsole } from '/static/js/components/QueryConsole.js?v=20261025_2';
import { TiffPreviewModal } from '/static/js/components/TiffPreviewModal.js?v=20261025_2';
import { ToastContainer } from '/static/js/components/Toast.js?v=20261025_2';

export function App() {
  const [activeTab, setActiveTab] = useState('globe'); // 'globe', 'task_1', 'task_2', 'task_3'
  const [supervisorOpen, setSupervisorOpen] = useState(false);
  const [stacModalOpen, setStacModalOpen] = useState(false);
  const [activeAoiBbox, setActiveAoiBbox] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [files, setFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [tasks, setTasks] = useState({
    task_1: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] },
    task_2: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] },
    task_3: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] }
  });

  const [feedItems, setFeedItems] = useState([
    {
      type: 'assistant',
      text: 'Supervisor connected. I oversee all 3 worker sandboxes. Live progress from all active tasks will stream here.'
    }
  ]);

  const [chatHistory, setChatHistory] = useState([]);
  const [previewTarget, setPreviewTarget] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const streamsRef = useRef({});
  const timerIntervalRef = useRef(null);

  const showToast = (message, type = 'info', title = '') => {
    const id = Date.now() + Math.random().toString(36).slice(2, 7);
    setToasts(prev => [...prev, { id, message, type, title }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4500);
  };

  const dismissToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

  useEffect(() => {
    loadFiles();
    restoreTasks();

    timerIntervalRef.current = setInterval(() => {
      setTasks(prev => {
        let changed = false;
        const updated = { ...prev };
        Object.keys(updated).forEach(tid => {
          if (updated[tid].status === 'running') {
            updated[tid] = { ...updated[tid], elapsed: (updated[tid].elapsed || 0) + 1 };
            changed = true;
          }
        });
        return changed ? updated : prev;
      });
    }, 1000);

    // Fallback polling every 5s for running tasks to sync state even if SSE drops
    const pollInterval = setInterval(async () => {
      setTasks(currentTasks => {
        const runningTaskIds = Object.keys(currentTasks).filter(
          tid => currentTasks[tid].status === 'running'
        );
        if (runningTaskIds.length === 0) return currentTasks;

        (async () => {
          try {
            const res = await fetch('/api/tasks');
            const data = await res.json();
            if (data.tasks) {
              data.tasks.forEach(t => {
                if (runningTaskIds.includes(t.task_id)) {
                  setTasks(prev => {
                    const task = prev[t.task_id];
                    if (!task) return prev;
                    const isNowTerminal = ['done', 'partial', 'failed'].includes(t.status);
                    if (isNowTerminal && streamsRef.current[t.task_id]) {
                      streamsRef.current[t.task_id].close();
                      delete streamsRef.current[t.task_id];
                    }
                    return {
                      ...prev,
                      [t.task_id]: {
                        ...task,
                        status: t.status,
                        step: t.step || task.step,
                        error: t.error || task.error,
                        plan: t.plan !== undefined ? t.plan : task.plan,
                      }
                    };
                  });
                  fetchArtifacts(t.task_id);
                }
              });
            }
          } catch (_) {}
        })();

        return currentTasks;
      });
    }, 5000);

    return () => {
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
      clearInterval(pollInterval);
      Object.values(streamsRef.current).forEach(es => es.close());
    };
  }, []);

  const loadFiles = async () => {
    try {
      const res = await fetch('/api/files');
      const data = await res.json();
      setFiles(data.files || []);
      if (data.files && data.files.length > 0 && selectedFiles.length === 0) {
        setSelectedFiles(data.files.slice(0, 2).map(f => f.name));
      }
    } catch (_) {}
  };

  const handleUploadFiles = async (fileList) => {
    if (!fileList || !fileList.length) return;
    const fd = new FormData();
    for (const f of fileList) fd.append('files', f);

    try {
      await fetch('/api/upload', { method: 'POST', body: fd });
      await loadFiles();
      showToast('Successfully uploaded dataset files into data/', 'success');
    } catch (err) {
      showToast(err.message, 'error', 'Upload Failed');
    }
  };

  const restoreTasks = async () => {
    try {
      const res = await fetch('/api/tasks');
      const data = await res.json();
      if (!data.tasks) return;

      for (const t of data.tasks) {
        if (t.status === 'running' || t.status === 'pending_approval') {
          streamTask(t.task_id, t.question);
        } else if (['done', 'failed', 'partial'].includes(t.status)) {
          setTasks(prev => ({
            ...prev,
            [t.task_id]: {
              ...prev[t.task_id],
              status: t.status,
              question: t.question,
              step: t.step || t.status,
              elapsed: t.elapsed || 0,
              plan: t.plan
            }
          }));
          fetchArtifacts(t.task_id);
        }
      }
    } catch (_) {}
  };

  const fetchArtifacts = async (taskId) => {
    try {
      const res = await fetch(`/api/tasks/${taskId}/artifacts`);
      const data = await res.json();
      if (data.artifacts) {
        setTasks(prev => ({
          ...prev,
          [taskId]: {
            ...prev[taskId],
            // Replace (do not append) to prevent duplicate items
            artifacts: data.artifacts
          }
        }));
      }
    } catch (_) {}
  };

  const handleSubmitTask = async (questionText, targetFiles) => {
    if (!questionText.trim()) return;
    if (!targetFiles || !targetFiles.length) {
      showToast('Please select at least one dataset file before running.', 'warning');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: questionText,
          files: targetFiles.join(',')
        })
      });

      const data = await res.json();
      if (!res.ok || data.error) {
        showToast(data.error || 'Failed to submit task', 'error', 'Submission Failed');
        setIsSubmitting(false);
        return;
      }

      showToast(`Task assigned to Sandbox #${data.task_id.slice(-1)}`, 'success');

      setFeedItems(prev => [
        ...prev,
        {
          type: 'text',
          taskId: data.task_id,
          text: `Task dispatched: "${questionText.slice(0, 60)}..."`
        }
      ]);

      streamTask(data.task_id, questionText);
    } catch (err) {
      showToast(err.message, 'error', 'Connection Error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const streamTask = (taskId, questionText) => {
    if (streamsRef.current[taskId]) {
      streamsRef.current[taskId].close();
    }

    setTasks(prev => ({
      ...prev,
      [taskId]: {
        ...prev[taskId],
        status: 'running',
        question: questionText || prev[taskId]?.question,
        step: 'Starting analysis...',
        elapsed: 0,
        plan: null,
        artifacts: [],
        attempt: null,
        activities: []
      }
    }));

    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    streamsRef.current[taskId] = es;

    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const t = msg.type;

        if (t === 'start') {
          setTasks(prev => ({
            ...prev,
            [taskId]: {
              ...prev[taskId],
              status: 'running',
              question: msg.question || prev[taskId].question,
              step: 'Starting analysis'
            }
          }));
        } else if (t === 'status') {
          setTasks(prev => ({
            ...prev,
            [taskId]: {
              ...prev[taskId],
              status: msg.status || prev[taskId].status,
              step: msg.step || prev[taskId].step
            }
          }));
        } else if (t === 'text') {
          const delta = msg.delta || '';
          if (!delta) return;
          setTasks(prev => {
            const task = prev[taskId];
            const acts = [...(task.activities || [])];
            const last = acts[acts.length - 1];
            if (last && last.type === 'text') {
              acts[acts.length - 1] = { ...last, text: last.text + delta };
            } else {
              acts.push({ type: 'text', text: delta });
            }
            return {
              ...prev,
              [taskId]: {
                ...task,
                step: delta.trim() ? delta.trim().slice(0, 80) : task.step,
                activities: acts
              }
            };
          });

          setFeedItems(prev => {
            const last = prev[prev.length - 1];
            if (last && last.taskId === taskId && last.type === 'text') {
              const updated = [...prev];
              updated[updated.length - 1] = { ...last, text: last.text + delta };
              return updated;
            }
            return [...prev, { type: 'text', taskId, text: delta }];
          });
        } else if (t === 'thinking') {
          const delta = msg.delta || '';
          if (!delta) return;
          setTasks(prev => {
            const task = prev[taskId];
            const acts = [...(task.activities || [])];
            const last = acts[acts.length - 1];
            if (last && last.type === 'thinking') {
              acts[acts.length - 1] = { ...last, text: last.text + delta };
            } else {
              acts.push({ type: 'thinking', text: delta });
            }
            return {
              ...prev,
              [taskId]: {
                ...task,
                step: 'Thinking...',
                activities: acts
              }
            };
          });
        } else if (t === 'tool_start') {
          setTasks(prev => {
            const task = prev[taskId];
            const acts = [...(task.activities || [])];
            acts.push({
              type: 'tool',
              id: msg.toolCallId,
              toolName: msg.toolName,
              args: msg.args,
              attempt: msg.attempt,
              code_attempt: msg.code_attempt,
              max_attempts: msg.max_attempts,
              running: true
            });
            return {
              ...prev,
              [taskId]: {
                ...task,
                attempt: msg.attempt || task.attempt,
                code_attempt: msg.code_attempt || task.code_attempt,
                max_attempts: msg.max_attempts || task.max_attempts,
                step: `Tool: ${msg.toolName}`,
                activities: acts
              }
            };
          });

          setFeedItems(prev => [
            ...prev,
            {
              type: 'tool_start',
              taskId,
              toolName: msg.toolName,
              args: msg.args,
              attempt: msg.attempt
            }
          ]);
        } else if (t === 'tool_end') {
          setTasks(prev => {
            const task = prev[taskId];
            const acts = (task.activities || []).map(act => {
              if (act.type === 'tool' && (act.id === msg.toolCallId || act.running)) {
                return {
                  ...act,
                  running: false,
                  ok: msg.ok,
                  exit_code: msg.exit_code,
                  duration_s: msg.duration_s,
                  error: msg.error,
                  stdout: msg.stdout
                };
              }
              return act;
            });
            return {
              ...prev,
              [taskId]: {
                ...task,
                step: `Tool ${msg.ok ? 'succeeded' : 'failed'} (exit ${msg.exit_code})`,
                activities: acts
              }
            };
          });

          setFeedItems(prev => [
            ...prev,
            {
              type: 'tool_end',
              taskId,
              ok: msg.ok,
              exit_code: msg.exit_code,
              duration_s: msg.duration_s,
              error: msg.error
            }
          ]);
        } else if (t === 'vision_check') {
          setTasks(prev => {
            const task = prev[taskId];
            const acts = [...(task.activities || [])];
            acts.push({
              type: 'vision_check',
              image: msg.image,
              state: msg.state,
              verdict: msg.verdict,
              text: msg.text,
              index: msg.index,
              total: msg.total
            });
            return {
              ...prev,
              [taskId]: {
                ...task,
                step: msg.state === 'started'
                  ? `Checking ${msg.image} (${msg.index}/${msg.total})`
                  : `${msg.image}: ${msg.verdict || 'checked'}`,
                activities: acts
              }
            };
          });

          setFeedItems(prev => [
            ...prev,
            {
              type: 'vision_check',
              taskId,
              image: msg.image,
              state: msg.state,
              verdict: msg.verdict,
              text: msg.text,
              index: msg.index,
              total: msg.total
            }
          ]);
        } else if (t === 'plan_ready') {
          setTasks(prev => ({
            ...prev,
            [taskId]: {
              ...prev[taskId],
              status: 'pending_approval',
              plan: msg.plan,
              step: 'Plan review required'
            }
          }));

          setFeedItems(prev => [
            ...prev,
            {
              type: 'plan_ready',
              taskId,
              plan: msg.plan
            }
          ]);
        } else if (t === 'artifacts') {
          const arts = msg.artifacts || [];
          setTasks(prev => ({
            ...prev,
            [taskId]: {
              ...prev[taskId],
              artifacts: arts,
              step: `Produced ${arts.length} artifacts`
            }
          }));
        } else if (t === 'finish') {
          // Collect full narrative from text activities before clearing
          setTasks(prev => {
            const task = prev[taskId];
            const textActivities = (task.activities || [])
              .filter(a => a.type === 'text' && a.text && a.text.trim())
              .map(a => a.text);
            const answer = textActivities.length > 0 ? textActivities.join('') : null;
            return {
              ...prev,
              [taskId]: {
                ...task,
                status: msg.status,
                error: msg.error,
                answer: answer,
                step: msg.status === 'done' ? 'Completed' : (msg.error || msg.status)
              }
            };
          });

          setFeedItems(prev => [
            ...prev,
            {
              type: 'finish',
              taskId,
              status: msg.status,
              error: msg.error
            }
          ]);

          es.close();
          delete streamsRef.current[taskId];
          fetchArtifacts(taskId);
        }
      } catch (_) {}
    };

    // Auto-reconnect: do NOT close or delete stream ref on error
    es.onerror = () => {};
  };

  const handleApprovePlan = async (taskId) => {
    try {
      await fetch(`/api/tasks/${taskId}/approve`, { method: 'POST' });
      setTasks(prev => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: 'running', plan: null }
      }));
      setFeedItems(prev => [
        ...prev,
        { type: 'progress', taskId, text: 'Plan approved — executing code' }
      ]);
    } catch (_) {}
  };

  const handleRevisePlan = async (taskId, feedback) => {
    try {
      await fetch(`/api/tasks/${taskId}/revise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback })
      });
      setTasks(prev => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: 'running', plan: null }
      }));
      setFeedItems(prev => [
        ...prev,
        { type: 'progress', taskId, text: `Revision requested: "${feedback.slice(0, 40)}..."` }
      ]);
    } catch (_) {}
  };

  const handleCancelTask = async (taskId) => {
    try {
      await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
      if (streamsRef.current[taskId]) {
        streamsRef.current[taskId].close();
        delete streamsRef.current[taskId];
      }
      setTasks(prev => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: 'failed', step: 'Aborted by user' }
      }));
      setFeedItems(prev => [
        ...prev,
        { type: 'progress', taskId, text: 'Task aborted by user' }
      ]);
    } catch (_) {}
  };

  const handleSendMessage = async (msgText) => {
    const userItem = { type: 'user', text: msgText };
    setFeedItems(prev => [...prev, userItem]);

    const updatedHistory = [...chatHistory, { role: 'user', content: msgText }];
    setChatHistory(updatedHistory);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msgText, history: updatedHistory })
      });

      const data = await res.json();
      const reply = data.reply || data.error || 'No response from supervisor.';

      setFeedItems(prev => [
        ...prev,
        {
          type: 'assistant',
          text: reply,
          proposedJob: data.is_run_job ? data.proposed_job : null
        }
      ]);

      setChatHistory(prev => [...prev, { role: 'assistant', content: reply }]);
    } catch (err) {
      setFeedItems(prev => [
        ...prev,
        { type: 'assistant', text: `Connection error: ${err.message}` }
      ]);
    }
  };

  const handleClearChat = () => {
    setFeedItems([
      {
        type: 'assistant',
        text: 'Feed cleared. Ready for supervisor inquiries.'
      }
    ]);
    setChatHistory([]);
  };

  const handleOpenStacWithAoi = (bbox) => {
    setActiveAoiBbox(bbox);
    setStacModalOpen(true);
  };

  const handleSendAoiToTask = (bbox, targetTaskId) => {
    const slot = targetTaskId && targetTaskId.startsWith('task_') ? targetTaskId : 'task_1';
    setActiveTab(slot);
    showToast(`Attached AOI coordinates [${bbox.map(n => n.toFixed(2)).join(', ')}] to Task #${slot.slice(-1)}`, 'info');
  };

  const handleAssetStaged = (stagedData) => {
    showToast(`Staged ${stagedData.filename} (${stagedData.size_mb} MB) into data/`, 'success');
    loadFiles();
  };

  const activeWorkerSlotId = activeTab.startsWith('task_') ? activeTab : 'task_1';

  return html`
    <div className="app-shell" style=${{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <!-- Browser-Style Task Tabs Navigation -->
      <${TaskTabs}
        activeTab=${activeTab}
        onSelectTab=${(tab) => setActiveTab(tab)}
        tasks=${tasks}
        supervisorOpen=${supervisorOpen}
        onToggleSupervisor=${() => setSupervisorOpen(!supervisorOpen)}
        onOpenStacSearch=${() => setStacModalOpen(true)}
      />

      <!-- Main Body Viewport -->
      <div style=${{ flex: 1, position: 'relative', overflow: 'hidden', display: 'flex' }}>
        ${activeTab === 'globe' ? html`
          <!-- 3D Interactive Globe Fullscreen View -->
          <${GlobeView}
            tasks=${tasks}
            activeTaskId=${activeWorkerSlotId}
            onOpenStacSearchWithAoi=${handleOpenStacWithAoi}
            onSendAoiToTask=${handleSendAoiToTask}
          />
        ` : html`
          <!-- Focused Tabbed Task Sandbox View -->
          <div style=${{ display: 'flex', width: '100%', height: '100%', overflow: 'hidden' }}>
            <${DatasetSidebar}
              files=${files}
              selectedFiles=${selectedFiles}
              setSelectedFiles=${setSelectedFiles}
              onUploadFiles=${handleUploadFiles}
              onNotify=${showToast}
            />

            <main style=${{ flex: 1, overflowY: 'auto', background: '#F3F4F1' }}>
              <div style=${{ padding: '16px 16px 0 16px', maxWidth: '1200px', margin: '0 auto' }}>
                <${QueryConsole}
                  files=${files}
                  selectedFiles=${selectedFiles}
                  setSelectedFiles=${setSelectedFiles}
                  onSubmitTask=${(q, f) => handleSubmitTask(q, f)}
                  isSubmitting=${isSubmitting}
                  onNotify=${showToast}
                />
              </div>

              <${SingleWorkerSlot}
                taskId=${activeWorkerSlotId}
                task=${tasks[activeWorkerSlotId]}
                onApprovePlan=${handleApprovePlan}
                onRevisePlan=${handleRevisePlan}
                onCancelTask=${handleCancelTask}
                onPreviewFile=${(art) => {
                  // art.url already contains the full server-relative path from find_artifacts
                  const url = typeof art === 'string' ? `/runs/${art}` : (art.url || `/runs/${art.name}`);
                  const name = typeof art === 'string' ? art : art.name;
                  setPreviewTarget({ url, name, type: (name.endsWith('.tif') || name.endsWith('.tiff')) ? 'tif' : 'img' });
                }}
                onSwitchToGlobe=${() => setActiveTab('globe')}
                onNotify=${showToast}
              />
            </main>
          </div>
        `}

        <!-- Floating Supervisor AI Assistant Drawer -->
        <${SupervisorDrawer}
          isOpen=${supervisorOpen}
          onClose=${() => setSupervisorOpen(false)}
          feedItems=${feedItems}
          onDispatchTask=${(proposedPrompt) => handleSubmitTask(proposedPrompt, selectedFiles)}
        />
      </div>

      <!-- Microsoft Planetary Computer STAC Search Modal -->
      <${StacModal}
        isOpen=${stacModalOpen}
        onClose=${() => setStacModalOpen(false)}
        initialBbox=${activeAoiBbox}
        onAssetStaged=${handleAssetStaged}
      />

      <!-- GeoTIFF Preview Modal -->
      <${TiffPreviewModal}
        previewTarget=${previewTarget}
        onClose=${() => setPreviewTarget(null)}
      />

      <!-- Toast Alerts -->
      <${ToastContainer}
        toasts=${toasts}
        onDismiss=${dismissToast}
      />
    </div>
  `;
}
