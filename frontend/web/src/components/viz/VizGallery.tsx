import { VizCard } from './VizCard';
import { SectionLabel } from '@/components/ui/Card';
import type { ResolvedTheme } from '@/lib/theme';
import type { AnswerEnvelope } from '@/types/envelope';
import type { VisualizationSpec } from '@/types/v2';

/** The charts the backend asked for that no intent layout has already shown. */
export function VizGallery({
  specs,
  envelope,
  theme,
  label = 'Charts',
}: {
  specs: readonly VisualizationSpec[];
  envelope: AnswerEnvelope;
  theme: ResolvedTheme;
  label?: string;
}) {
  if (specs.length === 0) return null;
  return (
    <section data-print="flow" data-testid="viz-gallery">
      <SectionLabel>{label}</SectionLabel>
      <div className="mt-group space-y-5">
        {specs.map((spec) => (
          <VizCard key={spec.viz_id} spec={spec} envelope={envelope} theme={theme} />
        ))}
      </div>
    </section>
  );
}
