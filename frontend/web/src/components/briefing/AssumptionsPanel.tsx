import { Card, SectionLabel } from '@/components/ui/Card';

/**
 * Every default the backend applied, visible without expanding anything
 * (EN-4, build-plan 5.9). The text is the backend's, verbatim.
 */
export function AssumptionsPanel({
  assumptions,
  title = 'Assumptions applied',
}: {
  assumptions: readonly string[];
  title?: string;
}) {
  if (assumptions.length === 0) return null;
  return (
    <Card tone="sunken" className="px-5 py-5 sm:px-7" as="section">
      <SectionLabel>{title}</SectionLabel>
      <ul className="mt-3 grid gap-x-8 gap-y-2 lg:grid-cols-2" data-testid="assumptions">
        {assumptions.map((assumption) => (
          <li
            key={assumption}
            className="max-w-prose text-[0.8125rem] leading-relaxed text-ink-muted before:mr-2 before:text-ink-faint before:content-['—']"
          >
            {assumption}
          </li>
        ))}
      </ul>
    </Card>
  );
}
