import { motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';

import { StageNode } from './StageNode';
import { Card, SectionLabel } from '@/components/ui/Card';
import { cx } from '@/lib/cx';
import { formatDuration } from '@/lib/format';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import type { StageProgress } from '@/lib/stages';
import type { RunPhase } from '@/lib/runState';

interface PipelineTrackProps {
  stages: readonly StageProgress[];
  phase: RunPhase;
  reconnecting: boolean;
}

/** A thin gold line, drawn only between stages that have both finished. */
function Connector({ lit }: { lit: boolean }) {
  const reduced = useReducedMotion();
  return (
    <div aria-hidden className="relative mt-[0.6875rem] h-px flex-1 bg-hairline">
      <motion.div
        className="absolute inset-y-0 left-0 bg-gold"
        initial={reduced ? { width: lit ? '100%' : 0 } : { width: 0 }}
        animate={{ width: lit ? '100%' : 0 }}
        transition={{ duration: reduced ? 0 : 0.6, ease: [0.22, 0.61, 0.36, 1] }}
      />
    </div>
  );
}

export function PipelineTrack({ stages, phase, reconnecting }: PipelineTrackProps) {
  if (stages.length === 0) return null;

  const done = stages.filter((stage) => stage.state === 'ok' || stage.state === 'failed');
  const elapsed = done.reduce((total, stage) => total + (stage.durationMs ?? 0), 0);
  const active = phase === 'submitting' || phase === 'streaming' || phase === 'fetching';

  return (
    <Card tone="flat" className="p-5 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <SectionLabel>
          {active ? 'Running' : 'Pipeline'}
          <span aria-hidden className="mx-2 text-ink-faint/50">
            ·
          </span>
          <span className="normal-case tracking-normal">
            {done.length} of {stages.length} stages
          </span>
        </SectionLabel>

        <div className="flex items-center gap-3">
          {reconnecting ? (
            <span className="flex items-center gap-1.5 text-[0.6875rem] text-gold">
              <Loader2 size={11} className="animate-spin" aria-hidden />
              reconnecting
            </span>
          ) : null}
          {phase === 'fetching' ? (
            <span className="text-[0.6875rem] text-ink-faint">collecting the answer…</span>
          ) : null}
          <span className="font-mono text-[0.6875rem] tabular-nums text-ink-faint">
            {formatDuration(elapsed)}
          </span>
        </div>
      </div>

      {/* Horizontal track from `sm` up. */}
      <div
        role="list"
        aria-label="Pipeline stages"
        className="mt-6 hidden items-start sm:flex"
      >
        {stages.map((stage, index) => {
          const next = stages[index + 1];
          const settled = (candidate?: StageProgress) =>
            candidate?.state === 'ok' || candidate?.state === 'failed';
          return (
            <div key={stage.definition.step} role="listitem" className="flex min-w-0 flex-1">
              <StageNode stage={stage} orientation="horizontal" />
              {next ? <Connector lit={settled(stage) && settled(next)} /> : null}
            </div>
          );
        })}
      </div>

      {/* Stacked below `sm`, where seven nodes cannot read horizontally. */}
      <div
        role="list"
        aria-label="Pipeline stages"
        className={cx('mt-5 space-y-4 sm:hidden')}
      >
        {stages.map((stage) => (
          <div key={stage.definition.step} role="listitem">
            <StageNode stage={stage} orientation="vertical" />
          </div>
        ))}
      </div>
    </Card>
  );
}
