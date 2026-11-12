// Strict TypeScript definitions for all GeoLLM Server-Sent Events (SSE).
// Directly derived from the Python backend (harness/orchestrator.py, pi_harness.py,
// harness/validation/*.py, and web_app.py).

export type TaskStatus =
  | 'idle'
  | 'running'
  | 'pending_approval'
  | 'pending_stac_approval'
  | 'done'
  | 'partial'
  | 'failed';

export interface BaseSSEEvent {
  id?: number;
  task_id?: string;
  type: string;
}

export interface SSEStartEvent extends BaseSSEEvent {
  type: 'start';
  task_id: string;
  question: string;
}

export interface SSEStatusEvent extends BaseSSEEvent {
  type: 'status';
  status?: TaskStatus | string;
  step?: string;
  text?: string;
}

export interface SSETurnEvent extends BaseSSEEvent {
  type: 'turn';
  state?: 'start' | 'end';
  turn?: number;
}

export interface SSETextEvent extends BaseSSEEvent {
  type: 'text';
  delta?: string;
  text?: string;
}

export interface SSEThinkingEvent extends BaseSSEEvent {
  type: 'thinking';
  delta?: string;
  text?: string;
}

export interface SSEToolStartEvent extends BaseSSEEvent {
  type: 'tool_start';
  toolCallId: string;
  toolName: string;
  args?: Record<string, unknown> | string;
  attempt?: number;
  code_attempt?: number;
  max_attempts?: number;
}

export interface SSEToolEndEvent extends BaseSSEEvent {
  type: 'tool_end';
  toolCallId: string;
  toolName?: string;
  ok: boolean;
  exit_code?: number;
  duration_s?: number;
  error?: string;
  stdout?: string;
  attempt?: number;
  code_attempt?: number;
  max_attempts?: number;
}

export interface SSEPlanReadyEvent extends BaseSSEEvent {
  type: 'plan_ready' | 'plan_proposed';
  plan: string;
}

export interface StacScenePreview {
  id?: string;
  item_id?: string;
  label?: string;
  collection: string;
  datetime?: string;
  cloud_cover?: number | null;
  aoi_coverage_pct?: number | null;
  thumbnail?: string | null;
  assets?: string[];
  [key: string]: unknown;
}

export interface StacPreviewPayload {
  scenes?: StacScenePreview[];
  location_name?: string;
  bbox?: [number, number, number, number] | number[];
  explanation?: string;
  native_grid_estimate?: {
    estimated_width_px?: number;
    estimated_height_px?: number;
    native_resolution_m?: number;
    area_km2?: number;
  };
  [key: string]: unknown;
}

export interface SSEStacPreviewReadyEvent extends BaseSSEEvent {
  type: 'stac_preview_ready' | 'stac_preview_proposed';
  preview: StacPreviewPayload;
}

export interface SSEStacDownloadStartEvent extends BaseSSEEvent {
  type: 'stac_download_start';
  filename: string;
  collection: string;
  item_id?: string;
  asset_key?: string;
  date?: string;
  band_index?: number;
  total_bands?: number;
}

export interface SSEStacDownloadProgressEvent extends BaseSSEEvent {
  type: 'stac_download_progress';
  filename: string;
  collection?: string;
  item_id?: string;
  asset_key?: string;
  date?: string;
  band_index?: number;
  total_bands?: number;
  band_pct: number;
  overall_pct: number;
  elapsed_s?: number;
}

export interface SSEStacDownloadDoneEvent extends BaseSSEEvent {
  type: 'stac_download_done';
  filename: string;
  collection?: string;
  asset_key?: string;
  date?: string;
  band_index?: number;
  total_bands?: number;
  ok: boolean;
  cached?: boolean;
  path?: string;
  size_mb?: number | null;
  width?: number | null;
  height?: number | null;
  resolution?: number | null;
  duration_s?: number;
  error?: string;
}

export interface SSEStacStagedEvent extends BaseSSEEvent {
  type: 'stac_staged';
  files: string[];
}

export interface VisionFileSummary {
  name: string;
  nodata_pct: number;
  cloud_pct: number;
  crs?: string;
  resolution_m?: [number, number] | number[];
  width?: number;
  height?: number;
  is_usable: boolean;
  issues?: string[];
}

export interface SSEVisionInputGateEvent extends BaseSSEEvent {
  type: 'vision_input_gate';
  state?: 'started' | 'done' | string;
  verdict?: 'pass' | 'insufficient_data' | string;
  reason?: string;
  area_verified_pct?: number;
  raster_count?: number;
  raster_paths?: string[];
  files?: VisionFileSummary[];
}

