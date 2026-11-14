import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface AccordionProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
  children: React.ReactNode;
}

export const Accordion: React.FC<AccordionProps> = ({
  title,
  subtitle,
  badge,
  action,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  className,
  children,
}) => {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen);
  const isOpen = controlledOpen !== undefined ? controlledOpen : internalOpen;

  const toggle = () => {
    const next = !isOpen;
    if (controlledOpen === undefined) setInternalOpen(next);
    onOpenChange?.(next);
  };

  return (
    <div className={cn('rounded-lg border border-border bg-card/70 overflow-hidden', className)}>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={isOpen}
          className="flex flex-1 min-w-0 items-center gap-2 text-left cursor-pointer"
        >
          <ChevronDown
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150',
              isOpen && 'rotate-180'
            )}
          />
          <span className="truncate text-xs font-medium text-foreground">{title}</span>
          {subtitle && <span className="truncate text-[11px] text-muted-foreground">{subtitle}</span>}
        </button>
        <div className="flex items-center gap-2 shrink-0">
          {badge}
          {action}
        </div>
      </div>
      {isOpen && <div className="border-t border-border/70 px-3 py-2.5">{children}</div>}
    </div>
  );
};

