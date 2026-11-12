import React from 'react';
import { ActivityItem } from '@/types/task';
import {
  SSEVisionInputGateEvent,
  SSEVisionGridEvent,
  SSEVisionInspectingTileEvent,
  SSEVisionTileVerdictEvent,
  SSEVisionProgressEvent,
  SSEVisionStoppedEvent,
  SSEVisionSummaryEvent,
  SSEVisionFeedbackEvent,
  SSEVisionConsensusDoneEvent,
  SSEVisionInsufficientDataEvent,
  VisionFileSummary,
} from '@/types/sse';
import {
  ShieldCheck,
  ShieldAlert,
  Grid,
  Search,
  Scale,
  OctagonAlert,
  BarChart3,
  CheckCircle2,
  XCircle,
  Flag,
  Handshake,
  AlertTriangle,
} from 'lucide-react';

interface ValidationViewerProps {
  activity: ActivityItem;
}

const cleanName = (p?: string | null): string => {
  if (!p) return '';
  return p.split(/[\\/]/).pop() || p;
};

interface GroupedGateScene {
  key: string;
  label: string;
  bands: string[];
  maxNodata: number;
  maxCloud: number;
  allUsable: boolean;
  count: number;
}

const groupGateFiles = (files: VisionFileSummary[]): GroupedGateScene[] => {
  const groups = new Map<string, GroupedGateScene>();
  for (const f of files) {
    const base = cleanName(f.name);
    const match = base.match(/^(.+?_(\d{4}-\d{2}-\d{2}))_([^.]+)\.[^.]+$/);
    const key = match ? match[1] : base;
    const band = match ? match[3] : '';
    const existing = groups.get(key);
    if (existing) {
      if (band) existing.bands.push(band);
      existing.maxNodata = Math.max(existing.maxNodata, Number(f.nodata_pct ?? 0));
      existing.maxCloud = Math.max(existing.maxCloud, Number(f.cloud_pct ?? 0));
      existing.allUsable = existing.allUsable && Boolean(f.is_usable);
      existing.count += 1;
    } else {
      groups.set(key, {
        key,
        label: match ? match[1] : base,
        bands: band ? [band] : [],
        maxNodata: Number(f.nodata_pct ?? 0),
        maxCloud: Number(f.cloud_pct ?? 0),
        allUsable: Boolean(f.is_usable),
        count: 1,
      });
    }
  }
  return Array.from(groups.values());
};

