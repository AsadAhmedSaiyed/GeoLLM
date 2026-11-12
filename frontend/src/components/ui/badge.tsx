import * as React from 'react';
import { cn } from '@/lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'teal' | 'running' | 'success' | 'warning';
}

function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  const variants: Record<string, string> = {
    default: 'border-transparent bg-primary text-primary-foreground',
    secondary: 'border-transparent bg-secondary text-secondary-foreground',
    destructive: 'border-destructive/30 bg-destructive/15 text-destructive',
    outline: 'text-foreground border-border',
    teal: 'border-[#0F766E]/40 bg-[#0F766E]/15 text-[#2DD4BF]',
    running: 'border-sky-500/40 bg-sky-500/15 text-sky-400 pulsing-glow',
    success: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-400',
    warning: 'border-amber-500/40 bg-amber-500/15 text-amber-400',
  };

  return (
    <div
      className={cn(
        'inline-flex items-center rounded-none border px-2 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
        variants[variant] || variants.default,
        className
      )}
      {...props}
    />
  );
}

export { Badge };