export interface SSEVisionInsufficientDataEvent extends BaseSSEEvent {
  type: 'vision_insufficient_data';
  reason?: string;
  area_verified_pct?: number;
  raster_count?: number;
  files?: VisionFileSummary[];
  image?: string;
  tile_id?: string;
  missing_data_fraction?: number;
  steps_used?: number;
  budget?: number;
}

export interface SSEVisionCheckEvent extends BaseSSEEvent {
  type: 'vision_check';
  image: string;
  index?: number;
  total?: number;
  state: 'started' | 'done';
  verdict?: 'ok' | 'needs_revision' | 'skipped' | 'insufficient_data' | string;
  text?: string;
  mode?: string;
}

export interface VisionTileRecord {
  tile_id: string;
  row?: number;
  col?: number;
  bbox_norm?: [number, number, number, number] | number[];
  verdict?: string | null;
  [key: string]: unknown;
}

export interface SSEVisionGridEvent extends BaseSSEEvent {
  type: 'vision_grid';
  image: string;
  rows: number;
  cols: number;
  tiles: VisionTileRecord[];
  steps_used: number;
  budget: number;
}

export interface SSEVisionInspectingTileEvent extends BaseSSEEvent {
  type: 'vision_inspecting_tile';
  image: string;
  tile_id: string;
  bbox_norm?: number[];
  zoom_level?: number;
  thumb_url?: string;
  step_number?: number;
  max_steps?: number;
}

export interface SSEVisionTileVerdictEvent extends BaseSSEEvent {
  type: 'vision_tile_verdict';
  image: string;
  tile_id: string;
  verdict: 'ok' | 'wrong' | 'unclear' | string;
  color?: string;
  bbox_norm?: number[];
  defect_category?: string;
  rationale?: string;
  confidence?: number;
  thumb_url?: string;
  crop_url?: string;
  verified_area_pct?: number;
}

export interface SSEVisionProgressEvent extends BaseSSEEvent {
  type: 'vision_progress';
  image?: string;
  index?: number;
  total?: number;
  steps_used: number;
  budget: number;
  tiles_checked?: number;
  tiles_marked?: number;
}

export interface FlaggedRegion {
  tile_id: string;
  rationale?: string;
  verdict?: string;
  severity?: string;
  defect_category?: string;
}

export interface SSEVisionSummaryEvent extends BaseSSEEvent {
  type: 'vision_summary';
  image?: string;
  final_verdict: 'valid' | 'not_valid' | 'insufficient_data' | string;
  verified_area_pct: number;
  tiles_checked?: number;
  defects_count?: number;
  flagged_regions?: FlaggedRegion[];
  summary?: string;
  checklist_results?: Record<string, boolean>;
}

export interface SSEVisionStoppedEvent extends BaseSSEEvent {
  type: 'vision_stopped';
  image?: string;
  reason: string;
  detail?: string;
}

export interface SSEVisionFeedbackEvent extends BaseSSEEvent {
  type: 'vision_feedback';
  file: string;
  tile_id?: string;
  bbox_norm?: number[];
  bbox_geo?: number[];
  severity?: string;
  category?: string;
  suggested_fix?: string;
}

export interface SSEVisionConsensusDoneEvent extends BaseSSEEvent {
  type: 'vision_consensus_done';
  image?: string;
  re_verified?: number;
  tiles?: Record<string, string>;
}

export interface ArtifactItem {
  name: string;
  path?: string;
  size_mb?: number;
  url?: string;
  [key: string]: unknown;
}

export interface SSEArtifactsEvent extends BaseSSEEvent {
  type: 'artifacts';
  artifacts: Array<string | ArtifactItem>;
}

export interface SSEFinishEvent extends BaseSSEEvent {
  type: 'finish';
  task_id: string;
  status: 'done' | 'failed' | 'partial' | string;
  ok?: boolean;
  error?: string | null;
}

export type GeoLLMSSEEvent =
  | SSEStartEvent
  | SSEStatusEvent
  | SSETurnEvent
  | SSETextEvent
  | SSEThinkingEvent
  | SSEToolStartEvent
  | SSEToolEndEvent
  | SSEPlanReadyEvent
  | SSEStacPreviewReadyEvent
  | SSEStacDownloadStartEvent
  | SSEStacDownloadProgressEvent
  | SSEStacDownloadDoneEvent
  | SSEStacStagedEvent
  | SSEVisionInputGateEvent
  | SSEVisionInsufficientDataEvent
  | SSEVisionCheckEvent
  | SSEVisionGridEvent
  | SSEVisionInspectingTileEvent
  | SSEVisionTileVerdictEvent
  | SSEVisionProgressEvent
  | SSEVisionSummaryEvent
  | SSEVisionStoppedEvent
  | SSEVisionFeedbackEvent
  | SSEVisionConsensusDoneEvent
  | SSEArtifactsEvent
  | SSEFinishEvent;

