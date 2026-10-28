import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { Button, Kbd } from '@/components/ui/Button';
import { SkeletonLine, SkeletonParagraph } from '@/components/ui/Skeleton';
import { STAGES } from '@/lib/stages';
import { formatDuration, formatNumber, formatPercent } from '@/lib/format';

/**
 * STAGE 1 SCAFFOLDING — replaced by the real hero and briefing in stages 2–4.
 *
 * It exists so the tokens, type scale, shadows, grain and both themes can be
 * checked against the design rules before any behaviour is built on them.
 */

const SWATCHES: readonly { name: string; className: string; note: string }[] = [
  { name: 'bg', className: 'bg-bg', note: 'page ground' },
  { name: 'sunken', className: 'bg-sunken', note: 'rail' },
  { name: 'surface', className: 'bg-surface', note: 'cards' },
  { name: 'raised', className: 'bg-raised', note: 'overlays' },
  { name: 'hairline', className: 'bg-hairline', note: '1px borders' },
  { name: 'gold', className: 'bg-gold', note: 'the one accent' },
  { name: 'sage', className: 'bg-sage', note: 'positive' },
  { name: 'terracotta', className: 'bg-terracotta', note: 'negative' },
  { name: 'series-1', className: 'bg-series-1', note: 'neutral data' },
  { name: 'series-2', className: 'bg-series-2', note: 'neutral data' },
  { name: 'series-3', className: 'bg-series-3', note: 'neutral data' },
  { name: 'series-4', className: 'bg-series-4', note: 'neutral data' },
];

export function ShellPreview() {
  return (
    <div className="space-y-16">
      <section>
        <SectionLabel>Stage 1 · foundation</SectionLabel>
        <h1 className="mt-4 max-w-prose text-h1 text-ink sm:text-display">
          Ask your data anything.
        </h1>
        <p className="mt-5 max-w-prose text-body-serif font-serif font-light text-ink-muted">
          The shell, the colour tokens and the type scale are in place. The question
          field, the live pipeline and the briefing arrive in the stages that follow.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <Button variant="primary" disabled>
            Ask
          </Button>
          <Button variant="quiet" disabled>
            Suggestions
          </Button>
          <span className="flex items-center gap-1.5 text-small text-ink-faint">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <span className="ml-1">focuses the question box</span>
          </span>
        </div>
      </section>

      <section>
        <SectionLabel>Palette · allowed colours only</SectionLabel>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {SWATCHES.map((swatch) => (
            <div key={swatch.name}>
              <div
                className={`h-14 rounded-sm border border-hairline ${swatch.className}`}
              />
              <div className="mt-2 font-mono text-[0.6875rem] text-ink">{swatch.name}</div>
              <div className="text-[0.6875rem] text-ink-faint">{swatch.note}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionLabel>Type scale</SectionLabel>
        <div className="mt-4 space-y-5">
          <p className="text-display text-ink">Display · Fraunces</p>
          <p className="text-h1 text-ink">Headline one · the conclusion voice</p>
          <p className="text-h2 text-ink">Headline two · section heads</p>
          <p className="text-h3 font-sans text-ink">Headline three · card titles</p>
          <p className="max-w-prose text-body-serif font-serif font-light text-ink-muted">
            Body serif · the answer narrative, set long for reading at length.
          </p>
          <p className="max-w-prose text-body text-ink-muted">
            Body sans · interface prose, labels and supporting copy.
          </p>
          <p className="text-small text-ink-faint">Small · metadata.</p>
          <p className="text-micro uppercase text-ink-faint">Micro · badges and labels</p>
          <p className="font-mono text-[0.8125rem] text-ink">
            {'SELECT count(*) FROM orders WHERE purchase_month = \'2018-08\';'}
          </p>
        </div>
      </section>

      <section>
        <SectionLabel>Figures · tabular</SectionLabel>
        <div className="mt-4 grid gap-6 sm:grid-cols-3">
          <div>
            <div className="font-serif text-figure tabular-nums text-ink">
              {formatNumber(6512)}
            </div>
            <div className="mt-1 text-micro uppercase text-ink-faint">Orders</div>
          </div>
          <div>
            <div className="font-serif text-figure tabular-nums text-sage">
              {formatPercent(12.4, true)}
            </div>
            <div className="mt-1 text-micro uppercase text-ink-faint">Above expected</div>
          </div>
          <div>
            <div className="font-serif text-figure tabular-nums text-terracotta">
              {formatPercent(-8.1, true)}
            </div>
            <div className="mt-1 text-micro uppercase text-ink-faint">Below expected</div>
          </div>
        </div>
      </section>

      <section>
        <SectionLabel>Pipeline stages · derived from service.py</SectionLabel>
        <Card className="mt-4 p-6">
          <ul className="space-y-3">
            {STAGES.map((stage) => (
              <li key={stage.step} className="flex items-baseline gap-4">
                <span className="w-7 shrink-0 font-mono text-[0.6875rem] tabular-nums text-gold">
                  {stage.step}
                </span>
                <span className="w-28 shrink-0 text-small text-ink">{stage.label}</span>
                <span className="min-w-0 flex-1 text-small text-ink-faint">
                  {stage.blurb}
                </span>
                <span className="shrink-0 text-[0.6875rem] uppercase text-ink-faint">
                  {stage.always ? 'always' : 'conditional'}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      <section>
        <SectionLabel>Surfaces, shadows and skeletons</SectionLabel>
        <div className="mt-4 grid gap-5 lg:grid-cols-3">
          <Card tone="flat" className="p-6">
            <h3 className="text-h3 font-sans text-ink">Flat</h3>
            <p className="mt-2 text-small text-ink-muted">Sits on the page.</p>
            <Hairline className="my-5" />
            <SkeletonParagraph lines={3} />
          </Card>
          <Card tone="raised" className="p-6">
            <h3 className="text-h3 font-sans text-ink">Raised</h3>
            <p className="mt-2 text-small text-ink-muted">Lifts off the page.</p>
            <Hairline className="my-5" />
            <div className="space-y-3">
              <SkeletonLine width="62%" />
              <SkeletonLine width="88%" />
            </div>
          </Card>
          <Card tone="sunken" className="p-6">
            <h3 className="text-h3 font-sans text-ink">Sunken</h3>
            <p className="mt-2 text-small text-ink-muted">Recedes behind it.</p>
            <Hairline className="my-5" />
            <p className="font-mono text-[0.6875rem] tabular-nums text-ink-faint">
              latency {formatDuration(1840)} · queries {formatNumber(2)} · rows{' '}
              {formatNumber(6512)}
            </p>
          </Card>
        </div>
      </section>
    </div>
  );
}
