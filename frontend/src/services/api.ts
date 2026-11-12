// REST API client for the GeoLLM FastAPI backend.

import {
  FileInfo,
  RasterBoundsResponse,
  TimelinePayload,
  Terrain3DPayload,
  SupervisorChatMessage,
  SupervisorChatResponse,
} from '@/types/geospatial';
import {
  StacCollection,
  StacSearchParams,
  StacSearchResponse,
  StacStagePayload,
  StacDownloadsResponse,
} from '@/types/stac';
import { TaskSummary } from '@/types/task';
import { ArtifactItem } from '@/types/sse';

export interface TaskSubmissionParams {
  question: string;
  files?: string;
  bands?: string;
  bbox?: number[];
  task_id?: string;
}

export interface TaskSubmissionResponse {
  task_id: string;
  status: string;
  error?: string;
}

export interface ArtifactsResponse {
  artifacts: Array<string | ArtifactItem>;
  answer?: string | null;
  timeline_frames?: string[];
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let errorMsg = `HTTP ${res.status}`;
    try {
      const errData = await res.json();
      if (errData && errData.error) errorMsg = errData.error;
      else if (errData && errData.detail) errorMsg = errData.detail;
    } catch {
      // fallback to status code
    }
    throw new Error(errorMsg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Tasks
  async getTasks(): Promise<TaskSummary[]> {
    const data = await request<{ tasks: TaskSummary[] }>('/api/tasks');
    return data.tasks || [];
  },

  async submitTask(params: TaskSubmissionParams): Promise<TaskSubmissionResponse> {
    return request<TaskSubmissionResponse>('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
  },

  async cancelTask(taskId: string): Promise<{ ok?: boolean; status?: string; error?: string }> {
    return request<{ ok?: boolean; status?: string; error?: string }>(
      `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
      { method: 'POST' }
    );
  },

  async resetTask(taskId: string): Promise<{ ok?: boolean; status?: string; error?: string }> {
    return request<{ ok?: boolean; status?: string; error?: string }>(
      `/api/tasks/${encodeURIComponent(taskId)}/reset`,
      { method: 'POST' }
    );
  },

  async approveTask(taskId: string): Promise<{ ok?: boolean; status?: string; error?: string }> {
    return request<{ ok?: boolean; status?: string; error?: string }>(
      `/api/tasks/${encodeURIComponent(taskId)}/approve`,
      { method: 'POST' }
    );
  },

  async reviseTask(taskId: string, feedback: string): Promise<{ ok?: boolean; status?: string; error?: string }> {
    return request<{ ok?: boolean; status?: string; error?: string }>(
      `/api/tasks/${encodeURIComponent(taskId)}/revise`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback }),
      }
    );
  },

  async getArtifacts(taskId: string): Promise<ArtifactsResponse> {
    return request<ArtifactsResponse>(
      `/api/tasks/${encodeURIComponent(taskId)}/artifacts`
    );
  },

  // Files & Data Storage
  async getFiles(): Promise<FileInfo[]> {
    const data = await request<{ files: FileInfo[] }>('/api/files');
    return data.files || [];
  },

  async uploadFiles(fileList: File[] | FileList): Promise<{ uploaded: string[] }> {
    const formData = new FormData();
    for (let i = 0; i < fileList.length; i++) {
      formData.append('files', fileList[i]);
    }
    return request<{ uploaded: string[] }>('/api/upload', {
      method: 'POST',
      body: formData,
    });
  },

  // Geospatial Visualization Payloads
  async getRasterBounds(rasterPath: string): Promise<RasterBoundsResponse> {
    return request<RasterBoundsResponse>(
      `/api/raster/bounds?path=${encodeURIComponent(rasterPath)}`
    );
  },

  getRasterPngUrl(rasterPath: string): string {
    return `/api/raster/png?path=${encodeURIComponent(rasterPath)}`;
  },

  async getTimeline(taskId: string): Promise<TimelinePayload> {
    return request<TimelinePayload>(
      `/api/runs/${encodeURIComponent(taskId)}/timeline.json`
    );
  },

  async getTerrain3D(taskId: string): Promise<Terrain3DPayload> {
    return request<Terrain3DPayload>(
      `/api/runs/${encodeURIComponent(taskId)}/terrain_3d.json`
    );
  },

  // Microsoft Planetary Computer STAC
  async getStacCollections(): Promise<StacCollection[]> {
    const data = await request<{ collections: StacCollection[] }>('/api/stac/collections');
    return data.collections || [];
  },

  async searchStac(params: StacSearchParams): Promise<StacSearchResponse> {
    return request<StacSearchResponse>('/api/stac/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
  },

  async stageStacAsset(payload: StacStagePayload): Promise<{ ok: boolean; stage_id: string; status: string }> {
    return request<{ ok: boolean; stage_id: string; status: string }>('/api/stac/stage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async cancelStacDownload(stageId: string): Promise<{ ok: boolean; stage_id: string; status: string }> {
    return request<{ ok: boolean; stage_id: string; status: string }>('/api/stac/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage_id: stageId }),
    });
  },

  async getStacDownloads(): Promise<StacDownloadsResponse> {
    return request<StacDownloadsResponse>('/api/stac/downloads');
  },

  // AI Supervisor Chat
  async sendChatMessage(message: string, history: SupervisorChatMessage[] = []): Promise<SupervisorChatResponse> {
    return request<SupervisorChatResponse>('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
    });
  },
};

