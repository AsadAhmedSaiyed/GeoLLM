// Astryx Main Application Shell (React 18 Component)
import { html, React } from '/static/js/html.js';
const { useState, useEffect, useRef } = React;

import { Navbar } from '/static/js/components/Navbar.js';
import { QueryConsole } from '/static/js/components/QueryConsole.js';
import { WorkerSlots } from '/static/js/components/WorkerSlots.js';
import { UnifiedChat } from '/static/js/components/UnifiedChat.js';
import { TiffPreviewModal } from '/static/js/components/TiffPreviewModal.js';

export function App() {
  const [files, setFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [tasks, setTasks] = useState({
    task_1: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [] },
    task_2: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [] },
    task_3: { status: 'idle', question: 'Slot idle — awaiting task assignment', step: 'Ready', elapsed: 0, plan: null, artifacts: [] }
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

    return () => {
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
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
    } catch (err) {
      alert(`Upload error: ${err.message}`);
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
      if (data.artifacts && data.artifacts.length) {
        setTasks(prev => ({
          ...prev,
          [taskId]: { ...prev[taskId], artifacts: data.artifacts }
        }));
      }
    } catch (_) {}
  };

  const handleSubmitTask = async (questionText, targetFiles) => {
    if (!questionText.trim()) return;
    if (!targetFiles || !targetFiles.length) {
      alert('Please select at least one dataset file.');
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
        alert(data.error || 'Failed to submit task');
        setIsSubmitting(false);
        return;
      }

      setFeedItems(prev => [
        ...prev,
        {
          type: 'progress',
          taskId: data.task_id,
          text: `Task dispatched: "${questionText.slice(0, 60)}..."`
        }
      ]);

      streamTask(data.task_id, questionText);
    } catch (err) {
      alert(`Submission error: ${err.message}`);
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
        question: questionText,
        step: 'Initializing container...',
        elapsed: 0,
        plan: null,
        artifacts: []
      }
    }));

    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    streamsRef.current[taskId] = es;

    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        if (msg.type === 'milestone') {
          setFeedItems(prev => [
            ...prev,
            { type: 'progress', taskId, text: msg.text }
          ]);
        } else if (msg.type === 'step') {
          setTasks(prev => ({
            ...prev,
            [taskId]: { ...prev[taskId], step: msg.text }
          }));
        } else if (msg.type === 'plan_ready') {
          setTasks(prev => ({
            ...prev,
            [taskId]: { ...prev[taskId], status: 'pending_approval', plan: msg.plan }
          }));
          setFeedItems(prev => [
            ...prev,
            { type: 'progress', taskId, text: 'Analysis plan proposed — review required' }
          ]);
        } else if (msg.type === 'artifacts') {
          setTasks(prev => ({
            ...prev,
            [taskId]: { ...prev[taskId], artifacts: msg.artifacts }
          }));
        } else if (msg.type === 'finish') {
          setTasks(prev => ({
            ...prev,
            [taskId]: {
              ...prev[taskId],
              status: msg.status,
              step: msg.status === 'done' ? 'Completed' : (msg.error || msg.status)
            }
          }));
          setFeedItems(prev => [
            ...prev,
            { type: 'progress', taskId, text: `Task ${msg.status.toUpperCase()}: ${msg.error || 'All deliverables ready'}` }
          ]);
          es.close();
          delete streamsRef.current[taskId];
          fetchArtifacts(taskId);
        }
      } catch (_) {}
    };

    es.onerror = () => {
      es.close();
      delete streamsRef.current[taskId];
    };
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

  const activeWorkerCount = Object.values(tasks).filter(t => t.status === 'running' || t.status === 'pending_approval').length;

  return html`
    <div>
      <${Navbar}
        activeWorkerCount=${activeWorkerCount}
        isClusterBusy=${activeWorkerCount > 0}
      />

      <${QueryConsole}
        files=${files}
        selectedFiles=${selectedFiles}
        setSelectedFiles=${setSelectedFiles}
        onSubmitTask=${handleSubmitTask}
        onUploadFiles=${handleUploadFiles}
        isSubmitting=${isSubmitting}
      />

      <div className="workspace-container">
        <${WorkerSlots}
          tasks=${tasks}
          onApprovePlan=${handleApprovePlan}
          onRevisePlan=${handleRevisePlan}
          onCancelTask=${handleCancelTask}
          onPreviewFile=${(url, name, type) => setPreviewTarget({ url, name, type })}
        />

        <${UnifiedChat}
          feedItems=${feedItems}
          onSendMessage=${handleSendMessage}
          onDispatchProposedJob=${(jobPrompt) => handleSubmitTask(jobPrompt, selectedFiles)}
          onClearChat=${handleClearChat}
        />
      </div>

      <${TiffPreviewModal}
        previewTarget=${previewTarget}
        onClose=${() => setPreviewTarget(null)}
      />
    </div>
  `;
}
