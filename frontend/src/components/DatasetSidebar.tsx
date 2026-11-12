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
        return <FileImage className="h-3.5 w-3.5 text-primary" />;
      case 'vector':
        return <FileCode className="h-3.5 w-3.5 text-[#14B8A6]" />;
      case 'lidar':
        return <Box className="h-3.5 w-3.5 text-purple-400" />;
      default:
        return <Folder className="h-3.5 w-3.5 text-muted-foreground" />;
    }
  };

  const filteredFiles = useMemo(() => {
    return files.filter((f) => {
      const matchesSearch = f.name.toLowerCase().includes(searchTerm.toLowerCase());
      if (!matchesSearch) return false;
      if (category === 'all') return true;
      return getFileCategory(f.name) === category;
    });
  }, [files, searchTerm, category]);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onUploadFiles(e.target.files);
    }
  };

  return (
    <aside className="w-full h-full flex flex-col bg-card border-r border-border select-none text-xs">
      {/* Catalog Header */}
      <div className="p-3 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-foreground">
          <Folder className="h-4 w-4 text-primary" />
          <span>Data Catalog</span>
          <span className="text-[10px] text-muted-foreground font-mono">({files.length})</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefreshFiles}
            className="p-1 rounded-none text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
            title="Refresh files"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <label className="p-1 rounded-none text-muted-foreground hover:text-primary hover:bg-muted cursor-pointer">
            <Upload className="h-3.5 w-3.5" />
            <input type="file" multiple className="hidden" onChange={handleFileInput} />
          </label>
        </div>
      </div>

      {/* Search Input */}
      <div className="p-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search datasets..."
            className="h-7 pl-8 text-xs bg-background border-border"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 mt-2">
          {(['all', 'raster', 'vector', 'lidar'] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={`px-2 py-0.5 rounded-none text-[10px] font-medium transition-colors cursor-pointer capitalize ${
                category === cat
                  ? 'bg-primary/15 text-primary border border-primary/40'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Selected Files & Clear All Action */}
        {selectedFiles.length > 0 && (
          <div className="flex items-center justify-between mt-2 pt-2 border-t border-border text-[#2DD4BF]">
            <span className="font-mono text-[10px] font-medium">
              {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''} selected
            </span>
            <button
              type="button"
              onClick={onClearSelectedFiles}
              className="flex items-center gap-1 text-[10px] font-semibold text-destructive hover:underline cursor-pointer bg-destructive/10 px-1.5 py-0.5 rounded-none border border-destructive/20"
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
          <div className="text-muted-foreground text-center py-8 text-[11px]">
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
                className={`flex items-center gap-2 p-2 rounded-none border cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-primary/15 border-primary/50 text-foreground'
                    : 'bg-background border-border text-foreground hover:border-primary/50'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => {}} // handled by parent div
                  className="rounded-none border-border bg-background text-primary focus:ring-0 cursor-pointer"
                />
                {getFileIcon(cat)}
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-[11px] truncate" title={f.name}>
                    {f.name}
                  </div>
                  <div className="text-[10px] text-muted-foreground font-mono">
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
                    className="p-1 rounded-none hover:bg-muted text-muted-foreground hover:text-primary transition-colors shrink-0"
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
        <div className="p-3 border-t border-border bg-card">
          <div className="flex items-center justify-between mb-2">
            <div>
              <div className="text-[10px] text-muted-foreground uppercase font-semibold">Active Container</div>
              <div className="font-mono text-[11px] text-foreground font-bold truncate">
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
                className="p-1 rounded-none text-muted-foreground hover:text-destructive hover:bg-destructive/10 cursor-pointer transition-colors"
                title="Delete workspace and free container slot"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {confirmDelete && (
            <div className="flex items-center gap-1.5 text-[10px] text-destructive bg-destructive/10 p-1.5 rounded-none border border-destructive/30">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              <span>Frees Docker container and clears workspace state.</span>
            </div>
          )}
        </div>
      )}
    </aside>
  );
};
