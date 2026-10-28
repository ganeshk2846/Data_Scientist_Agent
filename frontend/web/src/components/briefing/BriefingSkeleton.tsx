import { Card, Hairline, SectionLabel } from '@/components/ui/Card';
import { SkeletonBlock, SkeletonLine, SkeletonParagraph } from '@/components/ui/Skeleton';

/**
 * Shaped like the real briefing — headline card, evidence card, SQL rows,
 * footer strip — so the content swaps in without the page shifting.
 */
export function BriefingSkeleton() {
  return (
    <div aria-hidden className="space-y-10">
      <Card className="p-6 sm:p-9">
        <SkeletonLine width="7rem" className="h-6 rounded-sm" />
        <div className="mt-6 space-y-4">
          <SkeletonLine width="94%" className="h-6" />
          <SkeletonLine width="88%" className="h-6" />
          <SkeletonLine width="54%" className="h-6" />
        </div>
        <Hairline className="my-7" />
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="space-y-3">
            <SkeletonLine width="4rem" />
            <SkeletonLine width="12rem" />
          </div>
          <SkeletonBlock className="h-9 w-[7.5rem]" />
        </div>
        <Hairline className="my-7" />
        <div className="flex flex-wrap gap-x-10 gap-y-4">
          {['6rem', '8rem', '5rem'].map((width, index) => (
            <div key={index} className="space-y-2">
              <SkeletonLine width="3.5rem" />
              <SkeletonLine width={width} />
            </div>
          ))}
        </div>
      </Card>

      <section>
        <SectionLabel>Evidence</SectionLabel>
        <Card className="mt-4 p-5 sm:p-7">
          <div className="flex items-center justify-between gap-4">
            <SkeletonLine width="9rem" className="h-4" />
            <SkeletonLine width="2rem" />
          </div>
          <Hairline className="my-5" />
          <SkeletonBlock className="h-56 w-full" />
        </Card>
      </section>

      <section>
        <SectionLabel>SQL</SectionLabel>
        <div className="mt-4 space-y-3">
          {[0, 1].map((index) => (
            <Card key={index} className="px-5 py-4">
              <SkeletonLine width="60%" className="h-4" />
            </Card>
          ))}
        </div>
      </section>

      <footer className="border-t border-hairline pt-5">
        <div className="flex flex-wrap gap-x-10 gap-y-3">
          {/* Keyed by position: these widths intentionally repeat. */}
          {['5rem', '4.5rem', '4rem', '5rem'].map((width, index) => (
            <SkeletonLine key={index} width={width} />
          ))}
        </div>
        <div className="mt-4">
          <SkeletonParagraph lines={1} />
        </div>
      </footer>
    </div>
  );
}
