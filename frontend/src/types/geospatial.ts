// TypeScript definitions for GeoLLM geospatial analysis & raster data models.

export interface FileInfo {
  name: string;
  size_bytes?: number;
  size_mb: number;
  modified: string;
}

export interface RasterBoundsResponse {
  ok: boolean;
  bbox?: [number, number, number, number]; // [min_lon, min_lat, max_lon, max_lat]
  coordinates?: [
    [number, number], // top-left
    [number, number], // top-right
    [number, number], // bottom-right
    [number, number]  // bottom-left
  ];
  crs?: string;
  width?: number;
  height?: number;
  count?: number;
  path?: string;
  png_url?: string;
  error?: string;
}

export interface TimelineFrame {
  index?: number;
  file?: string;
  date?: string | null;
  value?: number | null;
  label?: string;
  png_url?: string;
  gif_url?: string;
  [key: string]: unknown;
}

export interface TimelinePayload {
  dates?: string[];
  series_values?: number[];
  frames: TimelineFrame[];
  gif_url?: string;
  metric_name?: string;
  title?: string;
  unit?: string;
  [key: string]: unknown;
}

export interface Terrain3DPayload {
  elevations: number[];
  hillshade?: number[];
  width: number;
  height: number;
  orthophoto_url?: string;
  min_elevation_m: number;
  max_elevation_m: number;
  elevation_range_m: number;
  is_lidar?: boolean;
  source?: string;
  default_surface?: string;
  cell_size_m?: [number, number];
  crs?: string;
  [key: string]: unknown;
}

export interface SupervisorChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: number;
}

export interface SupervisorChatResponse {
  reply: string;
  is_run_job: boolean;
  proposed_job?: string;
  error?: string;
}

export interface RasterClassItem {
  value: number;
  label: string;
  color: string;
}

export interface RasterNumericStats {
  min: number;
  max: number;
  mean: number;
  median: number;
  p02: number;
  p98: number;
}

export interface RasterStatsResponse {
  ok: boolean;
  file_name?: string;
  path?: string;
  band?: number;
  band_count?: number;
  band_description?: string;
  artifact_description?: string;
  units?: string;
  crs?: string;
  width?: number;
  height?: number;
  is_classified?: boolean;
  classes?: RasterClassItem[];
  recommended_cmap?: string;
  stats?: RasterNumericStats;
  error?: string;
}

export interface RasterPixelResponse {
  ok: boolean;
  inside: boolean;
  value?: number | null;
  is_nodata?: boolean;
  row?: number;
  col?: number;
  units?: string;
  band?: number;
  error?: string;
}

export interface FileInspectResponse {
  ok: boolean;
  filename?: string;
  path?: string;
  size_mb?: number;
  extension?: string;
  category?: 'raster' | 'lidar' | 'vector' | 'image' | 'other';
  crs?: string;
  width?: number;
  height?: number;
  count?: number;
  dtypes?: string[];
  nodata?: number | null;
  bounds_wgs84?: [number, number, number, number] | null;
  png_url?: string;
  point_count?: number;
  version?: string;
  feature_count?: number;
  geometry_types?: string[];
  format?: string;
  mode?: string;
  error?: string;
}

