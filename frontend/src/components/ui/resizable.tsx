import * as React from 'react';
import { GripVertical, GripHorizontal } from 'lucide-react';
import * as ResizablePrimitive from 'react-resizable-panels';
import { cn } from '@/lib/utils';

const ResizablePanelGroup = ({
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelGroup>) => (
  <ResizablePrimitive.PanelGroup
    className={cn(
      'flex h-full w-full data-[panel-group-direction=vertical]:flex-col',
      className
    )}
    {...props}
  />
);

const ResizablePanel = ResizablePrimitive.Panel;

const ResizableHandle = ({
  withHandle,
  className,
  ...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelResizeHandle> & {
  withHandle?: boolean;
}) => (
  <ResizablePrimitive.PanelResizeHandle
    className={cn(
      'group relative flex items-center justify-center bg-border hover:bg-primary/70 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
      'w-1.5 cursor-col-resize data-[panel-group-direction=vertical]:h-2 data-[panel-group-direction=vertical]:w-full data-[panel-group-direction=vertical]:cursor-row-resize',
      className
    )}
    {...props}
  >
    {withHandle && (
      <>
        {/* Horizontal Split Grip (Vertical pill) */}
        <div className="z-10 flex h-6 w-3 items-center justify-center rounded-none border border-border bg-card group-hover:border-primary/50 group-data-[panel-group-direction=vertical]:hidden shadow-xs">
          <GripVertical className="h-3 w-3 text-muted-foreground group-hover:text-primary" />
        </div>

        {/* Vertical Split Grip (Horizontal pill slider) */}
        <div className="z-10 hidden group-data-[panel-group-direction=vertical]:flex h-2.5 w-12 items-center justify-center rounded-none border border-border bg-card group-hover:border-primary/50 shadow-xs">
          <GripHorizontal className="h-2.5 w-4 text-muted-foreground group-hover:text-primary" />
        </div>
      </>
    )}
  </ResizablePrimitive.PanelResizeHandle>
);

export { ResizablePanelGroup, ResizablePanel, ResizableHandle };
