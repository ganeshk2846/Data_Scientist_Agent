import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

/**
 * Lineage: the thread from a claim, through the evidence block that produced
 * it, to the SQL that produced that.
 *
 * Hovering or focusing any one of the three highlights all three. The link is
 * entirely derived from the envelope — `claim.source.id` names a query or
 * artifact, and `evidence[].source_claims` names claim ids — so nothing here
 * invents a relationship the backend did not assert.
 */
export interface LineageFocus {
  claimIds: readonly string[];
  /** `claim.source.id` values: query ids like "Q1", or artifact ids. */
  sourceIds: readonly string[];
}

interface LineageValue {
  focus: LineageFocus | null;
  setFocus: (focus: LineageFocus | null) => void;
  /** True when this claim id is part of the active thread. */
  isClaimLit: (claimId: string) => boolean;
  /** True when this query or artifact id is part of the active thread. */
  isSourceLit: (sourceId: string) => boolean;
  /** True when any of these claim ids is lit — for evidence cards. */
  isAnyClaimLit: (claimIds: readonly string[]) => boolean;
  active: boolean;
}

const LineageCtx = createContext<LineageValue | null>(null);

export function LineageProvider({ children }: { children: ReactNode }) {
  const [focus, setFocus] = useState<LineageFocus | null>(null);

  const value = useMemo<LineageValue>(() => {
    const claims = new Set(focus?.claimIds ?? []);
    const sources = new Set(focus?.sourceIds ?? []);
    return {
      focus,
      setFocus,
      active: focus !== null,
      isClaimLit: (claimId) => claims.has(claimId),
      isSourceLit: (sourceId) => sources.has(sourceId),
      isAnyClaimLit: (claimIds) => claimIds.some((id) => claims.has(id)),
    };
  }, [focus]);

  return <LineageCtx.Provider value={value}>{children}</LineageCtx.Provider>;
}

/** Safe outside a provider: lineage then simply never lights up. */
export function useLineage(): LineageValue {
  const value = useContext(LineageCtx);
  if (value) return value;
  return {
    focus: null,
    setFocus: () => {},
    active: false,
    isClaimLit: () => false,
    isSourceLit: () => false,
    isAnyClaimLit: () => false,
  };
}

/**
 * The handlers a lineage participant needs. Pointer and keyboard both drive it,
 * so the thread is not a mouse-only feature.
 */
export function useLineageHandlers(focus: LineageFocus) {
  const { setFocus } = useLineage();
  const enter = useCallback(() => setFocus(focus), [focus, setFocus]);
  const leave = useCallback(() => setFocus(null), [setFocus]);
  return {
    onMouseEnter: enter,
    onMouseLeave: leave,
    onFocus: enter,
    onBlur: leave,
  };
}
