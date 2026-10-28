import { motion } from 'framer-motion';
import { CornerDownLeft } from 'lucide-react';
import type { RefObject } from 'react';

import { AskBox } from './AskBox';
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

/** The empty state: a centred stage, one question, four ways in. */
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
    initial: reduced ? false : { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.6, delay: reduced ? 0 : index * 0.1, ease: EASE },
  });

  return (
    <div className="relative">
      <TechnicalGrid />

      <div className="relative mx-auto max-w-2xl px-1 pb-4 pt-10 text-center sm:pt-16">
        <motion.p
          {...step(0)}
          className="text-micro uppercase tracking-label text-ink-faint"
        >
          Decision intelligence
        </motion.p>

        <motion.h1
          {...step(1)}
          className="mx-auto mt-6 max-w-xl text-balance font-serif text-[2.5rem] leading-[1.08] tracking-[-0.022em] text-ink sm:text-[3.5rem]"
        >
          Ask your data anything.
        </motion.h1>

        {/* Sans, and deliberately smaller: the serif headline owns this stage. */}
        <motion.p
          {...step(2)}
          className="mx-auto mt-5 max-w-[30rem] text-balance text-[0.9375rem] leading-[1.6] text-ink-muted"
        >
          Governed, read-only analysis of 100,000 Brazilian e-commerce orders. Every
          figure traces to a numbered claim and the SQL behind it.
        </motion.p>

        <motion.div {...step(3)} className="mt-10 text-left">
          <AskBox
            ref={inputRef}
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            disabled={disabled}
            examples={SUGGESTIONS}
            size="hero"
          />
        </motion.div>

        <motion.div {...step(4)} className="mt-7">
          <SuggestionChips onPick={onPickSuggestion} disabled={disabled} />
        </motion.div>

        <motion.div
          {...step(5)}
          className="mt-10 flex flex-wrap items-center justify-center gap-x-5 gap-y-2.5 text-[0.6875rem] text-ink-faint"
        >
          <span className="flex items-center gap-1.5">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <span className="ml-1">command palette</span>
          </span>
          <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
          <span className="flex items-center gap-1.5">
            <Kbd>
              <CornerDownLeft size={10} strokeWidth={2} aria-hidden />
            </Kbd>
            <span className="ml-1">ask</span>
          </span>
          <span aria-hidden className="h-2.5 w-px bg-hairline-strong" />
          <span>Read-only · never computes a number</span>
        </motion.div>
      </div>
    </div>
  );
}
