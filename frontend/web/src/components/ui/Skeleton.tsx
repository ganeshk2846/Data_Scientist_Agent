import { cx } from '@/lib/cx';

/**
 * Skeletons are shaped like the content that replaces them, so nothing shifts
 * when the real thing arrives. The shimmer is a warm-grey sweep — no colour.
 */

const SHIMMER =
  'relative overflow-hidden bg-[rgb(var(--c-hairline))] ' +
  'before:absolute before:inset-0 before:-translate-x-full before:animate-[sweep_1.8s_ease-in-out_infinite] ' +
  'before:bg-gradient-to-r before:from-transparent before:via-[rgb(var(--c-surface)/0.65)] before:to-transparent ' +
  'motion-reduce:before:hidden';

export function SkeletonLine({
  width = '100%',
  className,
}: {
  width?: string;
  className?: string;
}) {
  return (
    <div
      aria-hidden
      style={{ width }}
      className={cx('h-[0.6875rem] rounded-full', SHIMMER, className)}
    />
  );
}

export function SkeletonBlock({ className }: { className?: string }) {
  return <div aria-hidden className={cx('rounded-sm', SHIMMER, className)} />;
}

/** Three lines of serif-height prose, the shape of a conclusion paragraph. */
export function SkeletonParagraph({ lines = 3 }: { lines?: number }) {
  const widths = ['100%', '96%', '72%', '88%', '64%'];
  return (
    <div aria-hidden className="space-y-3">
      {Array.from({ length: lines }, (_, index) => (
        <SkeletonLine key={index} width={widths[index % widths.length] ?? '100%'} className="h-4" />
      ))}
    </div>
  );
}
