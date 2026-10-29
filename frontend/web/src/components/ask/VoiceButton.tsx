import { Mic } from 'lucide-react';
import { useEffect } from 'react';

import { cx } from '@/lib/cx';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { useSpeech } from '@/hooks/useSpeech';
import { useToast } from '@/components/ui/Toast';

/**
 * Dictation.
 *
 * Rendered only where there is an engine behind it — `useSpeech` detects
 * support and this returns null otherwise, because a mic that cannot listen
 * should not be on the screen at all.
 *
 * While it listens, eleven hairline bars stand in for the signal. They are
 * *not* a visualisation of the audio: the Web Speech API gives no amplitude, so
 * drawing one would be an invented figure. They are a deliberate, regular
 * animation — an instrument's "listening" light, in the accent, on a fixed
 * cadence — and they draw flat under reduced motion.
 */

const BARS = 11;

export function VoiceButton({
  onTranscript,
  onSubmit,
  disabled = false,
}: {
  /** Called on every interim result, so the field fills as the reader speaks. */
  onTranscript: (text: string) => void;
  /** Called once the engine commits a final result. */
  onSubmit?: (text: string) => void;
  disabled?: boolean;
}) {
  const reduced = useReducedMotion();
  const toast = useToast();
  const speech = useSpeech((text) => onSubmit?.(text));

  // Stream interim results straight into the field.
  useEffect(() => {
    if (speech.transcript) onTranscript(speech.transcript);
    // onTranscript is a setter; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.transcript]);

  useEffect(() => {
    if (speech.error) toast.fault(speech.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.error]);

  if (!speech.supported) return null;

  return (
    <div className="pointer-events-auto flex items-center gap-2.5">
      {/* The waveform occupies its block whether listening or not, so starting
          dictation never shifts the controls beside it. */}
      <span
        aria-hidden
        className={cx(
          'flex h-4 items-center gap-[2px] transition-opacity duration-micro ease-editorial',
          speech.listening ? 'opacity-100' : 'w-0 opacity-0',
        )}
        style={speech.listening ? { width: `${BARS * 4}px` } : undefined}
      >
        {Array.from({ length: BARS }, (_, index) => (
          <span
            key={index}
            className={cx(
              'w-px rounded-full bg-accent',
              speech.listening && !reduced
                ? 'motion-safe:animate-[pulse-soft_1.1s_ease-in-out_infinite]'
                : '',
            )}
            style={{
              // A fixed, symmetrical profile — tallest at the centre — with a
              // staggered delay, so the figure reads as a steady instrument
              // rather than as a reading of anything.
              height: `${4 + Math.round(10 * Math.sin((Math.PI * (index + 1)) / (BARS + 1)))}px`,
              animationDelay: `${index * 85}ms`,
            }}
          />
        ))}
      </span>

      <button
        type="button"
        onClick={() => (speech.listening ? speech.stop() : speech.start())}
        disabled={disabled}
        aria-pressed={speech.listening}
        className={cx(
          'grid h-8 w-8 place-items-center rounded-sm border',
          'transition-colors duration-hover ease-editorial',
          'disabled:cursor-not-allowed disabled:opacity-45',
          speech.listening
            ? 'border-accent bg-[var(--c-accent-wash)] text-accent-ink'
            : 'border-hairline text-ink-faint hover:border-hairline-strong hover:text-ink',
        )}
      >
        <Mic size={14} strokeWidth={1.5} aria-hidden />
        <span className="sr-only">
          {speech.listening ? 'Stop dictating' : 'Dictate the question'}
        </span>
      </button>
    </div>
  );
}
