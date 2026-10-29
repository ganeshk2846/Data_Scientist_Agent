import {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { ArrowUp } from 'lucide-react';

import { VoiceButton } from './VoiceButton';
import { Kbd } from '@/components/ui/Button';
import { cx } from '@/lib/cx';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSheen } from '@/hooks/useSheen';

interface AskBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
  /** Rotating example questions, shown as the placeholder while empty. */
  examples?: readonly string[];
  /** The hero field sits on a plinth; the docked one is compact. */
  size?: 'hero' | 'docked';
  /** Offers dictation, where the browser has an engine for it. */
  voice?: boolean;
}

/**
 * The question field.
 *
 * Enter submits; Shift+Enter inserts a newline, because a diagnostic question
 * can run long and losing it to a stray Return is cruel.
 *
 * The hero variant sits on a glass plinth whose thin accent border *traces
 * itself* on focus: two SVG rects share one path length, and the top one's
 * dash offset animates from full to zero, so the light appears to run around
 * the edge. It is a 600ms detail nobody will name but everybody will feel.
 */
export const AskBox = forwardRef<HTMLTextAreaElement, AskBoxProps>(function AskBox(
  {
    value,
    onChange,
    onSubmit,
    disabled = false,
    placeholder,
    examples,
    size = 'hero',
    voice = false,
  },
  ref,
) {
  const inner = useRef<HTMLTextAreaElement | null>(null);
  const hero = size === 'hero';
  const reduced = useReducedMotion();
  const sheenRef = useSheen<HTMLDivElement>(hero && !reduced);
  const [focused, setFocused] = useState(false);
  const [exampleIndex, setExampleIndex] = useState(0);

  // Grow with the content instead of scrolling inside a fixed box.
  useLayoutEffect(() => {
    const node = inner.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${node.scrollHeight}px`;
  }, [value]);

  // Rotate the example placeholder, but never while the field is in use.
  useEffect(() => {
    if (!examples || examples.length < 2) return;
    if (value || focused || reduced) return;
    const timer = window.setInterval(
      () => setExampleIndex((index) => (index + 1) % examples.length),
      4200,
    );
    return () => window.clearInterval(timer);
  }, [examples, value, focused, reduced]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  const ready = value.trim().length > 0 && !disabled;
  const shownPlaceholder =
    placeholder ?? (examples?.[exampleIndex] ?? 'Ask your data anything…');

  return (
    <div
      ref={sheenRef}
      className={cx(
        'group relative rounded-sm',
        hero
          ? // The plinth: a glass slab the field rests on.
            'edge-accent sheen border border-hairline-strong bg-[rgb(var(--c-surface)/0.82)] shadow-lifted backdrop-blur-xl'
          : 'border border-hairline-strong bg-surface shadow-soft',
        'transition-[border-color,box-shadow] duration-micro ease-editorial',
        focused && 'border-accent',
        disabled && 'bg-sunken',
      )}
    >
      {/* The tracing accent border. Decorative, so it never reaches the a11y tree. */}
      {hero ? (
        <svg
          aria-hidden
          className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
          preserveAspectRatio="none"
        >
          <rect
            x="0.5"
            y="0.5"
            width="calc(100% - 1px)"
            height="calc(100% - 1px)"
            rx="2.5"
            fill="none"
            stroke="rgb(var(--c-accent))"
            strokeWidth="1"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={focused ? 0 : 1}
            style={{
              transition: reduced
                ? 'none'
                : 'stroke-dashoffset 600ms cubic-bezier(0.22,0.61,0.36,1)',
            }}
          />
        </svg>
      ) : null}

      <textarea
        ref={(node) => {
          inner.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        disabled={disabled}
        rows={1}
        spellCheck
        aria-label="Ask your data a question"
        placeholder={shownPlaceholder}
        className={cx(
          'relative block w-full resize-none bg-transparent text-ink outline-none',
          'placeholder:text-ink-faint disabled:cursor-not-allowed',
          // The ring lives on the plinth, so the inner field drops its own.
          'focus-visible:outline-none',
          // The placeholder must never read as text the user already typed:
          // it sits well below body contrast and drops the serif entirely.
          'placeholder:font-sans placeholder:text-[0.9375rem] placeholder:leading-normal',
          'placeholder:text-[rgb(var(--c-ink-faint)/0.85)]',
          hero
            ? 'px-6 pb-12 pt-6 font-serif text-[1.25rem] leading-[1.8rem] sm:text-[1.375rem] sm:leading-[2rem]'
            : 'px-5 pb-11 pt-4 text-body',
        )}
      />

      <div
        className={cx(
          'pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-3',
          hero ? 'px-6 pb-4' : 'px-5 pb-3.5',
        )}
      >
        <span
          className={cx(
            'items-center gap-1.5 text-[0.625rem] text-ink-faint',
            disabled ? 'hidden' : 'hidden sm:flex',
          )}
        >
          <Kbd>Enter</Kbd>
          <span>to ask</span>
          <span aria-hidden className="mx-1 h-2.5 w-px bg-hairline-strong" />
          <Kbd>⇧</Kbd>
          <Kbd>Enter</Kbd>
          <span>new line</span>
        </span>

        {voice ? (
          <span className="ml-auto mr-1">
            <VoiceButton
              onTranscript={onChange}
              onSubmit={() => onSubmit()}
              disabled={disabled}
            />
          </span>
        ) : null}

        <button
          type="button"
          onClick={onSubmit}
          disabled={!ready}
          aria-label="Ask"
          className={cx(
            'pointer-events-auto grid place-items-center rounded-sm',
            voice ? '' : 'ml-auto',
            'transition-all duration-micro ease-editorial',
            hero ? 'h-10 w-10' : 'h-8 w-8',
            ready
              ? 'bg-accent text-on-accent shadow-soft hover:brightness-[1.06]'
              : 'border border-hairline bg-transparent text-ink-faint',
          )}
        >
          <ArrowUp size={hero ? 17 : 15} strokeWidth={1.5} aria-hidden />
        </button>
      </div>
    </div>
  );
});
