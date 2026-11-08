// GeoLLM Dataset Catalog & Workspaces Sidebar (React 18 JSX Component)
import React, { useState, useMemo } from 'https://esm.sh/react@18.2.0';

function getDynamicFileMeta(file) {
  const name = (file.name || '').toLowerCase();
  const ext = name.split('.').pop();

  let typeLabel = 'File';
  let category = 'Other';
  let icon = '📄';

  if (['tif', 'tiff', 'jp2', 'img', 'vrt'].includes(ext)) {
    typeLabel = 'GeoTIFF Raster';
    category = 'Raster';
    icon = '🗺️';
  } else if (['geojson', 'shp', 'kml', 'gpkg'].includes(ext)) {
    typeLabel = 'Vector Data';
    category = 'Vector';
    icon = '📐';
  } else if (['csv', 'json'].includes(ext)) {
    typeLabel = ext.toUpperCase();
    category = 'Vector';
    icon = '📊';
  } else if (['laz', 'las'].includes(ext)) {
    typeLabel = 'LiDAR Point Cloud';
    category = 'Other';
    icon = '🌲';
  } else if (['zip', 'tar', 'gz', '7z'].includes(ext)) {
    typeLabel = 'Archive';
    category = 'Other';
    icon = '📦';
  }

  return {
    category,
    typeLabel,
    icon,
    sizeStr: file.size_mb ? `${file.size_mb} MB` : '',
    dateStr: file.modified || '',
  };
}

