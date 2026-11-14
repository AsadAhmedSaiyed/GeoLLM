// GeoLLM Modern Frontend - Phase 5 Complete Geospatial Workbench
// Assembles TaskHeader, QueryConsole, SingleWorkerSlot (with Vision QA & TimeSeriesPanel),
// GlobeView (MapLibre 3D Globe), Terrain3DViewer (Three.js DEM/LiDAR), TiffPreviewModal, StacModal, and SupervisorDrawer.

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Workspace } from '@/types/task';
import { ArtifactItem, TaskStatus } from '@/types/sse';
import { api } from '@/services/api';
import { useMultiTaskStreams, DEFAULT_TASK_STATE } from '@/hooks/useTaskStream';
import { TaskHeader } from '@/components/TaskHeader';
import { QueryConsole } from '@/components/QueryConsole';
import { SingleWorkerSlot } from '@/components/SingleWorkerSlot';
import { GlobeView } from '@/components/GlobeView';
import { Terrain3DViewer } from '@/components/Terrain3DViewer';
import { TimeSeriesPanel } from '@/components/TimeSeriesPanel';
import { TiffPreviewModal, PreviewTarget } from '@/components/TiffPreviewModal';
import { StacModal } from '@/components/StacModal';
import { useResizableOverlay } from '@/hooks/useResizableOverlay';
import { ChatLayout } from '@/components/ui/chat';
import { Toaster } from '@/components/ui/sonner';
import { toast } from 'sonner';
import { Terminal } from 'lucide-react';

interface Terrain3DModalState {
  isOpen: boolean;
  taskId: string;
  payloadUrl: string;
  availableTextures: Array<string | ArtifactItem>;
  title: string;
}

