import React, { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FileUploadModal } from '@/components/FileUploadModal';
import {
  ChatComposer,
  ChatComposerDrawer,
  ChatComposerInput,
} from '@/components/ui/chat';
import {
  Send,
  X,
  Satellite,
  Loader2,
  AlertCircle,
  Paperclip,
  Eye,
  FileImage,
  Box,
  FileCode,
} from 'lucide-react';

interface QueryConsoleProps {
  selectedFiles: string[];
  onRemoveFile: (fileName: string) => void;
  onClearAllFiles?: () => void;
  onUploadFiles?: (files: FileList) => Promise<void> | void;
  onPreviewFile?: (fileName: string) => void;
  onSubmit: (question: string) => void;
  isSubmitting: boolean;
  isRunning?: boolean;
  hasActiveWorkspace: boolean;
  injectedPrompt?: string | null;
  onInjectedPromptConsumed?: () => void;
}

export const QueryConsole: React.FC<QueryConsoleProps> = ({
  selectedFiles,
  onRemoveFile,
  onClearAllFiles,
  onUploadFiles,
  onPreviewFile,
  onSubmit,
  isSubmitting,
  isRunning = false,
  hasActiveWorkspace,
  injectedPrompt,
  onInjectedPromptConsumed,
}) => {
  const [question, setQuestion] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !onUploadFiles) return;
    setIsUploading(true);
    try {
      await onUploadFiles(files);
    } finally {
      setIsUploading(false);
      e.target.value = '';
    }
  };

  useEffect(() => {
    if (injectedPrompt) {
      setQuestion((prev) =>
        prev.trim() ? `${prev.trim()} ${injectedPrompt}` : injectedPrompt
      );
      onInjectedPromptConsumed?.();
    }
  }, [injectedPrompt, onInjectedPromptConsumed]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!hasActiveWorkspace || !question.trim() || isSubmitting) return;
    const q = question.trim();
    setQuestion('');
    onSubmit(q);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const drawerNode =
    selectedFiles.length > 0 ? (
      <ChatComposerDrawer>
        <span className="text-[11px] font-medium text-muted-foreground mr-1">
          Attached ({selectedFiles.length}):
        </span>
        {selectedFiles.map((f) => {
          const isTif = /\.(tif|tiff)$/i.test(f);
          const isLidar = /\.(laz|las)$/i.test(f);
          const isVector = /\.(geojson|shp|kml|gpkg)$/i.test(f);
          const isImage = /\.(png|jpg|jpeg|webp)$/i.test(f);

          return (
            <Badge
              key={f}
              variant="secondary"
              className="gap-1.5 pl-1.5 pr-1 py-1 font-normal bg-card/90 border border-border hover:border-sky-400/60 transition-colors shadow-sm"
            >
              {isTif && <FileImage className="h-3.5 w-3.5 text-sky-400 shrink-0" />}
              {isLidar && <Box className="h-3.5 w-3.5 text-purple-400 shrink-0" />}
              {isVector && <FileCode className="h-3.5 w-3.5 text-teal-400 shrink-0" />}
              {isImage && <FileImage className="h-3.5 w-3.5 text-emerald-400 shrink-0" />}

              <span
                onClick={() => onPreviewFile?.(f)}
                className="max-w-[160px] truncate cursor-pointer hover:text-sky-400 font-mono text-[11px] transition-colors"
                title={`Click to preview ${f}`}
              >
                {f}
              </span>

              {onPreviewFile && (
                <button
                  type="button"
                  onClick={() => onPreviewFile(f)}
                  title={`Preview ${f}`}
                  className="rounded p-0.5 text-muted-foreground hover:text-sky-400 hover:bg-muted transition-colors cursor-pointer"
                >
                  <Eye className="h-3 w-3" />
                </button>
              )}

              <button
                type="button"
                onClick={() => onRemoveFile(f)}
                className="rounded-full p-0.5 hover:bg-background/60 cursor-pointer"
                aria-label={`Remove ${f}`}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          );
        })}
        {selectedFiles.length > 1 && onClearAllFiles && (
          <button
            type="button"
            onClick={onClearAllFiles}
            className="ml-auto text-[11px] text-muted-foreground hover:text-foreground cursor-pointer"
          >
            Clear all
          </button>
        )}
      </ChatComposerDrawer>
    ) : undefined;

  const headerNode = !hasActiveWorkspace ? (
    <div className="flex items-center gap-1.5 text-[11px] text-amber-400">
      <AlertCircle className="h-3.5 w-3.5 shrink-0" />
      <span>Select or create a workspace (+ New) to start chatting.</span>
    </div>
  ) : isRunning ? (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <span className="h-2 w-2 rounded-full bg-primary animate-pulse shrink-0" />
      <span>Sub-agent active in container · You can still ask questions or inspect outputs</span>
    </div>
  ) : undefined;

  const footerNode = (
    <>
      <div className="flex items-center gap-1.5 min-w-0">
        {onUploadFiles && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".tif,.tiff,.nc,.h5,.he5,.hdr,.img,.bsq,.bil,.bip,.laz,.las,.geojson,.json,.zip,.shp,.gpkg,.csv,.png,.jpg,.jpeg"
              className="hidden"
              onChange={handleFileChange}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!hasActiveWorkspace || isUploading}
              onClick={() => setIsUploadModalOpen(true)}
              title="Attach & preview input files (GeoTIFF, LAZ, GeoJSON, imagery)"
              className="h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            >
              {isUploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Paperclip className="h-3.5 w-3.5" />
              )}
              <span>{isUploading ? 'Uploading…' : 'Attach'}</span>
            </Button>
          </>
        )}
        {hasActiveWorkspace && selectedFiles.length === 0 && (
          <span className="hidden sm:inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <Satellite className="h-3 w-3" />
            Autonomous STAC ready
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <span className="hidden md:inline text-[10px] text-muted-foreground">
          Enter to send · Shift+Enter newline
        </span>
        <Button
          type="submit"
          size="sm"
          disabled={!hasActiveWorkspace || !question.trim() || isSubmitting}
          className="h-7 rounded-lg px-3 gap-1.5"
        >
          {isSubmitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
          <span>{isSubmitting ? 'Sending…' : 'Send'}</span>
        </Button>
      </div>
    </>
  );

  return (
    <>
      <ChatComposer
        onSubmit={handleSubmit}
        drawer={drawerNode}
        header={headerNode}
        footer={footerNode}
      >
        <ChatComposerInput
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!hasActiveWorkspace}
          placeholder={
            hasActiveWorkspace
              ? 'Ask GeoLLM, inspect outputs, or run a spatial analysis…'
              : 'Create or select a workspace to start…'
          }
        />
      </ChatComposer>

      {onUploadFiles && (
        <FileUploadModal
          isOpen={isUploadModalOpen}
          onClose={() => setIsUploadModalOpen(false)}
          onUpload={onUploadFiles}
        />
      )}
    </>
  );
};
