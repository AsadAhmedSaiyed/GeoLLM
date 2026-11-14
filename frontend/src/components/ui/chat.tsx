import * as React from 'react';
import { cn } from '@/lib/utils';

type ChatDensity = 'compact' | 'balanced' | 'spacious';
type ChatSender = 'user' | 'assistant';

const ChatSenderContext = React.createContext<ChatSender>('assistant');
const ChatDensityContext = React.createContext<ChatDensity>('balanced');

export interface ChatLayoutProps extends React.HTMLAttributes<HTMLDivElement> {
  density?: ChatDensity;
}

export const ChatLayout = React.forwardRef<HTMLDivElement, ChatLayoutProps>(
  ({ density = 'balanced', className, children, ...props }, ref) => (
    <ChatDensityContext.Provider value={density}>
      <div
        ref={ref}
        className={cn('flex h-full w-full flex-col min-h-0 bg-background text-foreground', className)}
        {...props}
      >
        {children}
      </div>
    </ChatDensityContext.Provider>
  )
);
ChatLayout.displayName = 'ChatLayout';

export interface ChatMessageListProps extends React.HTMLAttributes<HTMLDivElement> {
  density?: ChatDensity;
}

export const ChatMessageList = React.forwardRef<HTMLDivElement, ChatMessageListProps>(
  ({ density, className, children, ...props }, ref) => {
    const ctxDensity = React.useContext(ChatDensityContext);
    const activeDensity = density ?? ctxDensity;
    const spacingClass =
      activeDensity === 'compact'
        ? 'gap-2.5 px-3 py-3'
        : activeDensity === 'spacious'
          ? 'gap-5 px-5 py-5'
          : 'gap-3.5 px-4 py-4';

    return (
      <div
        ref={ref}
        role="log"
        aria-live="polite"
        className={cn('flex flex-1 min-h-0 flex-col overflow-y-auto', spacingClass, className)}
        {...props}
      >
        {children}
      </div>
    );
  }
);
ChatMessageList.displayName = 'ChatMessageList';

export interface ChatMessageProps extends React.HTMLAttributes<HTMLDivElement> {
  sender: ChatSender;
}

export const ChatMessage = React.forwardRef<HTMLDivElement, ChatMessageProps>(
  ({ sender, className, children, ...props }, ref) => (
    <ChatSenderContext.Provider value={sender}>
      <div
        ref={ref}
        data-sender={sender}
        className={cn(
          'flex w-full flex-col',
          sender === 'user' ? 'items-end' : 'items-start',
          className
        )}
        {...props}
      >
        {children}
      </div>
    </ChatSenderContext.Provider>
  )
);
ChatMessage.displayName = 'ChatMessage';

export interface ChatMessageBubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'ghost';
  group?: 'single' | 'first' | 'middle' | 'last';
  metadata?: React.ReactNode;
}

export const ChatMessageBubble = React.forwardRef<HTMLDivElement, ChatMessageBubbleProps>(
  ({ variant = 'default', group = 'single', metadata, className, children, ...props }, ref) => {
    const sender = React.useContext(ChatSenderContext);

    const userRadius =
      group === 'first'
        ? 'rounded-2xl rounded-br-md'
        : group === 'middle'
          ? 'rounded-2xl rounded-r-md'
          : group === 'last'
            ? 'rounded-2xl rounded-tr-md'
            : 'rounded-2xl rounded-br-sm';

    const surfaceClass =
      variant === 'ghost'
        ? 'bg-transparent border-0 px-0 py-1 text-foreground w-full'
        : sender === 'user'
          ? cn('bg-secondary text-secondary-foreground w-fit px-4 py-2.5 max-w-[82%] text-left break-words shadow-xs', userRadius)
          : 'bg-card text-card-foreground border border-border rounded-2xl rounded-bl-sm w-fit px-4 py-2.5 max-w-[90%] text-left break-words';

    return (
      <div
        ref={ref}
        className={cn(
          'flex w-full flex-col gap-1 text-[13px] leading-relaxed',
          sender === 'user' ? 'items-end' : 'items-start',
          className
        )}
      >
        <div className={cn(surfaceClass)} {...props}>
          {children}
        </div>
        {metadata && <div className="w-full">{metadata}</div>}
      </div>
    );
  }
);
ChatMessageBubble.displayName = 'ChatMessageBubble';

export interface ChatMessageMetadataProps extends React.HTMLAttributes<HTMLDivElement> {
  timestamp?: React.ReactNode;
  status?: React.ReactNode;
}

