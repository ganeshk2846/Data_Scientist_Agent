import { Suspense, lazy } from 'react';

import { Card } from '@/components/ui/Card';
import { SkeletonBlock } from '@/components/ui/Skeleton';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope } from '@/types/envelope';
import type { VisualizationSpec } from '@/types/v2';

/** Recharts loads on demand, exactly as `AnomalyChart` does. */
const VizFrame = lazy(() => import('./VizFrame').then((module) => ({ default: module.VizFrame })));

/** One chart, titled and captioned by the backend's spec, never by us. */
export function VizCard({
  spec,
  envelope,
  theme,
}: {
  spec: VisualizationSpec;
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
}) {
  return (
    <Card tone="flat" className="edge-light px-5 py-5 sm:px-7 sm:py-6" as="section">
      <div data-viz-kind={spec.kind} data-testid="viz-card">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <h2 className="opsz-title font-serif text-[1.125rem] leading-7 text-ink">{spec.title}</h2>
          {spec.claim_ids.length > 0 ? (
            <span className="font-mono text-[0.6875rem] text-ink-faint">
              {spec.claim_ids.slice(0, 6).join(' ')}
            </span>
          ) : null}
        </div>
        {spec.caption ? (
          <p className="mt-1.5 max-w-prose text-[0.8125rem] leading-relaxed text-ink-muted">
            {spec.caption}
          </p>
        ) : null}
        <div className="mt-5">
          <Suspense fallback={<SkeletonBlock className="h-64 w-full" />}>
            <VizFrame spec={spec} envelope={envelope} theme={theme} />
          </Suspense>
        </div>
      </div>
    </Card>
  );
}
