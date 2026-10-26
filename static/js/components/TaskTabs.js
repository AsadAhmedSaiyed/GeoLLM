import { html } from '../html.js';

export function TaskTabs({
  activeTab,
  onSelectTab,
  tasks,
  supervisorOpen,
  onToggleSupervisor,
  onOpenStacSearch,
}) {
  const taskIds = ['task_1', 'task_2', 'task_3'];

  const getStatusBadge = (t) => {
    if (!t) return { label: 'Idle', color: '#5B6B64', bg: '#EAECE8' };
    if (t.status === 'running') {
      return {
        label: t.step ? 'Running' : 'Active',
        color: '#92400E',
        bg: '#FEF3C7',
        pulse: true,
      };
    }
    if (t.status === 'pending_approval') {
      return { label: 'Review Plan', color: '#3730A3', bg: '#E0E7FF', pulse: true };
    }
    if (t.status === 'done') {
      return { label: 'Done', color: '#166534', bg: '#DCFCE7' };
    }
    if (t.status === 'failed') {
      return { label: 'Failed', color: '#991B1B', bg: '#FEE2E2' };
    }
    return { label: 'Idle', color: '#5B6B64', bg: '#EAECE8' };
  };

  return html`
    <header className="task-tabs-header">
      <div className="task-tabs-container">
        <!-- Brand / Logo -->
        <div className="task-tabs-brand">
          <div className="brand-dot"></div>
          <span className="brand-name">GeoLLM</span>
          <span className="brand-badge">Autonomous</span>
        </div>

        <!-- Navigation Tabs -->
        <nav className="task-tabs-nav" aria-label="Task Sandboxes">
          <!-- Globe Tab -->
          <button
            type="button"
            className="tab-button ${activeTab === 'globe' ? 'active' : ''}"
            onClick=${() => onSelectTab('globe')}
            title="3D Interactive Globe & Satellite Overlays"
          >
            <span className="tab-icon">🌍</span>
            <span className="tab-title">3D Globe</span>
          </button>

          <!-- Task 1, 2, 3 Tabs -->
          ${taskIds.map((tid, idx) => {
            const task = tasks[tid];
            const badge = getStatusBadge(task);
            const isActive = activeTab === tid;
            const taskNum = idx + 1;

            return html`
              <button
                key=${tid}
                type="button"
                className="tab-button ${isActive ? 'active' : ''}"
                onClick=${() => onSelectTab(tid)}
                title="Sandbox Slot #${taskNum}"
              >
                <span className="tab-num">#${taskNum}</span>
                <span className="tab-title">
                  ${task?.question
                    ? task.question.slice(0, 22) + (task.question.length > 22 ? '…' : '')
                    : `Task #${taskNum}`}
                </span>
                <span
                  className="tab-badge ${badge.pulse ? 'pulse' : ''}"
                  style=${{ color: badge.color, backgroundColor: badge.bg }}
                >
                  ${badge.label}
                </span>
              </button>
            `;
          })}
        </nav>

        <!-- Right Action Controls -->
        <div className="task-tabs-actions">
          <button
            type="button"
            className="action-btn stac-btn"
            onClick=${onOpenStacSearch}
            title="Search & Retrieve Satellite Imagery via Microsoft Planetary Computer"
          >
            <span style=${{ marginRight: '5px' }}>🛰️</span>
            <span>Planetary Computer</span>
          </button>

          <button
            type="button"
            className="action-btn supervisor-btn ${supervisorOpen ? 'active' : ''}"
            onClick=${onToggleSupervisor}
            title="Toggle Main LLM Supervisor Assistant"
          >
            <span style=${{ marginRight: '5px' }}>💬</span>
            <span>Supervisor AI</span>
          </button>
        </div>
      </div>
    </header>
  `;
}
