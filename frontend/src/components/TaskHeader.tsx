import React, { useState } from 'react';
import { Workspace } from '@/types/task';
import { TaskStatus } from '@/types/sse';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/components/theme-provider';
import { Layers, Plus, Terminal, Satellite, Bot, CheckCircle2, AlertCircle, Clock, X, Sun, Moon } from 'lucide-react';

interface TaskHeaderProps {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  tasksStatus: Record<string, { status: TaskStatus; step?: string }>;
  onSelectWorkspace: (id: string) => void;
  onCreateWorkspace: (name: string) => void;
  onDeleteWorkspace?: (id: string) => void;
  isConsoleOpen: boolean;
  onToggleConsole: () => void;
  onOpenStac: () => void;
  onOpenSupervisor: () => void;
}

export const TaskHeader: React.FC<TaskHeaderProps> = ({
  workspaces,
  activeWorkspaceId,
  tasksStatus,
  onSelectWorkspace,
  onCreateWorkspace,
  onDeleteWorkspace,
  isConsoleOpen,
  onToggleConsole,
  onOpenStac,
  onOpenSupervisor,
}) => {
  const { theme, toggleTheme } = useTheme();
  const [isCreating, setIsCreating] = useState(false);
  const [newWsName, setNewWsName] = useState('');

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newWsName.trim()) {
      onCreateWorkspace(newWsName.trim());
      setNewWsName('');
      setIsCreating(false);
    }
  };

  const getStatusIcon = (status?: TaskStatus) => {
    if (status === 'running') {
      return <span className="h-2 w-2 rounded-full bg-sky-400 pulsing-glow" />;
    }
    if (status === 'done') {
      return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
    }
    if (status === 'failed') {
      return <AlertCircle className="h-3 w-3 text-rose-400" />;
    }
    if (status === 'pending_approval' || status === 'pending_stac_approval') {
      return <Clock className="h-3 w-3 text-amber-400 animate-pulse" />;
    }
    return <span className="h-2 w-2 rounded-full bg-muted-foreground" />;
  };

  return (
    <header className="h-12 border-b border-border bg-card px-3 flex items-center justify-between select-none z-20">
      {/* Brand & Container Allocation Counter */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 font-bold text-sm text-foreground tracking-tight">
          <Layers className="h-4 w-4 text-primary" />
          <span>GeoLLM</span>
          <span className="text-[10px] font-mono text-[#14B8A6] font-semibold bg-[#0F766E]/20 px-1.5 py-0.5 rounded-none border border-[#0F766E]/40">
            AUTONOMOUS
          </span>
        </div>

        <Badge variant="secondary" className="font-mono text-[11px]">
          Containers: {workspaces.length} / 3 Allocated
        </Badge>
      </div>

      {/* Dynamic Workspace Tabs */}
      <div className="flex items-center gap-1.5 flex-1 max-w-2xl mx-4 overflow-x-auto no-scrollbar">
        {workspaces.map((ws) => {
          const isActive = ws.id === activeWorkspaceId;
          const status = tasksStatus[ws.containerId]?.status || 'idle';
          const containerNum = ws.containerId.replace('task_', '#');

          return (
            <div
              key={ws.id}
              onClick={() => onSelectWorkspace(ws.id)}
              className={`group flex items-center gap-1.5 px-3 py-1.5 rounded-none text-xs font-medium border transition-all cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'bg-muted border-primary/50 text-foreground shadow-xs'
                  : 'bg-transparent border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50'
              }`}
            >
              {getStatusIcon(status)}
              <span className="font-mono text-[10px] text-muted-foreground bg-muted px-1 rounded-none">
                {containerNum}
              </span>
              <span className="max-w-[120px] truncate">{ws.name}</span>
              {onDeleteWorkspace && workspaces.length > 1 && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteWorkspace(ws.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive p-0.5 rounded transition-opacity cursor-pointer ml-0.5"
                  title={`Close workspace "${ws.name}"`}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}

        {/* Create Workspace Inline Button */}
        {workspaces.length < 3 && (
          isCreating ? (
            <form onSubmit={handleCreateSubmit} className="flex items-center gap-1">
              <input
                type="text"
                autoFocus
                placeholder="Workspace name..."
                value={newWsName}
                onChange={(e) => setNewWsName(e.target.value)}
                onBlur={() => !newWsName && setIsCreating(false)}
                className="h-7 w-32 px-2 text-xs bg-background border border-input rounded-none text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary font-mono"
              />
              <Button type="submit" size="sm" variant="teal" className="h-7 px-2 text-xs">
                Add
              </Button>
            </form>
          ) : (
            <button
              onClick={() => setIsCreating(true)}
              className="flex items-center gap-1 px-2 py-1.5 rounded-none text-xs text-muted-foreground hover:text-primary hover:bg-muted border border-dashed border-border cursor-pointer transition-colors"
              title="Allocate a new container sandbox"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>New</span>
            </button>
          )
        )}
      </div>

      {/* Global Actions */}
      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant={isConsoleOpen ? 'secondary' : 'outline'}
          onClick={onToggleConsole}
          className="h-7 text-xs gap-1.5"
          title="Toggle Workbench Console"
        >
          <Terminal className="h-3.5 w-3.5 text-primary" />
          <span>Console</span>
        </Button>

        <Button
          size="sm"
          variant="outline"
          onClick={onOpenStac}
          className="h-7 text-xs gap-1.5"
          title="Search Planetary Computer STAC"
        >
          <Satellite className="h-3.5 w-3.5 text-teal-400" />
          <span>STAC</span>
        </Button>

        <Button
          size="sm"
          variant="outline"
          onClick={onOpenSupervisor}
          className="h-7 text-xs gap-1.5"
          title="Open AI Supervisor"
        >
          <Bot className="h-3.5 w-3.5 text-purple-400" />
          <span>Supervisor</span>
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={toggleTheme}
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground"
          title="Toggle Theme (or press 'd')"
        >
          {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
        </Button>
      </div>
    </header>
  );
};
