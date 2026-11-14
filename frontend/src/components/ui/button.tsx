import * as React from 'react';
import { cn } from '@/lib/utils';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link' | 'teal' | 'primary';
  size?: 'default' | 'sm' | 'lg' | 'icon';
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'default', ...props }, ref) => {
    const variants: Record<string, string> = {
      default: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-xs',
      primary: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-xs',
      destructive: 'bg-destructive/15 text-destructive hover:bg-destructive/25 border border-destructive/20',
      outline: 'border border-border bg-background hover:bg-muted hover:text-foreground',
      secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
      ghost: 'hover:bg-muted hover:text-foreground',
      link: 'text-sky-400 underline-offset-4 hover:underline',
      teal: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-xs',
    };

    const sizes: Record<string, string> = {
      default: 'h-8 px-3 text-xs',
      sm: 'h-7 px-2.5 text-xs',
      lg: 'h-9 px-4 text-sm',
      icon: 'h-8 w-8 p-0',
    };

    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-all outline-none select-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
          variants[variant] || variants.default,
          sizes[size] || sizes.default,
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';

export { Button };
