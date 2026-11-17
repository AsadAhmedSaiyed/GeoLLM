// REST API client for the GeoLLM FastAPI backend.

import {
  FileInfo,
  RasterBoundsResponse,
  RasterStatsResponse,
  RasterPixelResponse,
  FileInspectResponse,
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

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let errorMsg = `Server error (HTTP ${res.status})`;
    let errorCode: string | undefined;
    try {
      const text = await res.text();
      try {
        const errData = JSON.parse(text);
        if (errData?.error) errorMsg = String(errData.error);
        else if (errData?.detail) errorMsg = String(errData.detail);
        if (errData?.code) errorCode = String(errData.code);
      } catch {
        if (text && text.trim() && text.length < 300) errorMsg = text.trim();
      }
    } catch {
      // fallback to status code
    }
    throw new ApiError(errorMsg, res.status, errorCode);
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

  async uploadFiles(
    fileList: File[] | FileList,
    onProgress?: (info: {
      percent: number;
      loadedMb: number;
      totalMb: number;
      fileName: string;
      instant?: boolean;
    }) => void
  ): Promise<{ uploaded: string[]; instantCount?: number }> {
    const filesArr = Array.from(fileList);
    if (filesArr.length === 0) return { uploaded: [] };

    let existingFiles: FileInfo[] = [];
    try {
      existingFiles = await this.getFiles();
    } catch {
      existingFiles = [];
    }

    const uploaded: string[] = [];
    let instantCount = 0;

    for (const file of filesArr) {
      const totalMb = Math.round((file.size / (1024 * 1024)) * 10) / 10;
      const fileMbExact = file.size / (1024 * 1024);
      const match = existingFiles.find(
        (ef) =>
          ef.name === file.name &&
          (ef.size_bytes != null
            ? ef.size_bytes === file.size
            : Math.abs(ef.size_mb - fileMbExact) < 0.05)
      );

      if (match) {
        uploaded.push(file.name);
        instantCount += 1;
        onProgress?.({
          percent: 100,
          loadedMb: totalMb,
          totalMb,
          fileName: file.name,
          instant: true,
        });
        continue;
      }

      // Stream raw file binary directly to /api/upload/stream with live progress
      const streamUrl = `/api/upload/stream?filename=${encodeURIComponent(file.name)}&size=${file.size}`;
      const res = await new Promise<{ uploaded: string[] }>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', streamUrl, true);
        xhr.setRequestHeader('Content-Type', 'application/octet-stream');

        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable && ev.total > 0) {
            const pct = Math.min(100, Math.round((ev.loaded / ev.total) * 100));
            const loadedMb = Math.round((ev.loaded / (1024 * 1024)) * 10) / 10;
            onProgress?.({
              percent: pct,
              loadedMb,
              totalMb,
              fileName: file.name,
            });
          }
        };

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText));
            } catch {
              resolve({ uploaded: [file.name] });
            }
          } else {
            let errMsg = `HTTP ${xhr.status}`;
            try {
              const parsed = JSON.parse(xhr.responseText);
              if (parsed?.error) errMsg = parsed.error;
            } catch {
              // ignore
            }
            reject(new Error(errMsg));
          }
        };

        xhr.onerror = () => reject(new Error(`Network error while uploading ${file.name}`));
        xhr.onabort = () => reject(new Error(`Upload aborted for ${file.name}`));
        xhr.send(file);
      });

      if (res.uploaded && res.uploaded.length > 0) {
        uploaded.push(...res.uploaded);
      }
    }

    return { uploaded, instantCount };
  },

  // Geospatial Visualization Payloads
  async getRasterBounds(rasterPath: string): Promise<RasterBoundsResponse> {
    return request<RasterBoundsResponse>(
      `/api/raster/bounds?path=${encodeURIComponent(rasterPath)}`
    );
  },

  async getRasterStats(rasterPath: string, band: number = 1): Promise<RasterStatsResponse> {
    return request<RasterStatsResponse>(
      `/api/raster/stats?path=${encodeURIComponent(rasterPath)}&band=${band}`
    );
  },

  async getRasterPixel(
    rasterPath: string,
    lon: number,
    lat: number,
    band: number = 1
  ): Promise<RasterPixelResponse> {
    return request<RasterPixelResponse>(
      `/api/raster/pixel?path=${encodeURIComponent(rasterPath)}&lon=${lon}&lat=${lat}&band=${band}`
    );
  },

  async inspectFile(filePath: string): Promise<FileInspectResponse> {
    return request<FileInspectResponse>(
      `/api/file/inspect?path=${encodeURIComponent(filePath)}`
    );
  },

  getRasterPngUrl(
    rasterPath: string,
    options?: { cmap?: string; vmin?: number; vmax?: number; band?: number }
  ): string {
    const params = new URLSearchParams({ path: rasterPath });
    if (options?.cmap) params.set('cmap', options.cmap);
    if (options?.vmin !== undefined && options.vmin !== null) params.set('vmin', String(options.vmin));
    if (options?.vmax !== undefined && options.vmax !== null) params.set('vmax', String(options.vmax));
    if (options?.band) params.set('band', String(options.band));
    return `/api/raster/png?${params.toString()}`;
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

  // Unified Conversational Workspace Assistant
  async sendWorkspaceMessage(
    taskId: string,
    payload: {
      message: string;
      history?: Array<{ role: string; content: string }>;
      files?: string;
      bbox?: number[];
      bands?: string;
    }
  ): Promise<{
    type: 'conversational_reply' | 'visual_reply' | 'task_delegated' | 'workspace_busy' | 'clarification_needed';
    reply?: string;
    follow_ups?: string[];
    thumb_url?: string;
    fly_to_bbox?: [number, number, number, number] | number[];
    artifact?: string;
    task_id?: string;
    status?: string;
    current_step?: string;
    elapsed?: number;
    queued_prompt?: string;
    seq?: number;
    timestamp?: number;
    error?: string;
  }> {
    return request(`/api/workspace/${encodeURIComponent(taskId)}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  },

  async getWorkspaceConversation(taskId: string): Promise<{
    turns: Array<{
      id?: string;
      seq?: number;
      role: string;
      content: string;
      timestamp?: number;
      type?: 'conversational_reply' | 'visual_reply' | 'task_delegated' | 'clarification';
      question?: string;
      thumb_url?: string;
      fly_to_bbox?: number[];
      follow_ups?: string[];
    }>;
  }> {
    return request(`/api/workspace/${encodeURIComponent(taskId)}/conversation`);
  },

  async clearWorkspaceConversation(taskId: string): Promise<{ ok: boolean; task_id: string }> {
    return request(`/api/workspace/${encodeURIComponent(taskId)}/conversation`, {
      method: 'DELETE',
    });
  },
};