export const ValidationViewer: React.FC<ValidationViewerProps> = ({ activity }) => {
  if (!activity) return null;
  const { type } = activity;

  // 1. Input Quality Gate
  if (type === 'vision_input_gate') {
    const ev = activity as SSEVisionInputGateEvent;
    const isDone = ev.state === 'done';
    const isBad = ev.verdict === 'insufficient_data';
    const borderColor = isBad ? '#EF4444' : isDone ? '#10B981' : '#38BDF8';
    const badgeColor = isBad ? '#FCA5A5' : isDone ? '#34D399' : '#38BDF8';
    const badgeBg = isBad
      ? 'rgba(239, 68, 68, 0.15)'
      : isDone
      ? 'rgba(16, 185, 129, 0.15)'
      : 'rgba(56, 189, 248, 0.15)';

    const files = ev.files || [];
    const passedCount = files.filter((f) => f.is_usable).length;
    const failedFiles = files.filter((f) => !f.is_usable);
    const maxCloud = files.length > 0 ? Math.max(...files.map((f) => Number(f.cloud_pct ?? 0))) : null;
    const maxNodata = files.length > 0 ? Math.max(...files.map((f) => Number(f.nodata_pct ?? 0))) : null;
    const groupedScenes = files.length > 0 ? groupGateFiles(files) : [];

    return (
      <div
        className="rounded-none bg-card p-3 text-foreground"
        style={{
          border: `1px solid ${borderColor}`,
          borderLeft: `4px solid ${borderColor}`,
        }}
      >
        <div className="flex items-center gap-2 text-xs font-bold mb-1">
          {isBad ? (
            <ShieldAlert className="h-4 w-4 text-rose-400 shrink-0" />
          ) : (
            <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0" />
          )}
          <span>Input Quality Gate</span>
          {ev.raster_count != null && (
            <span className="font-mono text-[10.5px] text-muted-foreground font-medium">
              ({ev.raster_count} raster{ev.raster_count === 1 ? '' : 's'})
            </span>
          )}
          <span
            className="ml-auto font-mono text-[10px] px-2 py-0.5 rounded-none font-bold uppercase"
            style={{ background: badgeBg, color: badgeColor }}
          >
            {ev.verdict || (ev.state === 'started' ? 'Checking inputs…' : 'Checking…')}
          </span>
        </div>

        {/* Compact 1-Line Summary */}
        {(ev.area_verified_pct != null || files.length > 0) && (
          <div className="font-mono text-[10.5px] text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5">
            {files.length > 0 && (
              <span>
                <strong className={failedFiles.length > 0 ? 'text-rose-400' : 'text-emerald-400'}>
                  {passedCount}/{files.length}
                </strong>{' '}
                passed
              </span>
            )}
            {ev.area_verified_pct != null && (
              <span>
                Coverage: <strong className="text-foreground">{ev.area_verified_pct}%</strong>
              </span>
            )}
            {maxCloud != null && (
              <span>
                Max Cloud: <strong className="text-foreground">{maxCloud}%</strong>
              </span>
            )}
            {maxNodata != null && (
              <span>
                Max Nodata: <strong className="text-foreground">{maxNodata}%</strong>
              </span>
            )}
          </div>
        )}

        {/* Immediately surface ONLY failed files if any exist */}
        {failedFiles.length > 0 && (
          <div className="mt-2 space-y-1">
            {failedFiles.map((f) => (
              <div
                key={f.name}
                className="text-[11px] text-foreground border border-rose-500/40 bg-rose-500/10 px-2 py-1.5"
              >
                <div className="flex justify-between items-center">
                  <span className="font-mono font-semibold text-foreground truncate">
                    {cleanName(f.name)}
                  </span>
                  <span className="font-mono font-bold text-[10.5px] text-rose-400">FAIL</span>
                </div>
                <div className="grid grid-cols-2 gap-2 mt-0.5 text-muted-foreground font-mono text-[10.5px]">
                  <span>Nodata: {f.nodata_pct}%</span>
                  <span>Cloud: {f.cloud_pct}%</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Collapsed Details Dropdown (Grouped by Scene/Date) */}
        {files.length > 0 && (
          <details className="mt-2 text-[10.5px]">
            <summary className="font-mono cursor-pointer text-muted-foreground hover:text-foreground select-none">
              Details ({files.length} raster{files.length === 1 ? '' : 's'} checked)
            </summary>
            <div className="mt-1.5 border-t border-border pt-1 space-y-1 max-h-[240px] overflow-y-auto">
              {groupedScenes.map((scene) => (
                <div
                  key={scene.key}
                  className="text-[11px] text-foreground border-b border-border/60 last:border-none pb-1.5 pt-1"
                >
                  <div className="flex justify-between items-center gap-2">
                    <span className="font-mono font-semibold text-foreground truncate">
                      {scene.label}
                      {scene.count > 1 && (
                        <span className="text-muted-foreground font-normal ml-1.5">
                          ({scene.count} bands{scene.bands.length ? `: ${scene.bands.join(', ')}` : ''})
                        </span>
                      )}
                    </span>
                    <span
                      className="font-mono font-bold text-[10.5px] shrink-0"
                      style={{ color: scene.allUsable ? '#34D399' : '#F87171' }}
                    >
                      {scene.allUsable ? 'PASS' : 'FAIL'}
                    </span>
                  </div>
                  <div className="flex gap-4 mt-0.5 text-muted-foreground font-mono text-[10px]">
                    <span>Max Nodata: {scene.maxNodata}%</span>
                    <span>Max Cloud: {scene.maxCloud}%</span>
                  </div>
                </div>
              ))}
            </div>
          </details>
        )}

        {!ev.files && ev.raster_paths && ev.raster_paths.length > 0 && (
          <details className="mt-2 text-[10.5px]">
            <summary className="font-mono cursor-pointer text-muted-foreground hover:text-foreground select-none">
              Details ({ev.raster_paths.length} raster path{ev.raster_paths.length === 1 ? '' : 's'})
            </summary>
            <div className="flex flex-wrap gap-1 mt-1.5">
              {ev.raster_paths.map((rp) => (
                <span
                  key={rp}
                  className="font-mono text-[10px] bg-muted text-foreground px-1.5 py-0.5 rounded-none"
                >
                  {cleanName(rp)}
                </span>
              ))}
            </div>
          </details>
        )}

        {ev.reason && (
          <div
            className="text-[11px] mt-1.5 leading-snug"
            style={{ color: isBad ? '#FCA5A5' : '#A7F3D0' }}
          >
            {ev.reason}
          </div>
        )}
      </div>
    );
  }

  // 2. Vision Grid Defined
  if (type === 'vision_grid') {
    const ev = activity as SSEVisionGridEvent;
    const fileName = cleanName(ev.image);
    return (
      <div className="rounded-none bg-card border border-border p-2 text-foreground">
        <div className="flex items-center gap-1.5 font-mono text-[11px] font-semibold text-sky-400">
          <Grid className="h-3.5 w-3.5 shrink-0" />
          <span>
            Grid Defined {fileName ? `for ${fileName}` : ''}: {ev.rows}×{ev.cols} (
            {ev.tiles ? ev.tiles.length : 0} tiles)
          </span>
        </div>
        <div className="text-[10px] text-muted-foreground font-mono mt-0.5">
          Step {ev.steps_used} / {ev.budget}
        </div>
      </div>
    );
  }

  // 3. Inspecting Tile with Live Thumbnail
  if (type === 'vision_inspecting_tile') {
    const ev = activity as SSEVisionInspectingTileEvent;
    const fileName = cleanName(ev.image);
    return (
      <div
        className="rounded-none bg-card border border-border p-2 text-foreground"
        style={{ borderLeft: '3px solid #3B82F6' }}
      >
        <div className="flex items-center gap-2">
          <Search className="h-3.5 w-3.5 text-blue-400 shrink-0" />
          <span className="font-mono text-[11px] font-semibold text-blue-400">
            Inspecting: {fileName ? `${fileName} · ` : ''}
            {ev.tile_id}
          </span>
          <span className="text-[10px] text-muted-foreground font-mono ml-auto">
            Zoom ×{ev.zoom_level || 1}
          </span>
        </div>
        {ev.thumb_url && (
          <img
            src={ev.thumb_url}
            alt={`Tile inspection ${ev.tile_id}`}
            loading="lazy"
            className="w-full max-h-[260px] object-contain mt-1.5 rounded-none border border-border bg-background"
          />
        )}
      </div>
    );
  }

  // 4. Tile Verdict
  if (type === 'vision_tile_verdict') {
    const ev = activity as SSEVisionTileVerdictEvent;
    const color = ev.color || '#94A3B8';
    const fileName = cleanName(ev.image);
    return (
      <div
        className="rounded-none bg-card border border-border p-2 text-foreground"
        style={{ borderLeft: `4px solid ${color}` }}
      >
        <div className="flex items-center gap-2 text-[11px]">
          <Scale className="h-3.5 w-3.5 text-foreground shrink-0" />
          <span className="font-mono font-semibold text-foreground">
            Verdict: {fileName ? `${fileName} · ` : ''}
            {ev.tile_id}
          </span>
          <span className="font-mono ml-auto font-bold" style={{ color }}>
            {(ev.verdict || '').toUpperCase()}
          </span>
        </div>
        {ev.rationale && (
          <div className="text-[11px] text-foreground mt-1 leading-snug whitespace-pre-wrap break-words">
            {ev.rationale}
          </div>
        )}
        {ev.confidence != null && (
          <div className="mt-1.5 text-[10px] font-mono text-muted-foreground">
            Confidence: {Math.round(ev.confidence * 100)}%
          </div>
        )}
      </div>
    );
  }

  // 5. Vision Progress Bar
  if (type === 'vision_progress') {
    const ev = activity as SSEVisionProgressEvent;
    const pct = ev.budget > 0 ? Math.round((ev.steps_used / ev.budget) * 100) : 0;
    return (
      <div className="px-2 py-1 text-[10px] text-muted-foreground flex items-center gap-2">
        <div className="flex-1 h-1 bg-muted rounded-none overflow-hidden">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          />
        </div>
        <span className="font-mono">
          Step {ev.steps_used}/{ev.budget}
        </span>
      </div>
    );
  }

  // 6. Vision Stopped
  if (type === 'vision_stopped') {
    const ev = activity as SSEVisionStoppedEvent;
    const isBad = ev.reason !== 'valid';
    return (
      <div
        className="rounded-none bg-card p-2.5 text-foreground"
        style={{ border: isBad ? '1px solid #EF4444' : '1px solid #10B981' }}
      >
        <div
          className="flex items-center gap-1.5 font-bold text-xs"
          style={{ color: isBad ? '#FCA5A5' : '#34D399' }}
        >
          <OctagonAlert className="h-4 w-4 shrink-0" />
          <span>Vision Loop Stopped</span>
        </div>
        <div className="text-[11px] mt-1 text-foreground">
          Reason: <span className="font-mono font-semibold">{ev.reason}</span>
        </div>
        {ev.detail && (
          <div className="text-[10.5px] text-muted-foreground mt-1 italic">{ev.detail}</div>
        )}
      </div>
    );
  }

  // 7. Final Vision Summary
  if (type === 'vision_summary') {
    const ev = activity as SSEVisionSummaryEvent;
    const isGood = ev.final_verdict === 'valid';
    const isBad = ev.final_verdict === 'not_valid';
    const color = isGood ? '#10B981' : isBad ? '#EF4444' : '#F59E0B';

    return (
      <div
        className="rounded-none bg-card border border-border p-3 mt-1.5 text-foreground"
        style={{ borderLeft: `4px solid ${color}` }}
      >
        <div className="flex items-center gap-2 font-bold text-xs mb-2 text-foreground">
          <BarChart3 className="h-4 w-4 text-sky-400 shrink-0" />
          <span>Final Vision Summary</span>
        </div>

        <div className="grid grid-cols-2 gap-2.5 mb-2.5">
          <div className="p-2 text-center bg-muted border border-border rounded-none">
            <div className="text-[10px] text-muted-foreground">Verdict</div>
            <div className="text-xs font-extrabold font-mono mt-0.5" style={{ color }}>
              {(ev.final_verdict || '').toUpperCase()}
            </div>
          </div>
          <div className="p-2 text-center bg-muted border border-border rounded-none">
            <div className="text-[10px] text-muted-foreground">Area Verified</div>
            <div className="text-xs font-extrabold font-mono text-foreground mt-0.5">
              {ev.verified_area_pct}%
            </div>
          </div>
        </div>

        {ev.summary && (
          <div className="font-mono text-[11px] mb-2 text-foreground leading-relaxed">
            {ev.summary}
          </div>
        )}

        {ev.checklist_results && Object.keys(ev.checklist_results).length > 0 && (
          <div className="border-t border-border pt-2 mb-2">
            <div className="text-[11px] font-bold mb-1 text-foreground">Checklist:</div>
            <table className="w-full text-[11px] text-foreground">
              <tbody>
                {Object.entries(ev.checklist_results).map(([k, v]) => (
                  <tr key={k} className="border-b border-border/60 last:border-none">
                    <td className="font-mono py-1 pr-2">{k}</td>
                    <td className="py-1 pl-2 text-right">
                      {v ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 inline" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-rose-400 inline" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {ev.flagged_regions && ev.flagged_regions.length > 0 && (
          <div className="border-t border-border pt-2">
            <div className="flex items-center gap-1.5 text-[11px] font-bold mb-1.5 text-rose-300">
              <Flag className="h-3.5 w-3.5 text-rose-400" />
              <span>Flagged Issues:</span>
            </div>
            <div className="space-y-1">
              {ev.flagged_regions.map((f) => (
                <div
                  key={f.tile_id}
                  className="text-[10.5px] p-1.5 rounded-none bg-rose-500/10 border border-rose-500/30 text-rose-200"
                >
                  <span className="font-mono font-semibold">{f.tile_id}:</span> {f.rationale}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // 8. Vision Feedback (Self-Correction Guidance)
  if (type === 'vision_feedback') {
    const ev = activity as SSEVisionFeedbackEvent;
    return (
      <div
        className="rounded-none bg-card border border-border p-2 mb-1.5 text-foreground"
        style={{ borderLeft: '3px solid #F59E0B' }}
      >
        <div className="font-mono text-[11px] font-semibold text-amber-400">
          {ev.file}
          {ev.tile_id ? ` · tile ${ev.tile_id}` : ''}
        </div>
        <div className="text-[10px] text-muted-foreground my-0.5">
          Severity: <strong>{ev.severity || 'medium'}</strong> | Category:{' '}
          {ev.category || 'output'}
        </div>
        {ev.suggested_fix && (
          <div className="text-[11px] text-foreground">{ev.suggested_fix}</div>
        )}
      </div>
    );
  }

  // 9. Consensus Re-Verification Done
  if (type === 'vision_consensus_done') {
    const ev = activity as SSEVisionConsensusDoneEvent;
    return (
      <div className="rounded-none bg-card border border-sky-600 p-2 text-foreground">
        <div className="flex items-center gap-1.5 font-mono text-[11px] font-semibold text-sky-400">
          <Handshake className="h-3.5 w-3.5 shrink-0" />
          <span>Consensus Re-verification Complete</span>
        </div>
        <div className="text-[10px] text-muted-foreground mt-0.5">
          {ev.re_verified ?? 0} tile(s) reviewed for agreement.
        </div>
      </div>
    );
  }

  // 10. Vision Insufficient Data
  if (type === 'vision_insufficient_data') {
    const ev = activity as SSEVisionInsufficientDataEvent;
    return (
      <div
        className="rounded-none bg-card border border-rose-500 p-2.5 text-foreground"
        style={{ borderLeft: '4px solid #EF4444' }}
      >
        <div className="flex items-center gap-1.5 font-mono text-[11px] font-bold text-rose-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>Insufficient Input Data Quality</span>
        </div>
        {ev.reason && (
          <div className="text-[11px] text-rose-200 mt-1 leading-snug">{ev.reason}</div>
        )}
      </div>
    );
  }

  return null;
};