export function App() {
  // 1. Dynamic Workspaces (persisted to localStorage)
  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    try {
      const saved = localStorage.getItem('geollm_workspaces');
      if (saved) return JSON.parse(saved);
    } catch {}
    return [
      { id: 'ws_default', name: 'Analysis 1', containerId: 'task_1', createdAt: Date.now() },
    ];
  });

  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(() => {
    try {
      const saved = localStorage.getItem('geollm_workspaces');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.length > 0) return parsed[0].id;
      }
    } catch {}
    return 'ws_default';
  });

  useEffect(() => {
    try {
      localStorage.setItem('geollm_workspaces', JSON.stringify(workspaces));
    } catch {}
  }, [workspaces]);

  // Active workspace & active container
  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeWorkspaceId) || null,
    [workspaces, activeWorkspaceId]
  );
  const activeContainerId = activeWorkspace ? activeWorkspace.containerId : 'task_1';

  // 2. Selected input files & modal states
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [stacModalOpen, setStacModalOpen] = useState(false);
  const [stacInitialBbox, setStacInitialBbox] = useState<number[] | null>(null);
  const [previewTarget, setPreviewTarget] = useState<PreviewTarget | null>(null);
  const [pendingGlobeOverlay, setPendingGlobeOverlay] = useState<string | ArtifactItem | null>(
    null
  );
  const [focusOutputsNonce, setFocusOutputsNonce] = useState(0);
  const [injectedPrompt, setInjectedPrompt] = useState<string | null>(null);
  const [workspaceTurns, setWorkspaceTurns] = useState<Record<string, Array<{ id?: string; seq?: number; role: 'user' | 'assistant'; content: string; timestamp?: number; type?: any; question?: string; thumb_url?: string; fly_to_bbox?: number[]; follow_ups?: string[] }>>>({});
  const [globeFlyToBbox, setGlobeFlyToBbox] = useState<number[] | null>(null);

  // Chat Workspace Overlay Hook: Anchored Left, Expands Right up to 88% viewport
  const {
    panelWidth,
    isCollapsed,
    isDragging,
    toggleCollapse,
    handleMouseDown: handleOverlayResizeStart,
    setIsCollapsed,
  } = useResizableOverlay({
    storageKey: 'geollm_chat_overlay_width',
    defaultWidth: 480,
    minWidth: 340,
    maxWidthRatio: 0.88,
    snapThreshold: 180,
  });
  const [terrain3DModal, setTerrain3DModal] = useState<Terrain3DModalState>({
    isOpen: false,
    taskId: '',
    payloadUrl: '',
    availableTextures: [],
    title: '3D Digital Elevation Model',
  });

  const handleTaskResumed = useCallback((taskId: string, question: string, step: string) => {
    const slotNum = taskId.replace('task_', '#');
    const shortQ = question ? (question.length > 55 ? question.slice(0, 52) + '...' : question) : '';
    toast.info(`Container ${slotNum} resumed from checkpoint`, {
      description: step || shortQ || 'Auto-resuming task execution...',
      duration: 5000,
    });
  }, []);

  // 3. Multi-container SSE streaming & state across task_1, task_2, task_3
  const {
    tasks,
    setTasks,
    startSlotStream,
    stopSlotStream,
    resetSlotState,
  } = useMultiTaskStreams({
    onTaskResumed: handleTaskResumed,
  });

  // Load durable conversation history when switching workspaces
  useEffect(() => {
    if (!activeContainerId) return;
    let cancelled = false;
    api
      .getWorkspaceConversation(activeContainerId)
      .then((res) => {
        if (cancelled || !res.turns) return;
        setWorkspaceTurns((prev) => {
          if ((prev[activeContainerId] || []).length > 0) return prev;
          return {
            ...prev,
            [activeContainerId]: res.turns.map((t) => ({
              role: t.role === 'assistant' ? 'assistant' : 'user',
              content: t.content,
              timestamp: t.timestamp,
              thumb_url: t.thumb_url,
              fly_to_bbox: t.fly_to_bbox,
            })),
          };
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeContainerId]);

  const activeTask = tasks[activeContainerId] || DEFAULT_TASK_STATE;

  // Notification helper passed down to components
  const handleNotify = useCallback(
    (message: string, type: 'info' | 'warning' | 'error' | 'success' = 'info') => {
      if (type === 'error') toast.error(message);
      else if (type === 'warning') toast.warning(message);
      else if (type === 'success') toast.success(message);
      else toast.info(message);
    },
    []
  );

  // Helper to convert artifact or path into PreviewTarget for TiffPreviewModal
  const openArtifactPreview = useCallback((art: string | ArtifactItem) => {
    const rawPath =
      typeof art === 'string' ? art : art.url || art.path || art.name || '';
    const rawName =
      typeof art === 'object' && art.name
        ? art.name
        : rawPath.replace(/\\/g, '/').split('/').pop() || rawPath;
    const cleanName = rawName.replace(/\\/g, '/').split('/').pop() || rawName;
    const cleanUrl = rawPath.replace(/\\/g, '/');
    const url =
      cleanUrl.startsWith('http') || cleanUrl.startsWith('/')
        ? cleanUrl
        : `/${cleanUrl}`;
    const isTif = /\.(tif|tiff)$/i.test(cleanName) || /\.(tif|tiff)$/i.test(rawPath);

    setPreviewTarget({
      name: cleanName,
      url,
      path: rawPath,
      type: isTif ? 'tif' : 'img',
    });
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewTarget(null);
  }, []);

  // Handlers for Workspaces
  const handleCreateWorkspace = (name: string) => {
    if (workspaces.length >= 3) {
      toast.warning('All 3 sandbox slots allocated', {
        description: 'Delete a workspace to free a container slot.',
      });
      return;
    }

    const usedIds = workspaces.map((w) => w.containerId);
    const freeId = (['task_1', 'task_2', 'task_3'] as const).find((cid) => !usedIds.includes(cid));
    if (!freeId) return;

    const newWs: Workspace = {
      id: `ws_${Date.now()}`,
      name,
      containerId: freeId,
      createdAt: Date.now(),
    };

    setWorkspaces((prev) => [...prev, newWs]);
    setActiveWorkspaceId(newWs.id);
    setWorkspaceTurns((prev) => {
      const next = { ...prev };
      delete next[freeId];
      return next;
    });
    api.clearWorkspaceConversation(freeId).catch(() => {});
    toast.success(`Workspace "${name}" allocated to Container #${freeId.replace('task_', '')}`);
  };

  const handleDeleteWorkspace = async (wsId: string) => {
    const ws = workspaces.find((w) => w.id === wsId);
    if (!ws) return;

    try {
      resetSlotState(ws.containerId);
      setWorkspaceTurns((prev) => {
        const next = { ...prev };
        delete next[ws.containerId];
        return next;
      });
      await Promise.allSettled([
        api.clearWorkspaceConversation(ws.containerId),
        api.resetTask(ws.containerId),
      ]);
    } catch {
      // ignore
    }

    setWorkspaces((prev) => {
      const remaining = prev.filter((w) => w.id !== wsId);
      if (activeWorkspaceId === wsId) {
        setActiveWorkspaceId(remaining.length > 0 ? remaining[0].id : null);
      }
      return remaining;
    });

    toast.info(
      `Deleted workspace "${ws.name}". Container #${ws.containerId.replace('task_', '')} is now free.`
    );
  };

  // Handlers for File Selection & Upload
  const handleToggleFile = (fileName: string) => {
    setSelectedFiles((prev) =>
      prev.includes(fileName) ? prev.filter((f) => f !== fileName) : [...prev, fileName]
    );
  };

  const handleUploadFiles = async (fileList: FileList) => {
    toast.info(`Uploading ${fileList.length} file(s)...`);
    try {
      const res = await api.uploadFiles(fileList);
      if (res.uploaded && res.uploaded.length > 0) {
        setSelectedFiles((prev) => Array.from(new Set([...prev, ...res.uploaded])));
        toast.success(`Uploaded and attached ${res.uploaded.length} file(s).`);
      }
    } catch (err) {
      toast.error('File upload failed', {
        description: err instanceof Error ? err.message : String(err),
      });
    }
  };

  // Submit Task Dispatcher via Unified Conversational Router
  const dispatchTaskToSlot = async (question: string, targetSlotId?: string) => {
    if (!activeWorkspace) {
      toast.error('No active workspace selected. Please click "+ New" above to create a workspace first.');
      return;
    }

    const targetContainerId = targetSlotId || activeWorkspace.containerId;
    setIsSubmitting(true);

    // Optimistically record user turn in local state (seconds to match backend time.time())
    setWorkspaceTurns((prev) => ({
      ...prev,
      [targetContainerId]: [
        ...(prev[targetContainerId] || []),
        { role: 'user', content: question, timestamp: Date.now() / 1000 },
      ],
    }));

    try {
      const history = (workspaceTurns[targetContainerId] || []).map((t) => ({
        role: t.role,
        content: t.content,
      }));

      const res = await api.sendWorkspaceMessage(targetContainerId, {
        message: question,
        history,
        files: selectedFiles.join(','),
      });

      // Automatically clear selected files once dispatched
      if (selectedFiles.length > 0) setSelectedFiles([]);

      if (res.type === 'task_delegated') {
        toast.info(`Geospatial task delegated to Container #${targetContainerId.replace('task_', '')}`);
        setWorkspaceTurns((prev) => ({
          ...prev,
          [targetContainerId]: [
            ...(prev[targetContainerId] || []),
            {
              role: 'assistant',
              content: `Delegated complex geospatial task to specialized container sub-agent: *${question}*`,
              timestamp: res.timestamp || Date.now() / 1000,
              seq: res.seq,
              type: 'task_delegated',
              question,
            },
          ],
        }));
        setTasks((prev) => ({
          ...prev,
          [targetContainerId]: {
            ...DEFAULT_TASK_STATE,
            status: 'running',
            question,
            step: 'Starting Container Sandbox',
            elapsed: 0,
          },
        }));
        startSlotStream(targetContainerId, 0);
      } else if (res.type === 'workspace_busy') {
        toast.warning(res.reply || 'Workspace is currently busy');
        setWorkspaceTurns((prev) => ({
          ...prev,
          [targetContainerId]: [
            ...(prev[targetContainerId] || []),
            {
              role: 'assistant',
              content: res.reply || 'Workspace container is currently executing another task.',
              timestamp: res.timestamp || Date.now() / 1000,
              seq: res.seq,
              type: 'clarification',
              follow_ups: [
                'Switch to Workspace 2',
                'Wait for this task to finish',
              ],
            },
          ],
        }));
      } else if (res.type === 'visual_reply') {
        toast.success('Visual inspection completed by VLM');
        if (res.fly_to_bbox && res.fly_to_bbox.length >= 4) {
          setGlobeFlyToBbox(res.fly_to_bbox);
        }
        setWorkspaceTurns((prev) => ({
          ...prev,
          [targetContainerId]: [
            ...(prev[targetContainerId] || []),
            {
              role: 'assistant',
              content: res.reply || '',
              timestamp: res.timestamp || Date.now() / 1000,
              seq: res.seq,
              type: 'visual_reply',
              thumb_url: res.thumb_url,
              fly_to_bbox: res.fly_to_bbox,
              follow_ups: res.follow_ups,
            },
          ],
        }));
      } else {
        // Conversational or clarification reply
        setWorkspaceTurns((prev) => ({
          ...prev,
          [targetContainerId]: [
            ...(prev[targetContainerId] || []),
            {
              role: 'assistant',
              content: res.reply || '',
              timestamp: res.timestamp || Date.now() / 1000,
              seq: res.seq,
              type: res.type,
              follow_ups: res.follow_ups,
            },
          ],
        }));
      }
    } catch (err) {
      toast.error('Assistant error', {
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitTask = async (question: string) => {
    await dispatchTaskToSlot(question, activeContainerId);
  };

  // Human-in-the-Loop Gate Handlers
  const handleApprovePlan = async (tid: string) => {
    try {
      const res = await api.approveTask(tid);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setTasks((prev) => ({
        ...prev,
        [tid]: {
          ...(prev[tid] || DEFAULT_TASK_STATE),
          status: 'running',
          step: 'Approved — executing in sandbox…',
        },
      }));
      startSlotStream(tid, 0);
      toast.success('Approved — executing in sandbox');
    } catch (err) {
      toast.error(`Failed to approve: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleRevisePlan = async (tid: string, feedback: string) => {
    try {
      const res = await api.reviseTask(tid, feedback);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setTasks((prev) => ({
        ...prev,
        [tid]: {
          ...(prev[tid] || DEFAULT_TASK_STATE),
          status: 'running',
          step: 'Revising based on feedback…',
        },
      }));
      startSlotStream(tid, 0);
      toast.info('Revising based on your feedback…');
    } catch (err) {
      toast.error(`Failed to revise: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleCancelTask = async (tid: string) => {
    try {
      const res = await api.cancelTask(tid);
      if (res.error) {
        toast.error(res.error);
        return;
      }
      stopSlotStream(tid);
      setTasks((prev) => ({
        ...prev,
        [tid]: {
          ...(prev[tid] || DEFAULT_TASK_STATE),
          status: 'failed',
          step: 'Aborted by user',
          error: 'Aborted by user',
        },
      }));
      toast.warning(`Task ${tid.replace('task_', '#')} aborted`);
    } catch (err) {
      toast.error(`Failed to cancel task: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleResetTask = async (tid: string) => {
    try {
      await api.resetTask(tid);
      resetSlotState(tid);
      toast.success(`Container ${tid.replace('task_', '#')} reset to clean idle state.`);
    } catch (err) {
      toast.error(`Failed to reset task: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleClearHistory = async (tid: string) => {
    try {
      await api.clearWorkspaceConversation(tid);
      setWorkspaceTurns((prev) => ({ ...prev, [tid]: [] }));
      toast.success('Chat history cleared');
    } catch (err) {
      toast.error(`Failed to clear chat history: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const tasksStatus = useMemo<Record<string, { status: TaskStatus; step?: string }>>(() => {
    const map: Record<string, { status: TaskStatus; step?: string }> = {};
    Object.entries(tasks).forEach(([tid, t]) => {
      map[tid] = { status: t.status, step: t.step };
    });
    return map;
  }, [tasks]);

  return (
    <div className="flex flex-col h-screen w-screen bg-background text-foreground overflow-hidden font-sans">
      <Toaster />

      {/* Top Navigation & Workspace Header */}
      <TaskHeader
        workspaces={workspaces}
        activeWorkspaceId={activeWorkspaceId}
        tasksStatus={tasksStatus}
        onSelectWorkspace={(id) => {
          setActiveWorkspaceId(id);
          setIsCollapsed(false);
        }}
        onCreateWorkspace={handleCreateWorkspace}
        onDeleteWorkspace={handleDeleteWorkspace}
        isConsoleOpen={!isCollapsed}
        onToggleConsole={toggleCollapse}
        onOpenStac={() => {
          setStacInitialBbox(null);
          setStacModalOpen(true);
        }}
      />

      {/* Main Responsive Viewport: Full-Size 3D Map with Floating Chat Overlay */}
      <div className="flex-1 overflow-hidden">
        <div className="relative w-full h-full overflow-hidden bg-background">
              {/* Layer 0: 3D MapLibre Globe occupies 100% full size underneath. NEVER RESIZES DURING CHAT DRAG. */}
              <div className="absolute inset-0 w-full h-full">
                <GlobeView
                  tasks={tasks}
                  activeTaskId={activeContainerId}
                  activeWorkspaceName={activeWorkspace?.name || activeContainerId}
                  onOpenStacSearchWithAoi={(bbox) => {
                    setStacInitialBbox(bbox);
                    setStacModalOpen(true);
                  }}
                  onSendAoiToTask={(bbox) => {
                    setIsCollapsed(false);
                    setInjectedPrompt(
                      `[AOI BBOX: ${bbox[0]}, ${bbox[1]}, ${bbox[2]}, ${bbox[3]}]`
                    );
                    toast.success('AOI coordinates appended to Workspace Console');
                  }}
                  pendingOverlay={pendingGlobeOverlay}
                  onPendingOverlayConsumed={() => setPendingGlobeOverlay(null)}
                  onPreviewArtifact={openArtifactPreview}
                  focusOutputsNonce={focusOutputsNonce}
                  flyToBbox={globeFlyToBbox}
                />
              </div>

              {/* Layer 1: Floating Chat Workspace Overlay Anchored to Left, Expanding Right Only */}
              <div
                style={{
                  width: isCollapsed ? 48 : panelWidth,
                  transition: isDragging ? 'none' : 'width 240ms cubic-bezier(0.16, 1, 0.3, 1)',
                }}
                className="absolute top-0 bottom-0 left-0 z-20 flex bg-card/95 backdrop-blur-md border-r border-border shadow-[12px_0_36px_rgba(0,0,0,0.65)] overflow-hidden"
              >
                {/* When Collapsed: Compact Vertical Status Bar */}
                {isCollapsed ? (
                  <div
                    onClick={toggleCollapse}
                    title="Click or drag right to expand Chat Workspace"
                    className="w-12 h-full flex flex-col items-center justify-between py-4 cursor-pointer select-none hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex flex-col items-center gap-3">
                      <div className="p-2 rounded-lg bg-primary/15 text-primary border border-primary/30">
                        <Terminal className="h-4 w-4" />
                      </div>
                      <span className="font-mono text-[10px] font-bold text-foreground [writing-mode:vertical-rl] rotate-180 tracking-wider uppercase">
                        {activeWorkspace?.name || 'Console'}
                      </span>
                    </div>

                    <div className="flex flex-col items-center gap-2">
                      <span
                        className={`h-2.5 w-2.5 rounded-full ${
                          activeTask.status === 'running'
                            ? 'bg-primary animate-pulse'
                            : activeTask.status === 'done'
                            ? 'bg-emerald-400'
                            : activeTask.status === 'failed'
                            ? 'bg-destructive'
                            : 'bg-muted-foreground'
                        }`}
                      />
                      <span className="text-[10px] font-mono text-muted-foreground">
                        #{activeContainerId.replace('task_', '')}
                      </span>
                    </div>
                  </div>
                ) : (
                  /* When Expanded: Unified Astryx ChatLayout (Feed Top -> Bottom-Anchored Composer) */
                  <ChatLayout className="flex-1 min-w-[320px] overflow-hidden">
                    <div className="flex-1 min-h-0 overflow-hidden">
                      {activeWorkspace ? (
                        <SingleWorkerSlot
                          taskId={activeContainerId}
                          task={activeTask}
                          conversationTurns={workspaceTurns[activeContainerId] || []}
                          onSelectFollowUp={(prompt) => {
                            setInjectedPrompt(prompt);
                          }}
                          onFlyToBbox={(bbox) => {
                            setGlobeFlyToBbox(bbox);
                          }}
                          onApprovePlan={handleApprovePlan}
                          onRevisePlan={handleRevisePlan}
                          onCancelTask={handleCancelTask}
                          onResetTask={handleResetTask}
                          onClearHistory={handleClearHistory}
                          onPreviewFile={(art) => openArtifactPreview(art)}
                          onSwitchToGlobe={(art) => {
                            if (art) {
                              setPendingGlobeOverlay(art);
                              toast.info('Projecting georeferenced raster onto 3D Globe...');
                            }
                          }}
                          onSeeOutputs={() => setFocusOutputsNonce((n) => n + 1)}
                          onOpenTerrain3D={(info) => {
                            setTerrain3DModal({
                              isOpen: true,
                              taskId: info.taskId,
                              payloadUrl: info.payloadUrl,
                              availableTextures: info.availableTextures,
                              title: info.title,
                            });
                          }}
                          onNotify={handleNotify}
                          renderTimeSeriesPanel={({ taskId, runDir, onFrameChange }) => (
                            <TimeSeriesPanel
                              taskId={taskId}
                              runDir={runDir}
                              onFrameChange={onFrameChange}
                            />
                          )}
                        />
                      ) : (
                        <div className="h-full flex flex-col items-center justify-center text-center p-6 text-muted-foreground">
                          <div className="text-sm font-semibold text-foreground mb-1">
                            No Active Workspace Selected
                          </div>
                          <div className="text-xs text-muted-foreground max-w-xs">
                            Create or select a workspace tab in the top navigation bar to open its sandbox container.
                          </div>
                        </div>
                      )}
                    </div>

                    <QueryConsole
                      selectedFiles={selectedFiles}
                      onRemoveFile={handleToggleFile}
                      onClearAllFiles={() => setSelectedFiles([])}
                      onUploadFiles={handleUploadFiles}
                      onSubmit={handleSubmitTask}
                      isSubmitting={isSubmitting}
                      isRunning={activeTask.status === 'running'}
                      hasActiveWorkspace={Boolean(activeWorkspace)}
                      injectedPrompt={injectedPrompt}
                      onInjectedPromptConsumed={() => setInjectedPrompt(null)}
                    />
                  </ChatLayout>
                )}

                {/* Right-Edge Drag Handle: Drag right to expand, drag left to contract, double-click to collapse/expand */}
                <div
                  onMouseDown={handleOverlayResizeStart}
                  onDoubleClick={toggleCollapse}
                  title="Drag to resize (right) • Double-click to collapse/expand"
                  className="w-2.5 h-full cursor-col-resize hover:bg-[#14B8A6]/30 active:bg-[#14B8A6]/50 transition-colors flex items-center justify-center shrink-0 border-l border-border select-none"
                >
                  <div className="w-[3px] h-7 rounded-none-none bg-slate-600 hover:bg-[#2DD4BF] transition-colors" />
                </div>
              </div>
        </div>
      </div>

      {/* Planetary Computer STAC Explorer Modal */}
      <StacModal
        isOpen={stacModalOpen}
        onClose={() => setStacModalOpen(false)}
        initialBbox={stacInitialBbox}
        onAssetStaged={(info) => {
          toast.success(`Staged ${info.filename || 'GeoTIFF'} (${info.size_mb ?? '?'} MB) to /data`);
        }}
        onNotify={handleNotify}
      />

      {/* Three.js 3D Terrain & LiDAR Point Cloud Viewer Modal */}
      <Terrain3DViewer
        isOpen={terrain3DModal.isOpen}
        onClose={() => setTerrain3DModal((prev) => ({ ...prev, isOpen: false }))}
        payloadUrl={terrain3DModal.payloadUrl}
        availableTextures={terrain3DModal.availableTextures}
        title={terrain3DModal.title}
      />

      {/* GeoTIFF & Deliverable Scientific Inspector Modal */}
      <TiffPreviewModal
        previewTarget={previewTarget}
        onClose={handleClosePreview}
        onOverlayOnGlobe={(target) => {
          setPendingGlobeOverlay(target.path || target.url);
          toast.info(`Projecting ${target.name} onto 3D Globe...`);
        }}
      />
    </div>
  );
}
