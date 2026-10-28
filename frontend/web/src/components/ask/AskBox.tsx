import { forwardRef, useLayoutEffect, useRef, type KeyboardEvent } from 'react';
import { ArrowUp } from 'lucide-react';

import { Kbd } from '@/components/ui/Button';
import { cx } from '@/lib/cx';

interface AskBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
  /** The hero field is larger and set in serif; the docked one is compact. */
  size?: 'hero' | 'docked';
}

/**
 * One question field. Enter submits; Shift+Enter inserts a newline, because a
 * diagnostic question can run long and losing it to a stray Return is cruel.
 */
export const AskBox = forwardRef<HTMLTextAreaElement, AskBoxProps>(function AskBox(
  { value, onChange, onSubmit, disabled = false, placeholder, size = 'hero' },
  ref,
) {
  const inner = useRef<HTMLTextAreaElement | null>(null);
  const hero = size === 'hero';

  // Grow with the content instead of scrolling inside a fixed box.
  useLayoutEffect(() => {
    const node = inner.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${node.scrollHeight}px`;
  }, [value]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  const ready = value.trim().length > 0 && !disabled;

  return (
    <div
      className={cx(
        'group relative rounded-sm border bg-surface shadow-soft',
        'transition-colors duration-micro ease-editorial',
        'border-hairline-strong focus-within:border-gold',
        disabled && 'opacity-60',
      )}
    >
      <textarea
        ref={(node) => {
          inner.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
        rows={1}
        spellCheck
        aria-label="Ask your data a question"
        placeholder={placeholder ?? 'Ask your data anything…'}
        className={cx(
          'block w-full resize-none bg-transparent text-ink outline-none',
          'placeholder:text-ink-faint disabled:cursor-not-allowed',
          // The ring lives on the wrapper, so the inner field drops its own.
          'focus-visible:outline-none',
          hero
            ? 'px-6 pb-16 pt-6 font-serif text-[1.3125rem] leading-[1.9rem] sm:text-[1.5rem] sm:leading-[2.125rem]'
            : 'px-5 pb-12 pt-4 text-body',
        )}
      />

      <div
        className={cx(
          'pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-3',
          hero ? 'px-6 pb-5' : 'px-5 pb-3.5',
        )}
      >
        <span className="hidden items-center gap-1.5 text-[0.6875rem] text-ink-faint sm:flex">
          <Kbd>Enter</Kbd>
          <span>to ask</span>
          <span aria-hidden className="mx-1 h-2.5 w-px bg-hairline-strong" />
          <Kbd>⇧</Kbd>
          <Kbd>Enter</Kbd>
          <span>for a new line</span>
        </span>

        <button
          type="button"
          onClick={onSubmit}
          disabled={!ready}
          aria-label="Ask"
          className={cx(
            'pointer-events-auto ml-auto grid place-items-center rounded-sm transition-all duration-micro ease-editorial',
            hero ? 'h-10 w-10' : 'h-8 w-8',
            ready
              ? 'bg-gold text-on-gold hover:brightness-[1.06]'
              : 'border border-hairline bg-transparent text-ink-faint',
          )}
        >
          <ArrowUp size={hero ? 17 : 15} strokeWidth={2} aria-hidden />
        </button>
      </div>
    </div>
  );
});
