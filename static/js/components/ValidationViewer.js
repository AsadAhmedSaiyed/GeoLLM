import { html, React } from '../html.js';

/**
 * ValidationViewer renders the live agentic vision validation events.
 * It handles the input quality gate, grid overlay, tile highlights, thumbnails, and final summary.
 */
export const ValidationViewer = ({ activity }) => {
  if (!activity) return null;
  const { type } = activity;

  const cleanName = (p) => {
    if (!p) return '';
    return p.split(/[\\/]/).pop();
  };

  if (type === 'vision_input_gate') {
    const isDone = activity.state === 'done';
    const isBad = activity.verdict === 'insufficient_data';
    const borderColor = isBad ? '#EF4444' : isDone ? '#10B981' : '#38BDF8';
    const badgeColor = isBad ? '#FCA5A5' : isDone ? '#34D399' : '#38BDF8';
    const badgeBg = isBad ? 'rgba(239, 68, 68, 0.15)' : isDone ? 'rgba(16, 185, 129, 0.15)' : 'rgba(56, 189, 248, 0.15)';

    return html`
      <div
        className="tool-card ${isBad ? 'bad' : isDone ? 'ok' : 'run'}"
        style=${{
          padding: '10px 12px',
          background: '#0F172A',
          border: `1px solid ${borderColor}`,
          borderLeft: `4px solid ${borderColor}`,
          borderRadius: '6px',
          color: '#F1F5F9'
        }}
      >
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', fontWeight: 700, marginBottom: '4px' }}>
          <span>🛡️ Input Quality Gate</span>
          ${activity.raster_count != null ? html`
            <span className="mono" style=${{ fontSize: '10.5px', color: '#94A3B8', fontWeight: 500 }}>
              (${activity.raster_count} raster${activity.raster_count === 1 ? '' : 's'})
            </span>
          ` : null}
          <span
            className="mono"
            style=${{
              marginLeft: 'auto',
              fontSize: '10px',
              padding: '2px 7px',
              borderRadius: '4px',
              background: badgeBg,
              color: badgeColor,
              fontWeight: 700,
              textTransform: 'uppercase'
            }}
          >
            ${activity.verdict || (activity.state === 'started' ? 'Checking inputs…' : 'Checking…')}
          </span>
        </div>

        ${activity.area_verified_pct != null ? html`
          <div className="mono" style=${{ fontSize: '10.5px', color: '#94A3B8', marginBottom: '4px' }}>
            Spatial coverage verified: <strong style=${{ color: '#E2E8F0' }}>${activity.area_verified_pct}%</strong>
          </div>
        ` : null}

        ${activity.files && activity.files.map(f => html`
          <div key=${f.name} style=${{ fontSize: '11px', color: '#CBD5E1', borderTop: '1px solid #1E293B', paddingTop: '4px', marginTop: '4px' }}>
            <div style=${{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="mono" style=${{ fontWeight: 600, color: '#F1F5F9' }}>${cleanName(f.name)}</span>
              <span className="mono" style=${{ color: f.is_usable ? '#34D399' : '#F87171', fontWeight: 700 }}>${f.is_usable ? 'PASS' : 'FAIL'}</span>
            </div>
            <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '2px', color: '#94A3B8', fontSize: '10.5px' }}>
              <span>Nodata: ${f.nodata_pct}%</span>
              <span>Cloud: ${f.cloud_pct}%</span>
            </div>
          </div>
        `)}

        ${(!activity.files && activity.raster_paths && activity.raster_paths.length > 0) ? html`
          <div style=${{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
            ${activity.raster_paths.slice(0, 8).map(rp => html`
              <span key=${rp} className="mono" style=${{ fontSize: '10px', background: '#1E293B', color: '#CBD5E1', padding: '1px 6px', borderRadius: '4px' }}>
                ${cleanName(rp)}
              </span>
            `)}
            ${activity.raster_paths.length > 8 ? html`
              <span className="mono" style=${{ fontSize: '10px', color: '#64748B', padding: '1px 4px' }}>
                +${activity.raster_paths.length - 8} more
              </span>
            ` : null}
          </div>
        ` : null}

        ${activity.reason && html`
          <div style=${{ fontSize: '11px', color: isBad ? '#FCA5A5' : '#A7F3D0', marginTop: '6px', lineHeight: 1.4 }}>
            ${activity.reason}
          </div>
        `}
      </div>
    `;
  }

  if (type === 'vision_grid') {
    const fileName = cleanName(activity.image);
    return html`
      <div className="tool-card ok" style=${{ padding: '6px 8px', background: '#0F172A', border: '1px solid #1E293B', color: '#E2E8F0' }}>
        <div className="mono" style=${{ fontSize: '11px', fontWeight: 600, color: '#38BDF8' }}>
          🗺️ Grid Defined ${fileName ? `for ${fileName}` : ''}: ${activity.rows}x${activity.cols} (${activity.tiles ? activity.tiles.length : 0} tiles)
        </div>
        <div style=${{ fontSize: '10px', color: '#94A3B8' }}>
          Step ${activity.steps_used} / ${activity.budget}
        </div>
      </div>
    `;
  }

  if (type === 'vision_inspecting_tile') {
    const fileName = cleanName(activity.image);
    return html`
      <div className="tool-card run" style=${{ padding: '6px 8px', background: '#0F172A', border: '1px solid #1E293B', borderLeft: '3px solid #3B82F6', color: '#E2E8F0' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="mono" style=${{ fontSize: '11px', fontWeight: 600, color: '#60A5FA' }}>
            🔍 Inspecting: ${fileName ? `${fileName} · ` : ''}${activity.tile_id}
          </span>
          <span style=${{ fontSize: '10px', color: '#94A3B8', marginLeft: 'auto' }}>Zoom x${activity.zoom_level || 1}</span>
        </div>
        ${activity.thumb_url && html`
          <img
            src=${activity.thumb_url}
            style=${{ width: '100%', height: 'auto', marginTop: '6px', borderRadius: '4px', border: '1px solid #334155' }}
            alt="Tile inspection"
          />
        `}
      </div>
    `;
  }

  if (type === 'vision_tile_verdict') {
    const color = activity.color || '#94A3B8';
    const fileName = cleanName(activity.image);
    return html`
      <div className="tool-card" style=${{ padding: '6px 8px', background: '#0F172A', border: '1px solid #1E293B', borderLeft: `4px solid ${color}`, color: '#E2E8F0' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' }}>
          <span className="mono" style=${{ fontWeight: 600, color: '#F1F5F9' }}>⚖️ Verdict: ${fileName ? `${fileName} · ` : ''}${activity.tile_id}</span>
          <span className="mono" style=${{ marginLeft: 'auto', fontWeight: 700, color: color }}>${(activity.verdict || '').toUpperCase()}</span>
        </div>
        <div style=${{ fontSize: '11px', color: '#CBD5E1', marginTop: '4px', lineHeight: '1.45', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          ${activity.rationale}
        </div>
        ${activity.confidence != null && html`
          <div style=${{ marginTop: '6px', fontSize: '10px', color: '#94A3B8' }}>
             Confidence: ${Math.round(activity.confidence * 100)}%
          </div>
        `}
      </div>
    `;
  }

  if (type === 'vision_progress') {
    const pct = Math.round((activity.steps_used / activity.budget) * 100);
    return html`
      <div style=${{ padding: '4px 8px', fontSize: '10px', color: '#94A3B8', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style=${{ flex: 1, height: '4px', background: '#1E293B', borderRadius: '2px', overflow: 'hidden' }}>
          <div style=${{ width: `${pct}%`, height: '100%', background: '#10b981' }}></div>
        </div>
        <span className="mono">Step ${activity.steps_used}/${activity.budget}</span>
      </div>
    `;
  }

  if (type === 'vision_stopped') {
    const isBad = activity.reason !== 'valid';
    return html`
      <div className="tool-card ${isBad ? 'bad' : 'ok'}" style=${{ padding: '10px', background: '#0F172A', border: isBad ? '1px solid #EF4444' : '1px solid #10B981', color: '#F1F5F9' }}>
        <div style=${{ fontWeight: 'bold', fontSize: '13px', color: isBad ? '#FCA5A5' : '#34D399' }}>
          🛑 Vision Loop Stopped
        </div>
        <div style=${{ fontSize: '11px', marginTop: '4px', color: '#E2E8F0' }}>
          Reason: <span className="mono" style=${{ fontWeight: 600 }}>${activity.reason}</span>
        </div>
        ${activity.detail && html`<div style=${{ fontSize: '10.5px', color: '#94A3B8', marginTop: '4px', fontStyle: 'italic' }}>${activity.detail}</div>`}
      </div>
    `;
  }

  if (type === 'vision_summary') {
    const isGood = activity.final_verdict === 'valid';
    const isBad = activity.final_verdict === 'not_valid';
    const color = isGood ? '#10B981' : isBad ? '#EF4444' : '#F59E0B';
    return html`
      <div className="task-findings-card" style=${{ marginTop: '10px', background: '#0F172A', border: '1px solid #1E293B', borderLeft: `4px solid ${color}`, color: '#F1F5F9' }}>
        <div style=${{ fontWeight: 'bold', fontSize: '14px', marginBottom: '8px', color: '#F1F5F9' }}>
          📊 Final Vision Summary
        </div>
        <div style=${{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
          <div className="tool-card" style=${{ padding: '8px', textAlign: 'center', background: '#111827', border: '1px solid #1E293B' }}>
            <div style=${{ fontSize: '10px', color: '#94A3B8' }}>Verdict</div>
            <div style=${{ fontSize: '14px', fontWeight: 800, color: color }}>${(activity.final_verdict || '').toUpperCase()}</div>
          </div>
          <div className="tool-card" style=${{ padding: '8px', textAlign: 'center', background: '#111827', border: '1px solid #1E293B' }}>
            <div style=${{ fontSize: '10px', color: '#94A3B8' }}>Area Verified</div>
            <div style=${{ fontSize: '14px', fontWeight: 800, color: '#F1F5F9' }}>${activity.verified_area_pct}%</div>
          </div>
        </div>
        <div className="mono" style=${{ fontSize: '11px', marginBottom: '8px', color: '#CBD5E1' }}>
          ${activity.summary}
        </div>
        ${activity.checklist_results && Object.keys(activity.checklist_results).length > 0 && html`
          <div style=${{ borderTop: '1px solid #1E293B', paddingTop: '6px', marginBottom: '8px' }}>
            <div style=${{ fontSize: '11px', fontWeight: 'bold', marginBottom: '4px', color: '#E2E8F0' }}>📋 Checklist:</div>
            <table className="checklist-table" style=${{ width: '100%', fontSize: '11px', color: '#CBD5E1' }}>
              <tbody>
                ${Object.entries(activity.checklist_results).map(([k, v]) => html`
                  <tr key=${k}><td className="mono" style=${{ padding: '2px 4px' }}>${k}</td><td style=${{ padding: '2px 4px', textAlign: 'right' }}>${v ? '✅' : '❌'}</td></tr>
                `)}
              </tbody>
            </table>
          </div>
        `}
        ${activity.flagged_regions && activity.flagged_regions.length > 0 && html`
          <div style=${{ borderTop: '1px solid #1E293B', paddingTop: '8px' }}>
            <div style=${{ fontSize: '11px', fontWeight: 'bold', marginBottom: '4px', color: '#FCA5A5' }}>🚩 Flagged Issues:</div>
            ${activity.flagged_regions.map(f => html`
              <div key=${f.tile_id} style=${{ fontSize: '10.5px', marginBottom: '4px', padding: '6px', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '4px', color: '#FECACA' }}>
                <span style=${{ fontWeight: 600 }}>${f.tile_id}:</span> ${f.rationale}
              </div>
            `)}
          </div>
        `}
      </div>
    `;
  }

  if (type === 'vision_feedback') {
    return html`
      <div className="tool-card vision-feedback-card" style=${{ padding: '6px 8px', marginBottom: '6px', background: '#0F172A', border: '1px solid #1E293B', borderLeft: '3px solid #F59E0B', color: '#E2E8F0' }}>
        <div className="mono" style=${{ fontSize: '11px', fontWeight: 600, color: '#FBBF24' }}>
          ${activity.file}${activity.tile_id ? ' · tile ' + activity.tile_id : ''}
        </div>
        <div style=${{ fontSize: '10px', color: '#94A3B8', margin: '2px 0' }}>
          Severity: <strong>${activity.severity || 'medium'}</strong> | Category: ${activity.category || 'output'}
        </div>
        <div style=${{ fontSize: '11px', color: '#CBD5E1' }}>${activity.suggested_fix || ''}</div>
      </div>
    `;
  }

  if (type === 'vision_consensus_done') {
    return html`
      <div className="tool-card ok" style=${{ padding: '6px 8px', background: '#0F172A', border: '1px solid #0284C7', color: '#E2E8F0' }}>
        <div className="mono" style=${{ fontSize: '11px', fontWeight: 600, color: '#38BDF8' }}>
          🤝 Consensus Re-verification Complete
        </div>
        <div style=${{ fontSize: '10px', color: '#94A3B8' }}>
          ${activity.re_verified} tile(s) reviewed for agreement.
        </div>
      </div>
    `;
  }

  return null;
};
