import React, { useState, useMemo } from 'react';
import { FileInfo } from '@/types/geospatial';
import { Workspace } from '@/types/task';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Folder,
  FileImage,
  FileCode,
  Box,
  Upload,
  RefreshCw,
  Search,
  Trash2,
  AlertTriangle,
  Eye,
  XCircle,
} from 'lucide-react';

interface DatasetSidebarProps {
  files: FileInfo[];
  selectedFiles: string[];
  onToggleFile: (fileName: string) => void;
  onClearSelectedFiles?: () => void;
  onRefreshFiles: () => void;
  onUploadFiles: (files: FileList) => void;
  activeWorkspace: Workspace | null;
  onDeleteWorkspace: (wsId: string) => void;
  onInspectTiff?: (filePath: string) => void;
}

type FileCategory = 'all' | 'raster' | 'vector' | 'lidar' | 'other';

export const DatasetSidebar: React.FC<DatasetSidebarProps> = ({
  files,
  selectedFiles,
  onToggleFile,
  onClearSelectedFiles,
  onRefreshFiles,
  onUploadFiles,
  activeWorkspace,
  onDeleteWorkspace,
  onInspectTiff,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [category, setCategory] = useState<FileCategory>('all');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const getFileCategory = (fname: string): FileCategory => {
    const ext = fname.toLowerCase().split('.').pop() || '';
    if (['tif', 'tiff', 'jp2', 'img', 'vrt', 'nc', 'h5'].includes(ext)) return 'raster';
    if (['geojson', 'shp', 'kml', 'gpkg', 'csv', 'json'].includes(ext)) return 'vector';
    if (['laz', 'las'].includes(ext)) return 'lidar';
    return 'other';
  };

  const getFileIcon = (cat: FileCategory) => {
    switch (cat) {
      case 'raster':
        return <FileImage className="h-3.5 w-3.5 text-sky-400" />;
      case 'vector':
        return <FileCode className="h-3.5 w-3.5 text-teal-400" />;
      case 'lidar':
        return <Box className="h-3.5 w-3.5 text-emerald-400" />;
      default:
        return <Folder className="h-3.5 w-3.5 text-slate-400" />;
    }
  };

  const filteredFiles = useMemo(() => {
    return files.filter((f) => {
      const matchSearch = f.name.toLowerCase().includes(searchTerm.toLowerCase());
      if (category === 'all') return matchSearch;
      return matchSearch && getFileCategory(f.name) === category;
    });
  }, [files, searchTerm, category]);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onUploadFiles(e.target.files);
    }
  };

  return (
    <aside className="w-full h-full flex flex-col bg-[#070A0F] border-r border-[#1E293B] select-none text-xs">
      {/* Catalog Header */}
      <div className="p-3 border-b border-[#1E293B] flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-slate-200">
          <Folder className="h-4 w-4 text-sky-400" />
          <span>Data Catalog</span>
          <span className="text-[10px] text-slate-500 font-mono">({files.length})</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefreshFiles}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-[#111827] cursor-pointer"
            title="Refresh files"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <label className="p-1 rounded text-slate-400 hover:text-sky-400 hover:bg-[#111827] cursor-pointer">
            <Upload className="h-3.5 w-3.5" />
            <input type="file" multiple className="hidden" onChange={handleFileInput} />
          </label>
        </div>
      </div>

      {/* Search Input */}
      <div className="p-2 border-b border-[#1E293B]">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-500" />
          <Input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search datasets..."
            className="h-7 pl-8 text-xs bg-[#0B0F17] border-[#1E293B]"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 mt-2">
          {(['all', 'raster', 'vector', 'lidar'] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors cursor-pointer capitalize ${
                category === cat
                  ? 'bg-sky-500/20 text-sky-400 border border-sky-500/40'
                  : 'text-slate-400 hover:bg-[#111827]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Selected Files & Clear All Action */}
        {selectedFiles.length > 0 && (
          <div className="flex items-center justify-between mt-2 pt-2 border-t border-[#1E293B]/80 text-[#2DD4BF]">
            <span className="font-mono text-[10px] font-medium">
              {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
            </span>
            <button
              type="button"
              onClick={onClearSelectedFiles}
              className="flex items-center gap-1 text-[10px] font-semibold text-rose-400 hover:text-rose-300 hover:underline cursor-pointer bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/20"
              title="Deselect all files"
            >
              <XCircle className="h-3 w-3" />
              Clear all
            </button>
          </div>
        )}
      </div>

      {/* File List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {filteredFiles.length === 0 ? (
          <div className="text-slate-500 text-center py-8 text-[11px]">
            {files.length === 0 ? 'No files in data/ directory.' : 'No matching datasets.'}
          </div>
        ) : (
          filteredFiles.map((f) => {
            const isSelected = selectedFiles.includes(f.name);
            const cat = getFileCategory(f.name);

            return (
              <div
                key={f.name}
                onClick={() => onToggleFile(f.name)}
                className={`flex items-center gap-2 p-2 rounded-md border cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-[#0F766E]/20 border-[#14B8A6]/50 text-slate-100'
                    : 'bg-[#0B0F17] border-[#1E293B] text-slate-300 hover:border-slate-700'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => {}} // handled by parent div
                  className="rounded border-[#1E293B] bg-[#111827] text-teal-600 focus:ring-0 cursor-pointer"
                />
                {getFileIcon(cat)}
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-[11px] truncate" title={f.name}>
                    {f.name}
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">
                    {f.size_mb} MB • {f.modified}
                  </div>
                </div>
                {cat === 'raster' && onInspectTiff && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onInspectTiff(`data/${f.name}`);
                    }}
                    title="Inspect GeoTIFF Bands & Colormap"
                    className="p-1 rounded hover:bg-[#1E293B] text-slate-400 hover:text-sky-400 transition-colors shrink-0"
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Active Workspace Management Footer */}
      {activeWorkspace && (
        <div className="p-3 border-t border-[#1E293B] bg-[#0B0F17]">
          <div className="flex items-center justify-between mb-2">
            <div>
              <div className="text-[10px] text-slate-500 uppercase font-semibold">Active Container</div>
              <div className="font-mono text-[11px] text-slate-200 font-bold truncate">
                #{activeWorkspace.containerId.replace('task_', '')} — {activeWorkspace.name}
              </div>
            </div>

            {confirmDelete ? (
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-6 text-[10px] px-2"
                  onClick={() => {
                    onDeleteWorkspace(activeWorkspace.id);
                    setConfirmDelete(false);
                  }}
                >
                  Confirm
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 text-[10px] px-2"
                  onClick={() => setConfirmDelete(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 cursor-pointer transition-colors"
                title="Delete workspace and free container slot"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {confirmDelete && (
            <div className="flex items-center gap-1.5 text-[10px] text-rose-400 bg-rose-500/10 p-1.5 rounded border border-rose-500/30">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              <span>Frees Docker container and clears workspace state.</span>
            </div>
          )}
        </div>
      )}
    </aside>
  );
};

