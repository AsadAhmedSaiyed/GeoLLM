// TypeScript definitions for Microsoft Planetary Computer STAC interactions.

export interface StacCollection {
  id: string;
  title: string;
  modality?: 'optical' | 'sar' | 'hyperspectral' | 'dem' | 'landcover' | string;
  description?: string;
  recommended_assets?: string[];
  keywords?: string[];
  license?: string;
  [key: string]: unknown;
}

export interface StacAsset {
  key: string;
  href?: string;
  title?: string;
  description?: string;
  type?: string;
  roles?: string[];
  [key: string]: unknown;
}

export interface StacItem {
  id: string;
  collection: string;
  datetime?: string;
  cloud_cover?: number | null;
  aoi_coverage_pct?: number | null;
  nodata_pct?: number | null;
  thumbnail?: string | null;
  thumbnail_url?: string | null;
  bbox?: [number, number, number, number] | number[];
  assets?: StacAsset[];
  properties?: {
    datetime?: string;
    'eo:cloud_cover'?: number;
    cloud_cover?: number;
    platform?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface StacSearchParams {
  bbox: [number, number, number, number] | number[];
  start_date: string;
  end_date: string;
  collections?: string[];
  max_cloud_cover?: number;
  limit?: number;
}

export interface StacSearchResponse {
  ok: boolean;
  items: StacItem[];
  error?: string;
}

export interface StacStagePayload {
  collection: string;
  item_id: string;
  asset_key: string;
  custom_filename?: string;
}

export interface StacDownloadState {
  id?: string;
  stage_id: string;
  item_id?: string;
  collection?: string;
  asset_key?: string;
  status:
    | 'starting'
    | 'fetching_metadata'
    | 'started'
    | 'downloading'
    | 'completed'
    | 'done'
    | 'failed'
    | 'cancelled';
  percent?: number;
  progress?: number;
  downloaded_mb?: number;
  total_mb?: number;
  speed_mbps?: number;
  error?: string;
  filename?: string;
  path?: string;
}

export interface StacDownloadsResponse {
  downloads: Record<string, StacDownloadState>;
}
