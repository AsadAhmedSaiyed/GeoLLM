import React, { useState, useEffect, useRef } from 'react';
import { api } from '@/services/api';
import {
  StacCollection,
  StacItem,
  StacDownloadState,
} from '@/types/stac';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Satellite,
  X,
  Search,
  Download,
  Zap,
  Globe,
  Radio,
  Sparkles,
  Mountain,
  Trees,
  Check,
  Loader2,
} from 'lucide-react';

export interface StacAssetStagedInfo {
  ok: boolean;
  filename?: string;
  path?: string;
  size_mb?: number;
  collection?: string;
  item_id?: string;
  asset_key?: string;
}

export interface StacModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialBbox?: number[] | null;
  onAssetStaged?: (info: StacAssetStagedInfo) => void;
  onNotify?: (message: string, type?: 'info' | 'warning' | 'error' | 'success') => void;
}

export const StacModal: React.FC<StacModalProps> = ({
  isOpen,
  onClose,
  initialBbox,
  onAssetStaged,
  onNotify,
}) => {
  const [collections, setCollections] = useState<StacCollection[]>([]);
  const [selectedCollections, setSelectedCollections] = useState<string[]>([
    'sentinel-2-l2a',
    'sentinel-1-rtc',
  ]);
  const [selectedModality, setSelectedModality] = useState<string>('all');

  const [startDate, setStartDate] = useState('2024-04-10');
  const [endDate, setEndDate] = useState('2024-05-20');
  const [maxCloud, setMaxCloud] = useState<number>(25);
  const [bboxInput, setBboxInput] = useState<string>(
    initialBbox ? initialBbox.join(', ') : '55.15, 25.05, 55.45, 25.35'
  );

  const [loading, setLoading] = useState(false);
  const [searchResults, setSearchResults] = useState<StacItem[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [stagingKeys, setStagingKeys] = useState<Record<string, boolean>>({});
  const stagedKeysRef = useRef<Record<string, boolean>>({});
  const searchAbortRef = useRef<AbortController | null>(null);
  const [activeDownloads, setActiveDownloads] = useState<
    Record<string, StacDownloadState>
  >({});

  // Poll real-time download progress from backend every 500ms while modal is open
  useEffect(() => {
    if (!isOpen) return;
    const fetchProgress = async () => {
      try {
        const data = await api.getStacDownloads();
        if (data.downloads) {
          setActiveDownloads(data.downloads);
          Object.values(data.downloads).forEach((dl) => {
            if (dl.status === 'completed' && !stagedKeysRef.current[dl.stage_id]) {
              stagedKeysRef.current[dl.stage_id] = true;
              onAssetStaged?.({
                ok: true,
                filename: dl.filename,
                path: dl.path,
                size_mb: dl.downloaded_mb,
                collection: dl.collection,
                item_id: dl.item_id,
                asset_key: dl.asset_key,
              });
            }
          });
        }
      } catch {
        // ignore transient error
      }
    };

    fetchProgress();
    const timer = setInterval(fetchProgress, 500);
    return () => clearInterval(timer);
  }, [isOpen, onAssetStaged]);

  // Load collections dynamically from backend
  useEffect(() => {
    api
      .getStacCollections()
      .then((colls) => {
        if (colls) setCollections(colls);
      })
      .catch((e) => console.warn('Could not load STAC collections:', e));
  }, []);

  // Update BBOX if initialBbox changes from globe
  useEffect(() => {
    if (initialBbox && initialBbox.length === 4) {
      setBboxInput(initialBbox.map((n) => Number(n).toFixed(4)).join(', '));
    }
  }, [initialBbox]);

  if (!isOpen) return null;

  const toIsoDate = (val: string, fallback: string): string => {
    if (!val) return fallback;
    const s = String(val).trim();
    const isoMatch = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
    if (isoMatch) {
      const y = isoMatch[1];
      const m = isoMatch[2].padStart(2, '0');
      const d = isoMatch[3].padStart(2, '0');
      return `${y}-${m}-${d}`;
    }
    const dmyMatch = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})/);
    if (dmyMatch) {
      const p1 = parseInt(dmyMatch[1], 10);
      const p2 = parseInt(dmyMatch[2], 10);
      const y = dmyMatch[3];
      let d = p1;
      let m = p2;
      if (p1 > 12 && p2 <= 12) {
        d = p1;
        m = p2;
      } else if (p2 > 12 && p1 <= 12) {
        d = p2;
        m = p1;
      }
      return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    }
    return s.slice(0, 10);
  };

  const handleSearch = async () => {
    setErrorMsg(null);
    setLoading(true);
    setSearchResults([]);

    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
    }
    const controller = new AbortController();
    searchAbortRef.current = controller;

    try {
      const raw = bboxInput.split(',').map((s) => parseFloat(s.trim()));
      if (raw.length !== 4 || raw.some(isNaN)) {
        throw new Error(
          'Bounding box must contain 4 numbers: min_lon, min_lat, max_lon, max_lat'
        );
      }
      const minX = Math.min(raw[0], raw[2]);
      const maxX = Math.max(raw[0], raw[2]);
      const minY = Math.min(raw[1], raw[3]);
      const maxY = Math.max(raw[1], raw[3]);
      const parsedBbox: [number, number, number, number] = [minX, minY, maxX, maxY];

      let sDate = toIsoDate(startDate, '2024-04-10');
      let eDate = toIsoDate(endDate, '2024-05-20');
      if (sDate && eDate && sDate > eDate) {
        const tmp = sDate;
        sDate = eDate;
        eDate = tmp;
      }
      setStartDate(sDate);
      setEndDate(eDate);

      const resp = await fetch('/api/stac/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          bbox: parsedBbox,
          start_date: sDate,
          end_date: eDate,
          collections: selectedCollections,
          max_cloud_cover: maxCloud,
          limit: 12,
        }),
      });

      const data = await resp.json();
      if (!data.ok) {
        throw new Error(data.error || 'STAC search failed');
      }

      setSearchResults(data.items || []);
      if ((data.items || []).length === 0) {
        setErrorMsg(
          'No satellite scenes found matching this AOI, date range, and cloud threshold.'
        );
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setErrorMsg('Search request cancelled.');
      } else {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
      searchAbortRef.current = null;
    }
  };

  const handleCancelSearch = () => {
    if (searchAbortRef.current) {
      searchAbortRef.current.abort();
      searchAbortRef.current = null;
    }
    setLoading(false);
  };

  const handleStageAsset = async (item: StacItem, assetKey: string) => {
    const stageId = `${item.id}_${assetKey}`;
    setStagingKeys((prev) => ({ ...prev, [stageId]: true }));
    try {
      const data = await api.stageStacAsset({
        collection: item.collection,
        item_id: item.id,
        asset_key: assetKey,
      });
      if (!data.ok) {
        throw new Error('Failed to start download');
      }
    } catch (err) {
      onNotify?.(
        `Asset ${assetKey} download start failed: ${
          err instanceof Error ? err.message : String(err)
        }`,
        'error'
      );
      setStagingKeys((prev) => {
        const next = { ...prev };
        delete next[stageId];
        return next;
      });
    }
  };

  const handleCancelDownload = async (stageId: string) => {
    try {
      await api.cancelStacDownload(stageId);
      setStagingKeys((prev) => {
        const next = { ...prev };
        delete next[stageId];
        return next;
      });
    } catch (err) {
      console.error('Failed to cancel download:', err);
    }
  };

  const handleCancelAllDownloads = async () => {
    const active = Object.values(activeDownloads).filter(
      (d) =>
        d.status === 'downloading' ||
        d.status === 'starting' ||
        d.status === 'fetching_metadata'
    );
    await Promise.all(active.map((d) => handleCancelDownload(d.stage_id)));
  };

  const handleCancelItemDownloads = async (item: StacItem) => {
    const activeItemDls = Object.values(activeDownloads).filter(
      (d) =>
        d.item_id === item.id &&
        (d.status === 'downloading' ||
          d.status === 'starting' ||
          d.status === 'fetching_metadata')
    );
    await Promise.all(activeItemDls.map((d) => handleCancelDownload(d.stage_id)));
  };

  const handleDownloadAllCore = async (item: StacItem) => {
    let coreBands: string[] = [];
    if (
      item.collection.includes('sentinel-2') ||
      item.collection.includes('landsat')
    ) {
      coreBands = ['B02', 'B03', 'B04', 'B08', 'blue', 'green', 'red', 'nir08'];
    } else if (item.collection.includes('sentinel-1')) {
      coreBands = ['vv', 'vh'];
    } else if (item.collection.includes('emit')) {
      coreBands = ['reflectance'];
    } else if (
      item.collection.includes('dem') ||
      item.collection.includes('worldcover')
    ) {
      coreBands = ['data', 'map'];
    }

    const targets = (item.assets || []).filter((a) => coreBands.includes(a.key));
    if (targets.length === 0) {
      onNotify?.('No matching core assets found to batch download.', 'warning');
      return;
    }

    await Promise.all(targets.map((a) => handleStageAsset(item, a.key)));
  };

  const filteredCollections =
    selectedModality === 'all'
      ? collections
      : collections.filter((c) => c.modality === selectedModality);

  const modalities = [
    { key: 'all', label: 'All Sensors', icon: Globe },
    { key: 'optical', label: 'Optical', icon: Satellite },
    { key: 'sar', label: 'Radar (SAR)', icon: Radio },
    { key: 'hyperspectral', label: 'Hyperspectral (EMIT)', icon: Sparkles },
    { key: 'dem', label: 'Elevation (DEM)', icon: Mountain },
    { key: 'landcover', label: 'Land Cover', icon: Trees },
  ];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#0B0F17] border border-[#1E293B] rounded-xl w-full max-w-4xl max-h-[88vh] flex flex-col shadow-2xl overflow-hidden text-slate-100"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-[#1E293B] bg-[#0F172A] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Satellite className="h-5 w-5 text-sky-400 shrink-0" />
            <div>
              <div className="font-bold text-sm text-slate-100">
                Microsoft Planetary Computer Satellite Data
              </div>
              <div className="text-[11px] text-slate-400">
                Search & retrieve Optical, SAR, Hyperspectral, and DEM assets for your Area of Interest
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-[#1E293B] cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          {/* Controls Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 bg-[#111827] border border-[#1E293B] rounded-lg p-4">
            {/* Modality Pills */}
            <div className="md:col-span-2">
              <label className="block text-[11px] font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                Sensor Modality
              </label>
              <div className="flex flex-wrap gap-1.5">
                {modalities.map(({ key, label, icon: Icon }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setSelectedModality(key);
                      const matching = collections
                        .filter((c) => key === 'all' || c.modality === key)
                        .map((c) => c.id);
                      setSelectedCollections(matching.slice(0, 2));
                    }}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors cursor-pointer ${
                      selectedModality === key
                        ? 'bg-sky-500/20 border-sky-500/50 text-sky-300'
                        : 'bg-[#0B0F17] border-[#1E293B] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Target Collections Checkboxes */}
            <div className="md:col-span-2">
              <label className="block text-[11px] font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
                Target Collections
              </label>
              <div className="flex flex-wrap gap-1.5">
                {filteredCollections.map((c) => {
                  const isChecked = selectedCollections.includes(c.id);
                  return (
                    <label
                      key={c.id}
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs cursor-pointer transition-colors ${
                        isChecked
                          ? 'bg-[#0F766E]/25 border-[#14B8A6]/50 text-[#2DD4BF]'
                          : 'bg-[#0B0F17] border-[#1E293B] text-slate-300 hover:border-slate-700'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => {
                          if (isChecked) {
                            setSelectedCollections(
                              selectedCollections.filter((id) => id !== c.id)
                            );
                          } else {
                            setSelectedCollections([...selectedCollections, c.id]);
                          }
                        }}
                        className="rounded border-[#1E293B] bg-[#111827]"
                      />
                      <span>{c.title}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            {/* AOI BBOX */}
            <div className="md:col-span-2">
              <label className="block text-[11px] font-semibold text-slate-300 mb-1 uppercase tracking-wider">
                Area of Interest (BBOX: West, South, East, North)
              </label>
              <Input
                type="text"
                value={bboxInput}
                onChange={(e) => setBboxInput(e.target.value)}
                placeholder="min_lon, min_lat, max_lon, max_lat"
                className="h-8 text-xs"
              />
            </div>

            {/* Start & End Date */}
            <div>
              <label className="block text-[11px] font-semibold text-slate-300 mb-1 uppercase tracking-wider">
                Start Date
              </label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="h-8 text-xs"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-slate-300 mb-1 uppercase tracking-wider">
                End Date
              </label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="h-8 text-xs"
              />
            </div>

            {/* Cloud Cover Slider */}
            <div className="md:col-span-2">
              <div className="flex justify-between mb-1">
                <label className="text-[11px] font-semibold text-slate-300 uppercase tracking-wider">
                  Max Cloud Cover
                </label>
                <span className="font-mono text-[11px] text-sky-400">
                  {maxCloud}%
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={maxCloud}
                onChange={(e) => setMaxCloud(Number(e.target.value))}
                className="w-full accent-[#14B8A6] cursor-pointer"
              />
            </div>
          </div>

          {/* Search Button Row */}
          <div className="flex items-center justify-end gap-2">
            {loading && (
              <Button
                type="button"
                size="sm"
                variant="destructive"
                onClick={handleCancelSearch}
                className="h-8 text-xs gap-1"
              >
                <X className="h-3.5 w-3.5" />
                <span>Cancel Search</span>
              </Button>
            )}
            <Button
              type="button"
              variant="teal"
              size="sm"
              onClick={handleSearch}
              disabled={loading || selectedCollections.length === 0}
              className="h-8 px-4 text-xs font-semibold gap-1.5"
            >
              {loading ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Searching STAC Catalog…</span>
                </>
              ) : (
                <>
                  <Search className="h-3.5 w-3.5" />
                  <span>Search Matching Satellite Scenes</span>
                </>
              )}
            </Button>
          </div>

          {/* Error Alert */}
          {errorMsg && (
            <div className="p-3 rounded-md bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs">
              {errorMsg}
            </div>
          )}

          {/* Active Downloads Progress Panel */}
          {Object.keys(activeDownloads).length > 0 && (
            <div className="bg-[#111827] border border-[#1E293B] rounded-lg p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-semibold text-slate-200">
                  <Download className="h-4 w-4 text-sky-400" />
                  <span>Satellite Downloads</span>
                  <span className="text-[11px] text-slate-400 font-normal font-mono">
                    (
                    {
                      Object.values(activeDownloads).filter(
                        (d) =>
                          d.status === 'downloading' ||
                          d.status === 'starting' ||
                          d.status === 'fetching_metadata'
                      ).length
                    }{' '}
                    in progress)
                  </span>
                </div>
                {Object.values(activeDownloads).some(
                  (d) =>
                    d.status === 'downloading' ||
                    d.status === 'starting' ||
                    d.status === 'fetching_metadata'
                ) && (
                  <button
                    type="button"
                    onClick={handleCancelAllDownloads}
                    className="text-[10.5px] px-2 py-0.5 rounded bg-rose-500/20 border border-rose-500/40 text-rose-300 hover:bg-rose-500/30 cursor-pointer"
                  >
                    ✕ Cancel All
                  </button>
                )}
              </div>

              <div className="space-y-2">
                {Object.values(activeDownloads).map((dl) => {
                  const isDone = dl.status === 'completed';
                  const isFail = dl.status === 'failed';
                  const isCancelled = dl.status === 'cancelled';
                  const pct = isDone ? 100 : dl.percent || 0;

                  return (
                    <div
                      key={dl.stage_id}
                      className="bg-[#0B0F17] border border-[#1E293B] rounded p-2"
                    >
                      <div className="flex items-center justify-between text-[11px] mb-1">
                        <span
                          className="font-mono font-medium text-slate-200 truncate"
                          title={dl.filename}
                        >
                          {isDone
                            ? '✓ '
                            : isFail
                            ? '✗ '
                            : isCancelled
                            ? '⊘ '
                            : '⏳ '}
                          {dl.filename}
                        </span>
                        <div className="flex items-center gap-2 font-mono text-[10.5px] text-slate-400 shrink-0">
                          {isDone ? (
                            <span className="text-emerald-400 font-semibold">
                              Staged ({dl.total_mb || dl.downloaded_mb} MB)
                            </span>
                          ) : isCancelled ? (
                            <span className="text-amber-400 font-semibold">
                              Cancelled
                            </span>
                          ) : isFail ? (
                            <span className="text-rose-400">
                              Failed: {dl.error || 'Network error'}
                            </span>
                          ) : (
                            <>
                              <span>
                                {dl.downloaded_mb || 0} /{' '}
                                {dl.total_mb ? `${dl.total_mb} MB` : 'calc…'} (
                                {Math.round(pct)}%)
                              </span>
                              {dl.speed_mbps && (
                                <span className="text-slate-500">
                                  • {dl.speed_mbps} MB/s
                                </span>
                              )}
                              <button
                                type="button"
                                onClick={() => handleCancelDownload(dl.stage_id)}
                                className="text-rose-400 hover:text-rose-300 cursor-pointer"
                              >
                                ✕ Cancel
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                      <div className="w-full h-1.5 bg-[#1E293B] rounded overflow-hidden">
                        <div
                          className={`h-full transition-all ${
                            isDone
                              ? 'bg-emerald-500'
                              : isFail
                              ? 'bg-rose-500'
                              : isCancelled
                              ? 'bg-amber-500'
                              : 'bg-sky-500'
                          }`}
                          style={{ width: `${Math.max(pct, isDone ? 100 : 4)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Search Results Gallery */}
          {searchResults.length > 0 && (
            <div className="space-y-3">
              <div className="text-xs text-slate-300">
                Found <strong>{searchResults.length}</strong> matching satellite scene(s)
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {searchResults.map((item) => {
                  const dt = (item.datetime || '').slice(0, 10);
                  const cloud =
                    item.cloud_cover != null
                      ? `${Math.round(item.cloud_cover)}% clouds`
                      : null;

                  return (
                    <div
                      key={item.id}
                      className="bg-[#111827] border border-[#1E293B] rounded-lg overflow-hidden flex flex-col"
                    >
                      <div className="h-36 bg-[#070A0F] flex items-center justify-center overflow-hidden border-b border-[#1E293B]">
                        {item.thumbnail ? (
                          <img
                            src={item.thumbnail}
                            alt={item.id}
                            loading="lazy"
                            className="max-h-36 max-w-full object-contain"
                          />
                        ) : (
                          <div className="text-slate-500 font-mono text-xs flex items-center gap-1.5">
                            <Satellite className="h-4 w-4" />
                            <span>Scene Preview Unavailable</span>
                          </div>
                        )}
                      </div>

                      <div className="p-3 flex-1 flex flex-col justify-between space-y-2.5">
                        <div>
                          <div
                            className="font-mono font-bold text-[11px] text-slate-100 truncate mb-1.5"
                            title={item.id}
                          >
                            {item.id}
                          </div>
                          <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                            <span className="bg-[#1E293B] text-slate-300 px-1.5 py-0.5 rounded">
                              {dt}
                            </span>
                            <span className="bg-sky-500/15 text-sky-400 border border-sky-500/30 px-1.5 py-0.5 rounded">
                              {item.collection}
                            </span>
                            {cloud && (
                              <span className="bg-[#1E293B] text-slate-300 px-1.5 py-0.5 rounded">
                                {cloud}
                              </span>
                            )}
                            {item.aoi_coverage_pct != null && (
                              <span
                                className={`px-1.5 py-0.5 rounded font-semibold ${
                                  item.aoi_coverage_pct >= 90
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                    : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                                }`}
                              >
                                {item.aoi_coverage_pct >= 95
                                  ? '🎯 100% AOI Cover'
                                  : `📍 ${item.aoi_coverage_pct}% AOI`}
                              </span>
                            )}
                            {item.nodata_pct != null && (
                              <span className="bg-[#1E293B] text-slate-400 px-1.5 py-0.5 rounded">
                                {item.nodata_pct}% nodata
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Assets Drawer */}
                        <div className="border-t border-[#1E293B] pt-2">
                          <div className="flex items-center justify-between mb-1.5 gap-1 flex-wrap">
                            <span className="text-[10.5px] text-slate-400 font-semibold">
                              Available Bands:
                            </span>
                            <div className="flex items-center gap-1">
                              <button
                                type="button"
                                onClick={() => handleDownloadAllCore(item)}
                                className="flex items-center gap-1 bg-[#0F766E] hover:bg-[#14B8A6] text-white text-[10px] font-semibold px-2 py-0.5 rounded cursor-pointer transition-colors"
                                title="Download essential bands together"
                              >
                                <Zap className="h-3 w-3" />
                                <span>
                                  Core ({item.collection.includes('sentinel-1') ? 'VV+VH' : 'RGB+NIR'})
                                </span>
                              </button>
                              {Object.values(activeDownloads).some(
                                (d) =>
                                  d.item_id === item.id &&
                                  (d.status === 'downloading' ||
                                    d.status === 'starting' ||
                                    d.status === 'fetching_metadata')
                              ) && (
                                <button
                                  type="button"
                                  onClick={() => handleCancelItemDownloads(item)}
                                  className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 cursor-pointer"
                                >
                                  ✕ Cancel
                                </button>
                              )}
                            </div>
                          </div>

                          <div className="flex flex-wrap gap-1">
                            {(item.assets || []).map((a) => {
                              const stageId = `${item.id}_${a.key}`;
                              const dlInfo = activeDownloads[stageId];
                              const isCancelled = dlInfo && dlInfo.status === 'cancelled';
                              const isDownloading =
                                !isCancelled &&
                                ((dlInfo &&
                                  (dlInfo.status === 'downloading' ||
                                    dlInfo.status === 'starting' ||
                                    dlInfo.status === 'fetching_metadata')) ||
                                  !!stagingKeys[stageId]);
                              const isStaged =
                                (dlInfo && dlInfo.status === 'completed') ||
                                !!stagedKeysRef.current[stageId];
                              const pctText =
                                dlInfo && dlInfo.percent != null && dlInfo.percent > 0
                                  ? `${Math.round(dlInfo.percent)}%`
                                  : 'Staging…';

                              return (
                                <button
                                  key={a.key}
                                  type="button"
                                  onClick={() => {
                                    if (isDownloading) {
                                      handleCancelDownload(stageId);
                                    } else {
                                      handleStageAsset(item, a.key);
                                    }
                                  }}
                                  title={
                                    isDownloading
                                      ? 'Click to cancel download'
                                      : a.description || a.title || a.key
                                  }
                                  className={`font-mono text-[10px] px-2 py-0.5 rounded border cursor-pointer transition-colors flex items-center gap-1 ${
                                    isStaged
                                      ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                                      : isDownloading
                                      ? 'bg-sky-500/20 border-sky-500/50 text-sky-300'
                                      : 'bg-[#0B0F17] border-[#1E293B] text-slate-300 hover:border-sky-500/50'
                                  }`}
                                >
                                  {isDownloading ? (
                                    <span>
                                      ⏳ {pctText}{' '}
                                      <span className="text-rose-400 font-bold ml-0.5">✕</span>
                                    </span>
                                  ) : isStaged ? (
                                    <>
                                      <Check className="h-2.5 w-2.5" />
                                      <span>{a.key}</span>
                                    </>
                                  ) : (
                                    <span>⬇ {a.key}</span>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

