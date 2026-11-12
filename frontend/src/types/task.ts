// Task and Workspace data structures for the GeoLLM state hub.

import {
  TaskStatus,
  StacPreviewPayload,
  ArtifactItem,
  GeoLLMSSEEvent,
} from './sse';

export type ActivityItem =
  | {
      type: 'text';
      text: string;
      timestamp: number;
    }
  | {
      type: 'thinking';
      text: string;
      timestamp: number;
    }
  | {
      type: 'tool';
      id?: string;
      toolName: string;
      args?: Record<string, unknown> | string;
      attempt?: number;
      code_attempt?: number;
      max_attempts?: number;
      running: boolean;
      ok?: boolean;
      exit_code?: number;
      duration_s?: number;
      error?: string;
      stdout?: string;
    }
  | {
      type: 'stac_preview_ready';
      preview: StacPreviewPayload;
    }
  | {
      type: 'stac_download';
      filename: string;
      collection?: string;
      item_id?: string;
      asset_key?: string;
      date?: string;
      band_index?: number;
      total_bands?: number;
      band_pct?: number;
      overall_pct?: number;
      elapsed_s?: number;
      cached?: boolean;
      running: boolean;
      ok?: boolean;
      path?: string;
      size_mb?: number | null;
      width?: number | null;
      height?: number | null;
      resolution?: number | null;
      duration_s?: number;
      error?: string;
    }
  | {
      type: 'stac_staged';
      files: string[];
    }
  | {
      type: 'vision_check';
      image: string;
      state: 'started' | 'done';
      verdict?: string;
      text?: string;
      index?: number;
      total?: number;
    }
  | (GeoLLMSSEEvent & { timestamp?: number });

export interface TaskState {
  status: TaskStatus;
  question: string;
  step: string;
  elapsed: number;
  plan: string | null;
  stacPreview: StacPreviewPayload | null;
  artifacts: Array<string | ArtifactItem>;
  attempt: number | null;
  code_attempt?: number;
  max_attempts?: number;
  activities: ActivityItem[];
  answer?: string | null;
  error?: string | null;
  files?: string[];
  run_dir?: string;
}

export interface TaskSummary {
  task_id: string;
  status: TaskStatus;
  question?: string;
  step?: string;
  error?: string | null;
  elapsed?: number;
  plan?: string | null;
  stac_preview?: StacPreviewPayload | null;
}

export interface Workspace {
  id: string;
  name: string;
  containerId: 'task_1' | 'task_2' | 'task_3' | string;
  createdAt: number;
}