export const ChatMessageMetadata = React.forwardRef<HTMLDivElement, ChatMessageMetadataProps>(
  ({ timestamp, status, className, children, ...props }, ref) => {
    const sender = React.useContext(ChatSenderContext);
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground',
          sender === 'user' ? 'justify-end' : 'justify-start',
          className
        )}
        {...props}
      >
        {children}
        {timestamp}
        {status && <span className="capitalize">{status}</span>}
      </div>
    );
  }
);
ChatMessageMetadata.displayName = 'ChatMessageMetadata';

export interface ChatSystemMessageProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'divider' | 'status';
}

export const ChatSystemMessage = React.forwardRef<HTMLDivElement, ChatSystemMessageProps>(
  ({ variant = 'status', className, children, ...props }, ref) => {
    if (variant === 'divider') {
      return (
        <div
          ref={ref}
          className={cn('my-1 flex items-center gap-3 text-[11px] text-muted-foreground', className)}
          {...props}
        >
          <span className="h-px flex-1 bg-border" />
          <span className="shrink-0 font-medium">{children}</span>
          <span className="h-px flex-1 bg-border" />
        </div>
      );
    }

    return (
      <div
        ref={ref}
        className={cn(
          'mx-auto my-1 inline-flex items-center gap-2 rounded-full border border-border bg-muted/60 px-3 py-1 text-[11px] text-muted-foreground',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
ChatSystemMessage.displayName = 'ChatSystemMessage';

export interface TimestampProps extends React.HTMLAttributes<HTMLTimeElement> {
  value?: number | string | Date;
  format?: 'time' | 'datetime';
}

export const Timestamp: React.FC<TimestampProps> = ({ value, format = 'time', className, ...props }) => {
  if (value === undefined || value === null || value === '') return null;
  const ms = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : new Date(value).getTime();
  if (Number.isNaN(ms)) return null;
  const date = new Date(ms);
  const label =
    format === 'datetime'
      ? date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <time dateTime={date.toISOString()} className={cn('tabular-nums text-[11px] text-muted-foreground', className)} {...props}>
      {label}
    </time>
  );
};

export interface ChatComposerProps extends React.FormHTMLAttributes<HTMLFormElement> {
  drawer?: React.ReactNode;
  header?: React.ReactNode;
  footer?: React.ReactNode;
}

export const ChatComposer = React.forwardRef<HTMLFormElement, ChatComposerProps>(
  ({ drawer, header, footer, className, children, ...props }, ref) => (
    <form
      ref={ref}
      className={cn('shrink-0 border-t border-border bg-background/95 p-3 backdrop-blur-md', className)}
      {...props}
    >
      {drawer && <div className="mb-2">{drawer}</div>}
      <div className="rounded-xl border border-input bg-card/80 transition-colors focus-within:border-ring focus-within:ring-1 focus-within:ring-ring">
        {header && <div className="border-b border-border/60 px-3 py-1.5">{header}</div>}
        <div className="px-3 pt-2.5 pb-1.5">{children}</div>
        {footer && <div className="flex items-center justify-between gap-2 px-2.5 pb-2 pt-1">{footer}</div>}
      </div>
    </form>
  )
);
ChatComposer.displayName = 'ChatComposer';

export const ChatComposerDrawer: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div
    className={cn(
      'flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/50 px-2.5 py-1.5 text-xs',
      className
    )}
    {...props}
  >
    {children}
  </div>
);

export type ChatComposerInputProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const ChatComposerInput = React.forwardRef<HTMLTextAreaElement, ChatComposerInputProps>(
  ({ className, value, onChange, ...props }, ref) => {
    const innerRef = React.useRef<HTMLTextAreaElement | null>(null);

    const setRefs = React.useCallback(
      (node: HTMLTextAreaElement | null) => {
        innerRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = node;
      },
      [ref]
    );

    React.useEffect(() => {
      const el = innerRef.current;
      if (!el) return;
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
    }, [value]);

    return (
      <textarea
        ref={setRefs}
        rows={1}
        value={value}
        onChange={onChange}
        className={cn(
          'w-full min-h-[38px] max-h-[180px] resize-none overflow-y-auto bg-transparent text-[13px] leading-relaxed text-foreground placeholder:text-muted-foreground focus:outline-none',
          className
        )}
        {...props}
      />
    );
  }
);
ChatComposerInput.displayName = 'ChatComposerInput';

