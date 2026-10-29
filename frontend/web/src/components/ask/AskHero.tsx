import { motion } from 'framer-motion';
import { CornerDownLeft } from 'lucide-react';
import type { RefObject } from 'react';

import { AskBox } from './AskBox';
import { QuestionBuilder } from './QuestionBuilder';
import { SUGGESTIONS, SuggestionChips } from './SuggestionChips';
import { TechnicalGrid } from '@/components/hero/TechnicalGrid';
import { Kbd } from '@/components/ui/Button';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface AskHeroProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onPickSuggestion: (question: string) => void;
  inputRef: RefObject<HTMLTextAreaElement>;
  disabled?: boolean;
}

const EASE = [0.22, 0.61, 0.36, 1] as const;

/**
 * The empty state: a centred stage, one question, four ways in.
 *
 * One focal point, and it is the headline. The eyebrow above it and the
 * standfirst below are set deliberately quieter — smaller, sans, and at muted
 * rather than full ink — so nothing on this screen competes with the sentence
 * the whole product is named after.
 */
export function AskHero({
  value,
  onChange,
  onSubmit,
  onPickSuggestion,
  inputRef,
  disabled = false,
}: AskHeroProps) {
  const reduced = useReducedMotion();
  const step = (index: number) => ({
    initial: reduced ? false : { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.55, delay: reduced ? 0 : index * 0.095, ease: EASE },
  });

  return (
    <div className="relative">
      <TechnicalGrid />

      <div className="relative mx-auto max-w-2xl px-1 pb-4 pt-12 text-center sm:pt-20">
        <motion.p
          {...step(0)}
          className="text-micro uppercase tracking-label text-ink-faint"
        >
          Decision intelligence
        </motion.p>

        <motion.h1
          {...step(1)}
          className="opsz-display mx-auto mt-7 max-w-xl text-balance font-serif text-[2.5rem] font-light leading-[1.06] tracking-[-0.028em] text-ink sm:text-[3.5rem]"
        >
          Ask your data anything.
        </motion.h1>

        {/* Sans, and deliberately smaller: the serif headline owns this stage. */}
        <motion.p
          {...step(2)}
          className="mx-auto mt-6 max-w-[30rem] text-balance text-[0.9375rem] leading-6 text-ink-muted"
        >
          Governed, read-only analysis of 100,000 Brazilian e-commerce orders.
          Every figure traces to a numbered claim and the SQL behind it.
        </motion.p>

        <motion.div {...step(3)} className="mt-10 text-left" data-tour="ask">
          <AskBox
            ref={inputRef}
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            disabled={disabled}
            examples={SUGGESTIONS}
            size="hero"
            voice
          />

          <div className="mt-3">
            <QuestionBuilder onAsk={onPickSuggestion} disabled={disabled} />
          </div>
        </motion.div>

        <motion.div {...step(4)} className="mt-8">
          <SuggestionChips onPick={onPickSuggestion} disabled={disabled} />
        </motion.div>

        <motion.div
          {...step(5)}
          className="mt-12 flex flex-wrap items-center justify-center gap-x-5 gap-y-3 text-[0.6875rem] text-ink-faint"
        >
          <span className="flex items-center gap-1.5">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <span className="ml-1">command palette</span>
          </span>
          <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
          <span className="flex items-center gap-1.5">
            <Kbd>
              <CornerDownLeft size={10} strokeWidth={1.5} aria-hidden />
            </Kbd>
            <span className="ml-1">ask</span>
          </span>
          <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
          <span className="flex items-center gap-1.5">
            <Kbd>?</Kbd>
            <span className="ml-1">shortcuts</span>
          </span>
          <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
          <span>Read-only · never computes a number</span>
        </motion.div>
      </div>
    </div>
  );
}