export function DatasetSidebar({
  files = [],
  selectedFiles = [],
  setSelectedFiles,
  onUploadFiles,
  onNotify,
  workspaces = [],
  activeWorkspaceId,
  onSelectWorkspace,
  onCreateWorkspace,
  onDeleteWorkspace,
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('All'); // 'All' | 'Raster' | 'Vector' | 'Other'
  const [newWsName, setNewWsName] = useState('');
  const [showWsCreateInput, setShowWsCreateInput] = useState(false);
  const [confirmDeleteWsId, setConfirmDeleteWsId] = useState(null);

  const dynamicFiles = useMemo(() => {
    return files.map(f => {
      const meta = getDynamicFileMeta(f);
      return {
        ...f,
        ...meta
      };
    });
  }, [files]);

  const filteredFiles = useMemo(() => {
    return dynamicFiles.filter(item => {
      const matchesFilter =
        filter === 'All' ||
        (filter === 'Raster' && item.category === 'Raster') ||
        (filter === 'Vector' && item.category === 'Vector') ||
        (filter === 'Other' && item.category === 'Other');

      const matchesSearch =
        !search.trim() ||
        item.name.toLowerCase().includes(search.toLowerCase()) ||
        item.typeLabel.toLowerCase().includes(search.toLowerCase());

      return matchesFilter && matchesSearch;
    });
  }, [dynamicFiles, filter, search]);

  const toggleFile = (fileName) => {
    if (selectedFiles.includes(fileName)) {
      setSelectedFiles(selectedFiles.filter(f => f !== fileName));
    } else {
      setSelectedFiles([...selectedFiles, fileName]);
    }
  };

  const handleSelectAllFiltered = () => {
    const names = filteredFiles.map(f => f.name);
    const combined = Array.from(new Set([...selectedFiles, ...names]));
    setSelectedFiles(combined);
    if (onNotify) onNotify(`Selected ${names.length} datasets`, 'info');
  };

  const handleClearSelected = () => {
    setSelectedFiles([]);
  };

  const handleAddWorkspaceSubmit = (e) => {
    e.preventDefault();
    const trimmed = newWsName.trim();
    if (!trimmed) {
      if (onNotify) onNotify('Please enter a workspace name', 'warning');
      return;
    }
    onCreateWorkspace(trimmed);
    setNewWsName('');
    setShowWsCreateInput(false);
  };

  return (
    <aside
      className="geollm-spacious-sidebar"
      style={{
        width: '330px',
        minWidth: '310px',
        maxWidth: '360px',
        height: '100%',
        background: '#090D14',
        borderRight: '1px solid #1E293B',
        position: 'relative',
        zIndex: 15,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        color: '#F1F5F9'
      }}
    >
      {/* Top Header: Explorer & Total Datasets */}
      <div style={{ padding: '16px 16px 12px 16px', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: '13px', color: '#F1F5F9', letterSpacing: '-0.01em' }}>
            GeoLLM Data Catalog
          </div>
          <div className="mono" style={{ fontSize: '11px', color: '#64748B', marginTop: '2px' }}>
            {files.length} {files.length === 1 ? 'dataset' : 'datasets'} in storage
          </div>
        </div>

        <label
          style={{
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            background: '#1E293B',
            color: '#38BDF8',
            border: '1px solid #334155',
            padding: '5px 10px',
            borderRadius: '6px',
            fontSize: '11px',
            fontWeight: 600,
            transition: 'all 0.15s ease'
          }}
          title="Upload rasters, shapefiles, or archives"
        >
          <span>⬆️ Upload</span>
          <input
            type="file"
            multiple
            accept=".tif,.tiff,.geojson,.shp,.gpkg,.csv,.json,.zip,.laz"
            style={{ display: 'none' }}
            onChange={(e) => onUploadFiles && onUploadFiles(e.target.files)}
          />
        </label>
      </div>

      {/* Spacious Search Bar & Category Filters */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #1E293B', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ position: 'relative', width: '100%' }}>
          <input
            type="search"
            placeholder="Search datasets by name or type..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: '100%',
              background: '#111827',
              border: '1px solid #1E293B',
              borderRadius: '6px',
              color: '#F1F5F9',
              padding: '8px 12px',
              fontSize: '11.5px',
              outline: 'none',
              boxSizing: 'border-box'
            }}
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              style={{
                position: 'absolute',
                right: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'none',
                border: 'none',
                color: '#64748B',
                cursor: 'pointer',
                fontSize: '12px'
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div style={{ display: 'flex', gap: '6px' }}>
          {['All', 'Raster', 'Vector', 'Other'].map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setFilter(cat)}
              style={{
                flex: 1,
                fontSize: '11px',
                padding: '5px 0',
                borderRadius: '5px',
                border: filter === cat ? '1px solid #14B8A6' : '1px solid #1E293B',
                background: filter === cat ? 'rgba(20, 184, 166, 0.15)' : '#111827',
                color: filter === cat ? '#14B8A6' : '#94A3B8',
                cursor: 'pointer',
                fontWeight: 600,
                textAlign: 'center'
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Spacious Dataset Items List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {filteredFiles.length === 0 ? (
          <div style={{ padding: '36px 16px', textAlign: 'center', color: '#64748B', fontSize: '12px' }}>
            {search ? 'No matching datasets found.' : 'No files found in data/ directory.'}
          </div>
        ) : (
          filteredFiles.map((item) => {
            const isChecked = selectedFiles.includes(item.name);
            return (
              <div
                key={item.name}
                onClick={() => toggleFile(item.name)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '9px 12px',
                  background: isChecked ? 'rgba(20, 184, 166, 0.12)' : '#111827',
                  border: isChecked ? '1px solid #14B8A6' : '1px solid #1E293B',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  transition: 'background 0.15s ease, border 0.15s ease'
                }}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    e.stopPropagation();
                    toggleFile(item.name);
                  }}
                  style={{ accentColor: '#14B8A6', cursor: 'pointer', width: '15px', height: '15px' }}
                />

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="mono"
                    title={item.name}
                    style={{
                      fontSize: '11.5px',
                      color: isChecked ? '#38BDF8' : '#F1F5F9',
                      fontWeight: 600,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}
                  >
                    {item.name}
                  </div>
                  <div
                    className="mono"
                    style={{
                      fontSize: '10px',
                      color: '#64748B',
                      marginTop: '2px',
                      display: 'flex',
                      gap: '8px',
                      alignItems: 'center'
                    }}
                  >
                    <span>{item.typeLabel}</span>
                    {item.sizeStr && <span>• {item.sizeStr}</span>}
                    {item.dateStr && <span>• {item.dateStr}</span>}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Datasets Selection Footer */}
      <div style={{ padding: '8px 16px', background: '#0F172A', borderTop: '1px solid #1E293B', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="mono" style={{ fontSize: '11px', color: selectedFiles.length > 0 ? '#14B8A6' : '#64748B', fontWeight: 600 }}>
          {selectedFiles.length} selected
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {filteredFiles.length > 0 && (
            <button
              type="button"
              onClick={handleSelectAllFiltered}
              style={{
                background: '#1E293B',
                border: '1px solid #334155',
                color: '#E2E8F0',
                cursor: 'pointer',
                fontSize: '10.5px',
                padding: '3px 8px',
                borderRadius: '4px',
                fontWeight: 600
              }}
              title="Select all currently filtered datasets"
            >
              Select All
            </button>
          )}
          {selectedFiles.length > 0 && (
            <button
              type="button"
              onClick={handleClearSelected}
              style={{
                background: 'none',
                border: 'none',
                color: '#EF4444',
                cursor: 'pointer',
                fontSize: '11px',
                fontWeight: 600
              }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* DYNAMIC WORKSPACES SECTION (100% User-Created, Max 3 Containers, Delete & Free Container) */}
      <div
        className="dynamic-workspaces-section"
        style={{
          borderTop: '2px solid #1E293B',
          background: '#0B0F17',
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '11.5px', fontWeight: 700, color: '#14B8A6', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Workspaces
            </span>
            <span
              className="mono"
              style={{
                fontSize: '10.5px',
                background: workspaces.length === 3 ? 'rgba(245, 158, 11, 0.2)' : '#111827',
                color: workspaces.length === 3 ? '#F59E0B' : '#38BDF8',
                padding: '2px 7px',
                borderRadius: '10px',
                border: '1px solid #1E293B'
              }}
            >
              {workspaces.length} / 3 Active
            </span>
          </div>

          {workspaces.length < 3 && (
            <button
              type="button"
              onClick={() => setShowWsCreateInput(!showWsCreateInput)}
              style={{
                background: '#0F766E',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '4px',
                padding: '3px 9px',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
              title="Create new workspace with dynamic name"
            >
              + New Workspace
            </button>
          )}
        </div>

        {/* Quota Notice when all 3 containers are allocated */}
        {workspaces.length >= 3 && (
          <div style={{ padding: '6px 10px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.3)', color: '#F59E0B', fontSize: '10.5px', lineHeight: 1.4 }}>
            ⚠️ All containers allocated (3/3 active). Delete a workspace below to free a container.
          </div>
        )}

        {/* Create Workspace Inline Input */}
        {showWsCreateInput && workspaces.length < 3 && (
          <form onSubmit={handleAddWorkspaceSubmit} style={{ display: 'flex', gap: '6px' }}>
            <input
              type="text"
              autoFocus
              placeholder="e.g. Dubai Flood Analysis..."
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              style={{
                flex: 1,
                background: '#111827',
                border: '1px solid #14B8A6',
                borderRadius: '4px',
                color: '#F1F5F9',
                padding: '5px 8px',
                fontSize: '11px',
                outline: 'none'
              }}
            />
            <button
              type="submit"
              style={{
                background: '#0F766E',
                color: '#FFFFFF',
                border: 'none',
                borderRadius: '4px',
                padding: '5px 10px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => {
                setShowWsCreateInput(false);
                setNewWsName('');
              }}
              style={{
                background: '#1E293B',
                color: '#94A3B8',
                border: 'none',
                borderRadius: '4px',
                padding: '5px 8px',
                fontSize: '11px',
                cursor: 'pointer'
              }}
            >
              ✕
            </button>
          </form>
        )}

        {/* Workspaces List (Dynamically created only, with Delete button) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {workspaces.length === 0 ? (
            <div style={{ padding: '12px 10px', textAlign: 'center', color: '#64748B', fontSize: '11px', border: '1px dashed #1E293B', borderRadius: '6px' }}>
              No active workspaces. Click <strong>+ New Workspace</strong> to allocate a container sandbox.
            </div>
          ) : (
            workspaces.map((ws) => {
              const isSelected = activeWorkspaceId === ws.id;
              const containerSlotNum = ws.containerId ? ws.containerId.replace('task_', '') : '1';
              const isConfirming = confirmDeleteWsId === ws.id;

              return (
                <div
                  key={ws.id}
                  onClick={() => !isConfirming && onSelectWorkspace(ws.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    border: isConfirming ? '1px solid #EF4444' : isSelected ? '1px solid #14B8A6' : '1px solid #1E293B',
                    background: isConfirming ? 'rgba(239, 68, 68, 0.12)' : isSelected ? 'rgba(20, 184, 166, 0.12)' : '#111827',
                    cursor: isConfirming ? 'default' : 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  {isConfirming ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%' }}>
                      <div style={{ fontSize: '11px', color: '#F87171', lineHeight: 1.35, fontWeight: 500 }}>
                        Delete <strong>"{ws.name}"</strong>? Terminate task & free Container #{containerSlotNum}.
                      </div>
                      <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end', marginTop: '2px' }}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteWorkspace(ws.id);
                            setConfirmDeleteWsId(null);
                          }}
                          style={{
                            background: '#EF4444',
                            color: '#FFFFFF',
                            border: 'none',
                            borderRadius: '4px',
                            padding: '3px 8px',
                            fontSize: '10.5px',
                            fontWeight: 700,
                            cursor: 'pointer'
                          }}
                        >
                          Delete & Free
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteWsId(null);
                          }}
                          style={{
                            background: '#1E293B',
                            color: '#94A3B8',
                            border: '1px solid #334155',
                            borderRadius: '4px',
                            padding: '3px 8px',
                            fontSize: '10.5px',
                            cursor: 'pointer'
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#14B8A6' }}></span>
                          <span style={{ fontWeight: 600, fontSize: '12px', color: isSelected ? '#38BDF8' : '#F1F5F9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {ws.name}
                          </span>
                        </div>
                        <div className="mono" style={{ fontSize: '10px', color: '#64748B', marginTop: '2px' }}>
                          Container #{containerSlotNum} ({ws.containerId})
                        </div>
                      </div>

                      {/* Delete Workspace Button (Prompts non-blocking inline confirmation) */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteWsId(ws.id);
                        }}
                        title={`Delete workspace and free Container #${containerSlotNum}`}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#EF4444',
                          padding: '4px 6px',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '13px',
                          marginLeft: '6px'
                        }}
                      >
                        🗑️
                      </button>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
}
