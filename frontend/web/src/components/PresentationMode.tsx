import { motion } from 'framer-motion';
import { X } from 'lucide-react';

import { Briefing } from '@/components/briefing/Briefing';
import { Kbd } from '@/components/ui/Button';
import { useEscape } from '@/hooks/useHotkeys';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope } from '@/types/envelope';

/**
 * Presentation mode: the briefing alone, large and centred, with the chrome
 * gone. For putting on a screen in front of other people.
 *
 * It renders the same `Briefing` component rather than a parallel layout, so
 * there is exactly one place the answer is designed.
 */
export function PresentationMode({
  envelope,
  question,
  theme,
  onClose,
}: {
  envelope: AnswerEnvelope;
  question: string | null;
  theme: ResolvedTheme;
  onClose: () => void;
}) {
  const reduced = useReducedMotion();
  useEscape(true, onClose);

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label="Presentation"
      initial={reduced ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.45, ease: [0.22, 0.61, 0.36, 1] }}
      className="paper-grain fixed inset-0 z-50 overflow-y-auto bg-bg"
    >
      <div className="relative z-10">
        {/* The only chrome: a way out. */}
        <div
          data-print="hide"
          className="pointer-events-none sticky top-0 flex items-start justify-end px-5 pt-5 sm:px-8"
        >
          <button
            type="button"
            onClick={onClose}
            className="pointer-events-auto flex items-center gap-2.5 rounded-[3px] border border-hairline bg-[rgb(var(--c-surface)/0.8)] px-3 py-1.5 text-[0.75rem] text-ink-muted backdrop-blur-md transition-colors duration-micro hover:border-gold hover:text-ink"
          >
            <X size={12} strokeWidth={1.75} aria-hidden />
            Exit
            <Kbd>Esc</Kbd>
          </button>
        </div>

        <div className="mx-auto w-full max-w-4xl px-6 pb-24 pt-4 sm:px-10">
          {question ? (
            <header className="mb-12">
              <p className="text-micro uppercase tracking-label text-ink-faint">
                Question
              </p>
              <h1 className="mt-4 max-w-3xl font-serif text-[2rem] leading-[1.2] tracking-[-0.015em] text-ink sm:text-[2.75rem]">
                {question}
              </h1>
            </header>
          ) : null}

          <Briefing
            envelope={envelope}
            theme={theme}
            question={question}
            onAsk={() => {}}
            onPresent={() => {}}
            presenting
          />
        </div>
      </div>
    </motion.div>
  );
}
