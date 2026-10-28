import { motion } from 'framer-motion';
import type { RefObject } from 'react';

import { AskBox } from './AskBox';
import { SuggestionChips } from './SuggestionChips';
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

/** The empty state: one large question field and four ways in. */
export function AskHero({
  value,
  onChange,
  onSubmit,
  onPickSuggestion,
  inputRef,
  disabled = false,
}: AskHeroProps) {
  const reduced = useReducedMotion();

  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: [0.22, 0.61, 0.36, 1] }}
      className="mx-auto max-w-3xl pt-6 sm:pt-16"
    >
      <p className="text-micro uppercase text-ink-faint">Decision intelligence</p>
      <h1 className="mt-5 text-h1 text-ink sm:text-display">Ask your data anything.</h1>
      <p className="mt-5 max-w-prose font-serif text-body-serif font-light text-ink-muted">
        Governed, read-only analysis of 100,000 Brazilian e-commerce orders. Every
        figure in every answer traces back to a numbered claim and the SQL that
        produced it.
      </p>

      <div className="mt-10">
        <AskBox
          ref={inputRef}
          value={value}
          onChange={onChange}
          onSubmit={onSubmit}
          disabled={disabled}
          size="hero"
        />
      </div>

      <div className="mt-8">
        <p className="text-micro uppercase text-ink-faint">Try one of these</p>
        <div className="mt-4">
          <SuggestionChips onPick={onPickSuggestion} disabled={disabled} />
        </div>
      </div>

      <p className="mt-10 flex items-center gap-1.5 text-[0.6875rem] text-ink-faint">
        <Kbd>⌘</Kbd>
        <Kbd>K</Kbd>
        <span className="ml-1">focuses this field from anywhere</span>
      </p>
    </motion.div>
  );
}
