import React, { useState, useEffect, useRef } from "https://esm.sh/react@18.2.0";
import { TaskTabs } from "./components/TaskTabs.js?v=20261107_v5";
import { GlobeView } from "./components/GlobeView.js?v=20261107_v5";
import { SingleWorkerSlot } from "./components/SingleWorkerSlot.js?v=20261107_v5";
import { StacModal } from "./components/StacModal.js?v=20261107_v5";
import { SupervisorDrawer } from "./components/SupervisorDrawer.js?v=20261107_v5";
import { DatasetSidebar } from "./components/DatasetSidebar.js?v=20261107_v5";
import { QueryConsole } from "./components/QueryConsole.js?v=20261107_v5";
import { TiffPreviewModal } from "./components/TiffPreviewModal.js?v=20261107_v5";
import { ToastContainer } from "./components/Toast.js?v=20261107_v5";
function App() {
  const [workspaces, setWorkspaces] = useState(() => {
    try {
      const saved = localStorage.getItem("geollm_workspaces");
      if (saved) return JSON.parse(saved);
    } catch (e) {
    }
    return [];
  });
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(() => {
    try {
      const saved = localStorage.getItem("geollm_workspaces");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.length > 0) return parsed[0].id;
      }
    } catch (e) {
    }
    return null;
  });
  const [isConsoleOpen, setIsConsoleOpen] = useState(true);
  const [consoleWidth, setConsoleWidth] = useState(() => {
    try {
      const savedW = parseInt(localStorage.getItem("geollm_console_width"), 10);
      if (savedW && savedW >= 360 && savedW <= 1200) return savedW;
    } catch (e) {
    }
    return 480;
  });
  const [isResizingConsole, setIsResizingConsole] = useState(false);
  const handleStartConsoleResize = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizingConsole(true);
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const onMouseMove = (moveEvent) => {
      const maxAllowed = Math.max(480, window.innerWidth - 360);
      const nextWidth = Math.min(Math.max(moveEvent.clientX - 330, 360), maxAllowed);
      setConsoleWidth(nextWidth);
    };
    const onMouseUp = (upEvent) => {
      setIsResizingConsole(false);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      try {
        const maxAllowed = Math.max(480, window.innerWidth - 360);
        const finalWidth = Math.min(Math.max(upEvent.clientX - 330, 360), maxAllowed);
        localStorage.setItem("geollm_console_width", String(finalWidth));
      } catch (err) {
      }
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };
  const [supervisorOpen, setSupervisorOpen] = useState(false);
  const [stacModalOpen, setStacModalOpen] = useState(false);
  const [activeAoiBbox, setActiveAoiBbox] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [files, setFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [tasks, setTasks] = useState({
    task_1: { status: "idle", question: "Slot idle \u2014 awaiting task assignment", step: "Ready", elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] },
    task_2: { status: "idle", question: "Slot idle \u2014 awaiting task assignment", step: "Ready", elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] },
    task_3: { status: "idle", question: "Slot idle \u2014 awaiting task assignment", step: "Ready", elapsed: 0, plan: null, artifacts: [], attempt: null, activities: [] }
  });
  const [feedItems, setFeedItems] = useState([
    {
      type: "assistant",
      text: "GeoLLM Supervisor connected. I oversee all 3 container sandboxes."
    }
  ]);
  const [previewTarget, setPreviewTarget] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingGlobeArtifact, setPendingGlobeArtifact] = useState(null);
  const streamsRef = useRef({});
  const timerIntervalRef = useRef(null);
  useEffect(() => {
    try {
      localStorage.setItem("geollm_workspaces", JSON.stringify(workspaces));
    } catch (e) {
    }
  }, [workspaces]);
  const showToast = (message, type = "info", title = "") => {
    const id = Date.now() + Math.random().toString(36).slice(2, 7);
    setToasts((prev) => [...prev, { id, message, type, title }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  };
  const dismissToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };
  useEffect(() => {
    loadFiles();
    restoreTasks();
    timerIntervalRef.current = setInterval(() => {
      setTasks((prev) => {
        let changed = false;
        const updated = { ...prev };
        Object.keys(updated).forEach((tid) => {
          if (updated[tid].status === "running") {
            updated[tid] = { ...updated[tid], elapsed: (updated[tid].elapsed || 0) + 1 };
            changed = true;
          }
        });
        return changed ? updated : prev;
      });
    }, 1e3);
    const pollInterval = setInterval(async () => {
      setTasks((currentTasks) => {
        const runningTaskIds = Object.keys(currentTasks).filter(
          (tid) => currentTasks[tid].status === "running"
        );
        if (runningTaskIds.length === 0) return currentTasks;
        (async () => {
          try {
            const res = await fetch("/api/tasks");
            const data = await res.json();
            if (data.tasks) {
              data.tasks.forEach((t) => {
                if (runningTaskIds.includes(t.task_id)) {
                  setTasks((prev) => {
                    const task = prev[t.task_id];
                    if (!task) return prev;
                    const isNowTerminal = ["done", "partial", "failed"].includes(t.status);
                    if (isNowTerminal && streamsRef.current[t.task_id]) {
                      streamsRef.current[t.task_id].close();
                      delete streamsRef.current[t.task_id];
                    }
                    return {
                      ...prev,
                      [t.task_id]: {
                        ...task,
                        status: t.status,
                        question: t.question || task.question,
                        step: t.step || task.step,
                        error: t.error || task.error,
                        plan: t.plan !== void 0 ? t.plan : task.plan,
                        stacPreview: t.stac_preview !== void 0 ? t.stac_preview : task.stacPreview
                      }
                    };
                  });
                  if (["running", "done", "partial", "failed"].includes(t.status)) {
                    fetchArtifacts(t.task_id);
                  }
                }
              });
            }
          } catch (e) {
            console.error("Fallback poll error:", e);
          }
        })();
        return currentTasks;
      });
    }, 5e3);
    return () => {
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
      clearInterval(pollInterval);
      Object.values(streamsRef.current).forEach((es) => es && es.close());
    };
  }, []);
  const loadFiles = async () => {
    try {
      const res = await fetch("/api/files");
      const data = await res.json();
      setFiles(data.files || []);
    } catch (e) {
      console.error("Failed to load data files:", e);
    }
  };
  const handleUploadFiles = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    const formData = new FormData();
    for (let i = 0; i < fileList.length; i++) {
      formData.append("files", fileList[i]);
    }
    showToast(`Uploading ${fileList.length} file(s)...`, "info");
    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Uploaded ${data.uploaded.length} file(s) to storage`, "success");
        loadFiles();
      } else {
        showToast(data.error || "Upload failed", "error");
      }
    } catch (e) {
      console.error("Upload error:", e);
      showToast("File upload failed", "error");
    }
  };
  const restoreTasks = async () => {
    try {
      const res = await fetch("/api/tasks");
      const data = await res.json();
      if (!data.tasks) return;
      const restored = {};
      data.tasks.forEach((t) => {
        restored[t.task_id] = {
          status: t.status,
          question: t.question || `Slot idle \u2014 awaiting task assignment`,
          step: t.step || "Ready",
          elapsed: t.elapsed || 0,
          error: t.error || null,
          plan: t.plan || null,
          stacPreview: t.stac_preview || null,
          artifacts: [],
          activities: []
        };
      });
      setTasks((prev) => ({ ...prev, ...restored }));
      data.tasks.forEach((t) => {
        if (t.status && t.status !== "idle") {
          connectTaskStream(t.task_id);
          fetchArtifacts(t.task_id);
        }
      });
    } catch (e) {
      console.error("Task restore error:", e);
    }
  };
  const fetchArtifacts = async (taskId) => {
    try {
      const res = await fetch(`/api/tasks/${taskId}/artifacts`);
      if (res.ok) {
        const data = await res.json();
        setTasks((prev) => ({
          ...prev,
          [taskId]: {
            ...prev[taskId],
            artifacts: data.artifacts || [],
            answer: data.answer || prev[taskId]?.answer || null
          }
        }));
      }
    } catch (e) {
      console.error("Artifact fetch failed:", e);
    }
  };
  const connectTaskStream = (taskId) => {
    if (streamsRef.current[taskId]) {
      streamsRef.current[taskId].close();
    }
    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    streamsRef.current[taskId] = es;
    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleStreamEvent(taskId, msg);
      } catch (e) {
        console.error(`SSE parse error on ${taskId}:`, e);
      }
    };
    es.onerror = () => {
    };
  };
  const handleStreamEvent = (taskId, msg) => {
    if (!msg || !msg.type) return;
    const t = msg.type;
    if (t === "supervisor_feed") {
      setFeedItems((prev) => [
        ...prev,
        {
          id: Date.now() + Math.random(),
          type: msg.feed_type || "progress",
          text: msg.text || "",
          taskId: msg.task_id || taskId,
          meta: msg.meta || null,
          timestamp: (/* @__PURE__ */ new Date()).toLocaleTimeString()
        }
      ]);
      return;
    }
    if (t === "start") {
      setTasks((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          status: "running",
          question: msg.question || prev[taskId]?.question,
          step: "Starting analysis"
        }
      }));
    } else if (t === "status") {
      setTasks((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          status: msg.status || prev[taskId]?.status,
          step: msg.step || prev[taskId]?.step
        }
      }));
    } else if (t === "text") {
      const delta = msg.delta !== void 0 ? msg.delta : msg.text || "";
      if (!delta) return;
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        const last = acts[acts.length - 1];
        if (last && last.type === "text") {
          acts[acts.length - 1] = { ...last, text: (last.text || "") + delta };
        } else {
          acts.push({ type: "text", text: delta, timestamp: Date.now() });
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
      setFeedItems((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.taskId === taskId && last.type === "text") {
          const updated = [...prev];
          updated[updated.length - 1] = { ...last, text: (last.text || "") + delta };
          return updated;
        }
        return [...prev, { type: "text", taskId, text: delta }];
      });
    } else if (t === "thinking") {
      const delta = msg.delta !== void 0 ? msg.delta : msg.text || "";
      if (!delta) return;
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        const last = acts[acts.length - 1];
        if (last && last.type === "thinking") {
          acts[acts.length - 1] = { ...last, text: (last.text || "") + delta };
        } else {
          acts.push({ type: "thinking", text: delta, timestamp: Date.now() });
        }
        return {
          ...prev,
          [taskId]: {
            ...task,
            step: "Thinking\u2026",
            activities: acts
          }
        };
      });
      setFeedItems((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.taskId === taskId && last.type === "thinking") {
          const updated = [...prev];
          updated[updated.length - 1] = { ...last, text: (last.text || "") + delta };
          return updated;
        }
        return [...prev, { type: "thinking", taskId, text: delta }];
      });
    } else if (t === "tool_start" || t === "tool") {
      const toolName = msg.toolName || msg.tool || "tool";
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        acts.push({
          type: "tool",
          id: msg.toolCallId,
          toolName,
          args: msg.args,
          attempt: msg.attempt,
          code_attempt: msg.code_attempt,
          max_attempts: msg.max_attempts,
          running: msg.running !== void 0 ? msg.running : true,
          ok: msg.ok,
          exit_code: msg.exit_code,
          duration_s: msg.duration_s,
          error: msg.error,
          stdout: msg.stdout
        });
        return {
          ...prev,
          [taskId]: {
            ...task,
            attempt: msg.attempt || task.attempt,
            code_attempt: msg.code_attempt || task.code_attempt,
            max_attempts: msg.max_attempts || task.max_attempts,
            step: `Running tool: ${toolName}`,
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "tool_start",
          taskId,
          toolName,
          args: msg.args,
          attempt: msg.attempt
        }
      ]);
    } else if (t === "tool_end") {
      let resolvedToolName = msg.toolName || "";
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = (task.activities || []).map((act) => {
          if (act.type === "tool" && (act.id === msg.toolCallId || act.running)) {
            if (!resolvedToolName && act.toolName) resolvedToolName = act.toolName;
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
            step: `Tool ${msg.ok ? "succeeded" : "failed"} (exit ${msg.exit_code})`,
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "tool_end",
          taskId,
          toolName: resolvedToolName || msg.toolName || "tool",
          ok: msg.ok,
          exit_code: msg.exit_code,
          duration_s: msg.duration_s,
          error: msg.error
        }
      ]);
      fetchArtifacts(taskId);
    } else if (t === "vision_check") {
      fetchArtifacts(taskId);
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        let acts = [...task.activities || []];
        if (msg.state === "started" && msg.image) {
          const targetBase = msg.image.split(/[/\\]/).pop();
          acts = acts.filter((a) => {
            if (!a.type || !a.type.startsWith("vision_")) return true;
            const aImg = a.image || a.file || "";
            const aBase = aImg.split(/[/\\]/).pop();
            return aBase !== targetBase;
          });
        }
        acts.push({
          type: "vision_check",
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
            step: msg.state === "started" ? `Checking ${msg.image} (${msg.index}/${msg.total})` : `${msg.image}: ${msg.verdict || "checked"}`,
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "vision_check",
          taskId,
          image: msg.image,
          state: msg.state,
          verdict: msg.verdict,
          text: msg.text,
          index: msg.index,
          total: msg.total
        }
      ]);
    } else if (t.startsWith("vision_") && t !== "vision_check") {
      if (t === "vision_summary" || t === "vision_stopped") {
        fetchArtifacts(taskId);
      }
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        acts.push(msg);
        return {
          ...prev,
          [taskId]: {
            ...task,
            step: t === "vision_input_gate" ? `Input Quality Gate: ${msg.verdict || msg.state || "checking"}` : task.step,
            activities: acts
          }
        };
      });
      if (t === "vision_input_gate") {
        const gateText = msg.state === "started" ? `\u{1F6E1}\uFE0F Input Quality Gate: inspecting ${msg.raster_count || ""} input raster(s)\u2026` : `\u{1F6E1}\uFE0F Input Quality Gate [${(msg.verdict || "done").toUpperCase()}]: ${msg.reason || "Inputs checked"}`;
        setFeedItems((prev) => [
          ...prev,
          {
            type: "progress",
            taskId,
            text: gateText
          }
        ]);
      }
    } else if (t === "stac_preview_ready" || t === "stac_preview_proposed") {
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        acts.push({
          type: "stac_preview_ready",
          preview: msg.preview
        });
        return {
          ...prev,
          [taskId]: {
            ...task,
            status: "pending_stac_approval",
            stacPreview: msg.preview,
            step: "STAC satellite preview ready \u2014 review required",
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "progress",
          taskId,
          text: "\u{1F6F0}\uFE0F Satellite scene previews ready \u2014 awaiting user approval"
        }
      ]);
    } else if (t === "stac_download_start") {
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        acts.push({
          type: "stac_download",
          filename: msg.filename,
          collection: msg.collection,
          item_id: msg.item_id,
          asset_key: msg.asset_key,
          date: msg.date,
          running: true
        });
        return {
          ...prev,
          [taskId]: {
            ...task,
            step: `Downloading ${msg.filename} at native resolution\u2026`,
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "progress",
          taskId,
          text: `\u2B07\uFE0F Downloading STAC band ${msg.filename} (native resolution)\u2026`
        }
      ]);
    } else if (t === "stac_download_done") {
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        let matched = false;
        const acts = (task.activities || []).map((act) => {
          if (act.type === "stac_download" && act.filename === msg.filename && act.running) {
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
              error: msg.error
            };
          }
          return act;
        });
        if (!matched) {
          acts.push({
            type: "stac_download",
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
            error: msg.error
          });
        }
        return {
          ...prev,
          [taskId]: {
            ...task,
            step: msg.ok ? `Downloaded ${msg.filename}` : `Failed downloading ${msg.filename}`,
            activities: acts
          }
        };
      });
    } else if (t === "stac_staged") {
      loadFiles();
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const acts = [...task.activities || []];
        acts.push({
          type: "stac_staged",
          files: msg.files || []
        });
        return {
          ...prev,
          [taskId]: {
            ...task,
            files: msg.files || task.files,
            step: `Staged ${(msg.files || []).length} native-resolution GeoTIFFs`,
            activities: acts
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "progress",
          taskId,
          text: `\u{1F4E5} Staged ${(msg.files || []).length} native-resolution GeoTIFFs`
        }
      ]);
    } else if (t === "plan_ready" || t === "plan_proposed") {
      setTasks((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          status: "pending_approval",
          plan: msg.plan,
          step: "Plan review required"
        }
      }));
      setFeedItems((prev) => [
        ...prev,
        {
          type: "plan_ready",
          taskId,
          plan: msg.plan
        }
      ]);
    } else if (t === "artifacts") {
      const arts = msg.artifacts || [];
      setTasks((prev) => ({
        ...prev,
        [taskId]: {
          ...prev[taskId],
          artifacts: arts,
          step: `Produced ${arts.length} artifacts`
        }
      }));
      setFeedItems((prev) => [
        ...prev,
        {
          type: "artifacts",
          taskId,
          artifacts: arts
        }
      ]);
    } else if (t === "finish") {
      const finalStatus = msg.status || (msg.ok ? "done" : "failed");
      setTasks((prev) => {
        const task = prev[taskId];
        if (!task) return prev;
        const textActivities = (task.activities || []).filter((a) => a.type === "text" && a.text && a.text.trim()).map((a) => a.text);
        const answer = textActivities.length > 0 ? textActivities.join("") : task.answer || null;
        return {
          ...prev,
          [taskId]: {
            ...task,
            status: finalStatus,
            error: msg.error || null,
            answer,
            step: finalStatus === "done" ? "Completed" : msg.error || finalStatus
          }
        };
      });
      setFeedItems((prev) => [
        ...prev,
        {
          type: "finish",
          taskId,
          status: finalStatus,
          error: msg.error
        }
      ]);
      if (streamsRef.current[taskId]) {
        streamsRef.current[taskId].close();
        delete streamsRef.current[taskId];
      }
      fetchArtifacts(taskId);
    }
  };
  const handleCreateWorkspace = (name) => {
    const trimmed = (name || "").trim();
    if (!trimmed) {
      showToast("Please provide a name for the workspace.", "warning");
      return;
    }
    if (workspaces.length >= 3) {
      showToast("\u26A0\uFE0F All containers allocated (3/3 active). Delete a workspace to free a container.", "warning", "Limit Reached");
      return;
    }
    const usedContainerIds = workspaces.map((w) => w.containerId);
    const availableContainerId = ["task_1", "task_2", "task_3"].find((cid) => !usedContainerIds.includes(cid));
    if (!availableContainerId) {
      showToast("\u26A0\uFE0F All containers allocated (3/3 active).", "warning");
      return;
    }
    const newWs = {
      id: "ws_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6),
      name: trimmed,
      containerId: availableContainerId,
      createdAt: Date.now()
    };
    setWorkspaces((prev) => [...prev, newWs]);
    setActiveWorkspaceId(newWs.id);
    setIsConsoleOpen(true);
    showToast(`Workspace "${trimmed}" created & allocated to Container #${availableContainerId.replace("task_", "")}`, "success", "Workspace Allocated");
  };
  const handleDeleteWorkspace = async (wsId) => {
    const ws = workspaces.find((w) => w.id === wsId);
    if (!ws) return;
    try {
      await fetch(`/api/tasks/${ws.containerId}/reset`, { method: "POST" });
    } catch (e) {
      console.warn("Backend task reset failed:", e);
    }
    if (streamsRef.current[ws.containerId]) {
      streamsRef.current[ws.containerId].close();
      delete streamsRef.current[ws.containerId];
    }
    setTasks((prev) => ({
      ...prev,
      [ws.containerId]: {
        status: "idle",
        question: "Slot idle \u2014 awaiting task assignment",
        step: "Ready",
        elapsed: 0,
        plan: null,
        artifacts: [],
        attempt: null,
        activities: []
      }
    }));
    setWorkspaces((prev) => {
      const remaining = prev.filter((w) => w.id !== wsId);
      if (activeWorkspaceId === wsId) {
        setActiveWorkspaceId(remaining.length > 0 ? remaining[0].id : null);
      }
      return remaining;
    });
    showToast(`Deleted workspace "${ws.name}". Container #${ws.containerId.replace("task_", "")} is now free.`, "info", "Container Freed");
  };
  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || null;
  const activeContainerId = activeWs ? activeWs.containerId : "task_1";
  const handleSubmitTask = async (question, fileList) => {
    if (!question || !question.trim()) {
      showToast("Please enter an analysis query before running.", "warning");
      return;
    }
    let targetContainerId = activeContainerId;
    if (!activeWs) {
      if (workspaces.length >= 3) {
        showToast("\u26A0\uFE0F All containers allocated (3/3 active). Free or delete a workspace to allocate a new container.", "warning");
        return;
      }
      const usedCids = workspaces.map((w) => w.containerId);
      const freeCid = ["task_1", "task_2", "task_3"].find((cid) => !usedCids.includes(cid)) || "task_1";
      const autoName = question.slice(0, 24) + (question.length > 24 ? "\u2026" : "");
      const newWs = {
        id: "ws_" + Date.now(),
        name: autoName,
        containerId: freeCid,
        createdAt: Date.now()
      };
      setWorkspaces((prev) => [...prev, newWs]);
      setActiveWorkspaceId(newWs.id);
      targetContainerId = freeCid;
    }
    setIsSubmitting(true);
    setIsConsoleOpen(true);
    try {
      const filesArg = (fileList || []).join(",");
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          files: filesArg,
          task_id: targetContainerId,
          bbox: activeAoiBbox || void 0
        })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "Failed to submit task", "error");
        setIsSubmitting(false);
        return;
      }
      const assignedTaskId = data.task_id;
      setTasks((prev) => ({
        ...prev,
        [assignedTaskId]: {
          ...prev[assignedTaskId],
          status: "running",
          question,
          files: fileList || [],
          step: "Task dispatched to Docker sandbox\u2026",
          elapsed: 0,
          plan: null,
          stacPreview: null,
          artifacts: [],
          activities: []
        }
      }));
      setFeedItems((prev) => [
        ...prev,
        {
          type: "progress",
          taskId: assignedTaskId,
          text: `\u{1F680} Task dispatched: "${question.slice(0, 80)}${question.length > 80 ? "\u2026" : ""}"`
        }
      ]);
      connectTaskStream(assignedTaskId);
      showToast(`Task assigned to Container #${assignedTaskId.replace("task_", "")}`, "info", "Execution Started");
    } catch (e) {
      console.error("Submit task error:", e);
      showToast("Network error while dispatching task", "error");
    } finally {
      setIsSubmitting(false);
    }
  };
  const handleApprovePlan = async (taskId) => {
    try {
      await fetch(`/api/tasks/${taskId}/approve`, { method: "POST" });
      setTasks((prev) => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: "running", plan: null, stacPreview: null, step: "Plan Approved \u2014 Running Container Pipeline" }
      }));
      setFeedItems((prev) => [
        ...prev,
        { type: "progress", taskId, text: "\u2705 Approved \u2014 resuming agent execution" }
      ]);
      showToast("Plan approved. Execution resuming...", "success");
    } catch (err) {
      console.error("Plan approval failed:", err);
      showToast("Failed to approve plan.", "error");
    }
  };
  const handleRevisePlan = async (taskId, feedback) => {
    try {
      await fetch(`/api/tasks/${taskId}/revise`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback })
      });
      setTasks((prev) => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: "running", plan: null, stacPreview: null }
      }));
      setFeedItems((prev) => [
        ...prev,
        { type: "progress", taskId, text: `\u{1F504} Revision feedback sent: "${feedback.slice(0, 60)}${feedback.length > 60 ? "\u2026" : ""}"` }
      ]);
      showToast("Feedback sent to container. Re-evaluating plan...", "info");
    } catch (err) {
      console.error("Plan revision failed:", err);
      showToast("Failed to send revision feedback.", "error");
    }
  };
  const handleCancelTask = async (taskId) => {
    try {
      await fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" });
      if (streamsRef.current[taskId]) {
        streamsRef.current[taskId].close();
        delete streamsRef.current[taskId];
      }
      setTasks((prev) => ({
        ...prev,
        [taskId]: { ...prev[taskId], status: "failed", error: "Cancelled by user", step: "Aborted" }
      }));
      setFeedItems((prev) => [
        ...prev,
        { type: "progress", taskId, text: "\u{1F6D1} Task aborted by user" }
      ]);
      showToast(`Aborted execution on container ${taskId}`, "warning");
    } catch (err) {
      console.error("Cancel task failed:", err);
      showToast("Failed to abort task.", "error");
    }
  };
  const handleOpenStacWithAoi = (bbox) => {
    setActiveAoiBbox(bbox);
    setStacModalOpen(true);
  };
  const handleSendAoiToTask = (bbox, targetTaskId) => {
    const tid = targetTaskId || activeContainerId;
    showToast(`Attached AOI coordinates to Container #${tid.replace("task_", "")}`, "info");
    setIsConsoleOpen(true);
  };
  const handleAssetStaged = (stagedData) => {
    showToast(`Staged ${stagedData.filename} (${stagedData.size_mb} MB) into data/`, "success");
    loadFiles();
  };
  return /* @__PURE__ */ React.createElement("div", { className: "app-shell", style: { display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", background: "#070A0F", color: "#F1F5F9" } }, /* @__PURE__ */ React.createElement(
    TaskTabs,
    {
      workspaces,
      activeWorkspaceId,
      onSelectWorkspace: (wsId) => {
        setActiveWorkspaceId(wsId);
        setIsConsoleOpen(true);
      },
      onCreateWorkspace: handleCreateWorkspace,
      tasks,
      isConsoleOpen,
      onToggleConsole: () => setIsConsoleOpen(!isConsoleOpen),
      supervisorOpen,
      onToggleSupervisor: () => setSupervisorOpen(!supervisorOpen),
      onOpenStacSearch: () => setStacModalOpen(true)
    }
  ), /* @__PURE__ */ React.createElement("div", { className: "geollm-studio-viewport", style: { flex: 1, position: "relative", overflow: "hidden", display: "flex", width: "100%", height: "100%" } }, /* @__PURE__ */ React.createElement(
    DatasetSidebar,
    {
      files,
      selectedFiles,
      setSelectedFiles,
      onUploadFiles: handleUploadFiles,
      onNotify: showToast,
      workspaces,
      activeWorkspaceId,
      onSelectWorkspace: (wsId) => {
        setActiveWorkspaceId(wsId);
        setIsConsoleOpen(true);
      },
      onCreateWorkspace: handleCreateWorkspace,
      onDeleteWorkspace: handleDeleteWorkspace
    }
  ), /* @__PURE__ */ React.createElement(
    "aside",
    {
      className: "connected-workspace-console",
      style: {
        position: "absolute",
        top: 0,
        bottom: 0,
        left: "330px",
        width: `${consoleWidth}px`,
        maxWidth: "calc(100vw - 360px)",
        height: "100%",
        background: "#0B0F17",
        borderRight: isResizingConsole ? "2px solid #38BDF8" : "1px solid #1E293B",
        overflow: "hidden",
        zIndex: 12,
        boxShadow: isConsoleOpen ? "6px 0 24px rgba(0,0,0,0.6)" : "none",
        transition: isResizingConsole ? "none" : "transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease",
        transform: isConsoleOpen ? "translateX(0)" : "translateX(-100%)",
        opacity: isConsoleOpen ? 1 : 0,
        pointerEvents: isConsoleOpen ? "auto" : "none",
        display: "flex",
        flexDirection: "column"
      }
    },
    /* @__PURE__ */ React.createElement(
      "div",
      {
        onMouseDown: handleStartConsoleResize,
        title: "Drag left or right to resize Workspace Console",
        style: {
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          width: "7px",
          cursor: "col-resize",
          zIndex: 30,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: isResizingConsole ? "rgba(56, 189, 248, 0.25)" : "transparent",
          transition: "background 0.15s ease"
        },
        onMouseEnter: (e) => {
          if (!isResizingConsole) e.currentTarget.style.background = "rgba(56, 189, 248, 0.18)";
        },
        onMouseLeave: (e) => {
          if (!isResizingConsole) e.currentTarget.style.background = "transparent";
        }
      },
      /* @__PURE__ */ React.createElement(
        "div",
        {
          style: {
            width: "2px",
            height: "36px",
            borderRadius: "2px",
            background: isResizingConsole ? "#38BDF8" : "#334155",
            pointerEvents: "none"
          }
        }
      )
    ),
    /* @__PURE__ */ React.createElement("div", { style: { width: "100%", height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" } }, /* @__PURE__ */ React.createElement(
      "div",
      {
        style: {
          padding: "10px 14px",
          background: "#090D14",
          borderBottom: "1px solid #1E293B",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          userSelect: "none",
          flexShrink: 0
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: "13px" } }, "\u{1F4AC}"), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, fontSize: "12.5px", color: "#F1F5F9" } }, activeWs ? activeWs.name : "Workspace Console"), /* @__PURE__ */ React.createElement(
        "span",
        {
          className: "mono",
          style: {
            fontSize: "10px",
            background: "#111827",
            color: "#14B8A6",
            padding: "2px 6px",
            borderRadius: "4px",
            fontWeight: 600,
            border: "1px solid #1E293B"
          }
        },
        "Container #",
        activeContainerId.replace("task_", "")
      )),
      /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          onClick: () => setIsConsoleOpen(false),
          style: {
            background: "#1E293B",
            border: "1px solid #334155",
            color: "#94A3B8",
            cursor: "pointer",
            fontSize: "11px",
            padding: "3px 8px",
            borderRadius: "4px",
            display: "flex",
            alignItems: "center",
            gap: "4px"
          },
          title: "Collapse Console Panel"
        },
        /* @__PURE__ */ React.createElement("span", null, "\u25C0"),
        /* @__PURE__ */ React.createElement("span", null, "Collapse")
      )
    ), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflowY: "auto", padding: "14px", display: "flex", flexDirection: "column", gap: "12px" } }, /* @__PURE__ */ React.createElement(
      QueryConsole,
      {
        files,
        selectedFiles,
        setSelectedFiles,
        onSubmitTask: (q, f) => handleSubmitTask(q, f),
        isSubmitting,
        onNotify: showToast
      }
    ), /* @__PURE__ */ React.createElement(
      SingleWorkerSlot,
      {
        taskId: activeContainerId,
        task: tasks[activeContainerId],
        onApprovePlan: handleApprovePlan,
        onRevisePlan: handleRevisePlan,
        onCancelTask: handleCancelTask,
        onPreviewFile: (art) => {
          const url = typeof art === "string" ? `/runs/${art}` : art.url || `/runs/${art.name}`;
          const name = typeof art === "string" ? art : art.name;
          setPreviewTarget({ url, name, type: name.endsWith(".tif") || name.endsWith(".tiff") ? "tif" : "img" });
        },
        onSwitchToGlobe: (art) => {
          if (art) setPendingGlobeArtifact(art);
          showToast("GeoTIFF layer projected onto 3D Globe", "info");
        },
        onNotify: showToast
      }
    )))
  ), /* @__PURE__ */ React.createElement("section", { className: "geollm-map-column", style: { flex: 1, height: "100%", position: "relative", overflow: "hidden", background: "#05080E" } }, /* @__PURE__ */ React.createElement(
    GlobeView,
    {
      tasks,
      activeTaskId: activeContainerId,
      activeWorkspaceName: activeWs ? activeWs.name : "",
      onOpenStacSearchWithAoi: handleOpenStacWithAoi,
      onSendAoiToTask: handleSendAoiToTask,
      pendingOverlay: pendingGlobeArtifact,
      onPendingOverlayConsumed: () => setPendingGlobeArtifact(null)
    }
  ))), /* @__PURE__ */ React.createElement(
    SupervisorDrawer,
    {
      isOpen: supervisorOpen,
      onClose: () => setSupervisorOpen(false),
      feedItems,
      onDispatchTask: (proposedPrompt) => handleSubmitTask(proposedPrompt, selectedFiles)
    }
  ), /* @__PURE__ */ React.createElement(
    StacModal,
    {
      isOpen: stacModalOpen,
      onClose: () => setStacModalOpen(false),
      initialBbox: activeAoiBbox,
      onAssetStaged: handleAssetStaged
    }
  ), /* @__PURE__ */ React.createElement(
    TiffPreviewModal,
    {
      previewTarget,
      onClose: () => setPreviewTarget(null)
    }
  ), /* @__PURE__ */ React.createElement(
    ToastContainer,
    {
      toasts,
      onDismiss: dismissToast
    }
  ));
}
export {
  App
};
