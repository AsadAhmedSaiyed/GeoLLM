import * as React from 'react';
import { cn } from '@/lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'teal' | 'running' | 'success' | 'warning';
}

function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  const variants: Record<string, string> = {
    default: 'border-transparent bg-primary text-primary-foreground',
    secondary: 'border-transparent bg-secondary text-secondary-foreground',
    destructive: 'border-transparent bg-destructive text-destructive-foreground',
    outline: 'text-foreground border-border',
    teal: 'border-transparent bg-[#0F766E]/20 text-[#2DD4BF] border border-[#0F766E]/40',
    running: 'border-transparent bg-sky-500/20 text-sky-400 border border-sky-500/40 pulsing-glow',
    success: 'border-transparent bg-emerald-500/20 text-emerald-400 border border-emerald-500/40',
    warning: 'border-transparent bg-amber-500/20 text-amber-400 border border-amber-500/40',
  };

  return (
    <div
      className={cn(
        'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
        variants[variant] || variants.default,
        className
      )}
      {...props}
    />
  );
}

export { Badge };

