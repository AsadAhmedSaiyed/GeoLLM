import * as React from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from './button';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  headerActions?: React.ReactNode;
  maxWidthClass?: string;
  className?: string;
  children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  headerActions,
  maxWidthClass = 'max-w-5xl',
  className,
  children,
}) => {
  React.useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'flex max-h-[90vh] w-full flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-2xl',
          maxWidthClass,
          className
        )}
      >
        {(title || headerActions) && (
          <div className="flex items-center justify-between gap-3 border-b border-border bg-background/60 px-4 py-3">
            <div className="min-w-0">
              {title && <div className="truncate text-sm font-semibold text-foreground">{title}</div>}
              {subtitle && <div className="truncate text-[11px] text-muted-foreground">{subtitle}</div>}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {headerActions}
              <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Close modal">
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
};

