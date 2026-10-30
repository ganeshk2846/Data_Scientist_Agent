"""Pydantic contracts shared across the backend pipeline.

These follow ``spec/Interfaces.md`` and ``docs/Product.md`` 5.3. The models are
frozen and reject unknown fields so a step cannot quietly widen a contract that
downstream steps, the trace, or the evaluator depend on. ``TableRef`` keeps an
optional ``rows`` extension for in-memory analyst execution; its required
fields match the interface contract.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GuardReason = Literal["write_attempt", "injection", "unsafe"]
ExecutionStatus = Literal["ok", "error", "timeout", "truncated"]
ExecutionErrorKind = Literal[
    "binder", "catalog", "syntax", "permission", "timeout", "other"
]
ColumnRole = Literal["dimension", "measure", "time", "key"]
ValidationMode = Literal["benchmark", "enterprise"]
ValidationCheckStatus = Literal["pass", "fail", "skipped"]
SqlOrigin = Literal["compiler", "generator", "repair"]
RepairErrorKind = Literal["parse", "validation", "runtime", "reconciliation"]
MetricCoverage = Literal["full", "partial", "none"]
MetricTimeGrain = Literal["day", "week", "month", "quarter", "year"]
MetricFilterOperator = Literal["=", "!=", ">", ">=", "<", "<=", "in"]
JoinCardinality = Literal["1:1", "1:N", "N:1", "N:M"]
ReconciliationStatus = Literal["pass", "flags"]
ReconciliationCheckName = Literal[
    "grain", "nulls", "duplicates", "ranges", "registry_total"
]
ReconciliationCheckStatus = Literal["pass", "flag"]
ValidationCheckName = Literal[
    "parse",
    "single_select",
    "no_dml_ddl",
    "allowlist",
    "approved_joins_fanout",
    "limits_bounds",
    "cost_gate",
    "readonly_exec",
    "post_exec",
    "reconcile",
]


class ContractModel(BaseModel):
    """Base for every contract object: immutable, strict about its shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GatewayConfig(ContractModel):
    """Step 9 executor configuration for one datasource.

    ``read_only`` is deliberately not configurable: the gateway must never be
    able to open a writable connection.
    """

    datasource_id: str = Field(min_length=1)
    dialect: str = Field(min_length=1)
    connection_url: str = Field(min_length=1, repr=False)
    connection_pool_size: int = Field(default=5, ge=1)
    timeout_ms: int = Field(default=30_000, ge=1)
    read_only: bool = True

    @field_validator("read_only")
    @classmethod
    def _read_only_must_stay_locked(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("GatewayConfig.read_only is locked to True")
        return True


class ExecutionColumn(ContractModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    role: ColumnRole | None = None


class ExecutionError(ContractModel):
    kind: ExecutionErrorKind
    message: str = Field(min_length=1)


class ExecutionResult(ContractModel):
    """Step 9 output. Rows are tuples so a consumer cannot mutate the payload."""

    query_id: str = Field(min_length=1)
    datasource_id: str | None = None
    status: ExecutionStatus
    columns: tuple[ExecutionColumn, ...] = ()
    row_count: int = Field(ge=0)
    truncated: bool = False
    rows: tuple[tuple[Any, ...], ...] | None = None
    result_ref: str | None = None
    rows_scanned: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def _truncated_status_matches_flag(self) -> ExecutionResult:
        if self.status == "truncated" and not self.truncated:
            raise ValueError("status 'truncated' requires truncated=True")
        return self


class GuardResult(ContractModel):
    """Step 1 output. A passed guard cannot also report why it blocked."""

    passed: bool
    reason: GuardReason | None = None
    matched_rule: str | None = None

    @model_validator(mode="after")
    def _passed_guard_has_no_block_reason(self) -> GuardResult:
        if self.passed and self.reason is not None:
            raise ValueError("a passed GuardResult cannot carry a block reason")
        return self


class AnswerabilityResult(ContractModel):
    """Step 5 output.

    ``confidence`` is confidence in the answerable/refused decision. A refusal
    must name what the catalog cannot answer and may list covered domains.
    """

    answerable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    missing: tuple[str, ...] = ()
    closest_answerable: str | None = None
    cheap_filter_hit: str | None = None
    available_domains: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _refusal_names_the_gap(self) -> AnswerabilityResult:
        if not self.answerable and not self.missing:
            raise ValueError("a refused AnswerabilityResult must name what is missing")
        if self.answerable and self.missing:
            raise ValueError("an answerable result cannot list missing attributes")
        return self


class LinkedValue(ContractModel):
    """A question phrase grounded to one database literal."""

    phrase: str = Field(min_length=1)
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    literal: str
    confidence: float = Field(ge=0.0, le=1.0)


class PerceptorConfig(ContractModel):
    """Online perceptor budgets and thresholds from ``Interfaces.md``."""

    column_top_k: int = Field(default=5, ge=1)
    value_description_top_k: int = Field(default=3, ge=1)
    value_vector_top_k: int = Field(default=3, ge=1)
    value_search_workers: int = Field(default=4, ge=1)
    value_search_max_calls: int = Field(default=80, ge=1)
    column_score_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    value_score_threshold: float = Field(default=0.55, ge=0.0, le=1.0)


class PerceptionResult(ContractModel):
    """Output of fuzzy value linking before SQL generation."""

    catalog_version: str = Field(min_length=1)
    linked_values: tuple[LinkedValue, ...] = ()
    requires_clarification: bool = False
    clarification_reason: str | None = None

    @model_validator(mode="after")
    def _clarification_has_a_reason(self) -> PerceptionResult:
        if self.requires_clarification and not self.clarification_reason:
            raise ValueError("clarification requires a reason")
        return self


class ValidationCheck(ContractModel):
    id: int = Field(ge=1, le=10)
    name: ValidationCheckName
    status: ValidationCheckStatus
    reason: str | None = None
    offending: tuple[str, ...] | None = None


class EstimatedCost(ContractModel):
    rows_scanned: int | None = Field(default=None, ge=0)
    bytes: int | None = Field(default=None, ge=0)
    plan_cost: float | None = Field(default=None, ge=0)


class ValidationResult(ContractModel):
    """Step 8 output; checks 8-10 are appended after execution."""

    approved: bool
    validation_mode: ValidationMode
    checks: tuple[ValidationCheck, ...] = ()
    est_cost: EstimatedCost | None = None
    rewrite: str | None = None

    @model_validator(mode="after")
    def _checks_are_consistent(self) -> ValidationResult:
        check_ids = [check.id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("validation check ids must be unique")
        if self.approved and any(check.status == "fail" for check in self.checks):
            raise ValueError("an approved ValidationResult cannot contain a failed check")
        return self


class IntendedColumn(ContractModel):
    """A column the generated SQL is expected to produce."""

    name: str = Field(min_length=1)
    role: ColumnRole


class ModelUsage(ContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)


class SqlCandidate(ContractModel):
    """Step 7 output, field-for-field from ``Interfaces.md``."""

    candidate_id: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    dialect: str = Field(min_length=1)
    origin: SqlOrigin
    intended_columns: tuple[IntendedColumn, ...] = ()
    grain: tuple[str, ...] = ()
    uses_edges: tuple[str, ...] = ()
    model: ModelUsage | None = None
    icl_exemplars_used: tuple[str, ...] | None = None
    repair_of: str | None = None

    @model_validator(mode="after")
    def _repairs_name_the_failed_candidate(self) -> SqlCandidate:
        if self.origin == "repair" and not self.repair_of:
            raise ValueError("a repair candidate must name repair_of")
        return self


class AllowlistedColumn(ContractModel):
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)


class SchemaAllowlist(ContractModel):
    """The exact tables and columns a generated/repair candidate may use."""

    tables: tuple[str, ...] = ()
    columns: tuple[AllowlistedColumn, ...] = ()

    @property
    def table_set(self) -> frozenset[str]:
        return frozenset(table.lower() for table in self.tables)

    @property
    def column_set(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (column.table.lower(), column.column.lower())
            for column in self.columns
        )

    def permits_table(self, table: str) -> bool:
        return table.lower() in self.table_set

    def permits_column(self, table: str, column: str) -> bool:
        return (table.lower(), column.lower()) in self.column_set


class RepairError(ContractModel):
    kind: RepairErrorKind
    message: str = Field(min_length=1)


class RepairRequest(ContractModel):
    """Step 8b input. The allowlist is carried unchanged into every attempt."""

    attempt: Literal[1, 2]
    failed_sql: str = Field(min_length=1)
    failed_candidate_id: str | None = None
    error: RepairError
    allowlist: SchemaAllowlist
    reflector_score_threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class ClarificationResult(ContractModel):
    """SQL-13 structured clarification envelope."""

    what_understood: str = Field(min_length=1)
    what_needs_clarification: str = Field(min_length=1)


class RepairAttempt(ContractModel):
    attempt: Literal[1, 2]
    request: RepairRequest
    candidate: SqlCandidate | None = None
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None

    @model_validator(mode="after")
    def _request_matches_attempt(self) -> RepairAttempt:
        if self.request.attempt != self.attempt:
            raise ValueError("repair attempt and request.attempt must match")
        return self


class RepairOutcome(ContractModel):
    success: bool
    candidate: SqlCandidate | None = None
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    attempts: tuple[RepairAttempt, ...] = Field(default=(), max_length=2)
    clarification: ClarificationResult | None = None

    @model_validator(mode="after")
    def _outcome_is_complete(self) -> RepairOutcome:
        if self.success:
            if (
                self.candidate is None
                or self.validation is None
                or self.execution is None
            ):
                raise ValueError(
                    "a successful repair outcome needs candidate, validation and execution"
                )
            if self.execution.status not in ("ok", "truncated"):
                raise ValueError(
                    "a successful repair outcome needs an ok or truncated execution"
                )
            if self.clarification is not None:
                raise ValueError("a successful outcome cannot carry a clarification")
        elif self.clarification is None:
            raise ValueError("a failed repair outcome needs a clarification")
        return self


class Period(ContractModel):
    """A half-open reporting period: ``start`` inclusive, ``end`` exclusive."""

    start: date
    end: date

    @model_validator(mode="after")
    def _period_has_positive_length(self) -> Period:
        if self.end <= self.start:
            raise ValueError("period end must be after start")
        return self


class MetricAllowedDimension(ContractModel):
    """A governed grouping dimension and the approved join path it requires."""

    name: str = Field(min_length=1)
    column: str = Field(min_length=1)
    table: str = ""
    join_edges: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    time_grain: MetricTimeGrain | None = None


class MetricJoinPath(ContractModel):
    edge_id: str = Field(min_length=1)
    cardinality: JoinCardinality


class MetricReconciliation(ContractModel):
    """The registry-owned cross-check query and its absolute tolerance."""

    sql: str = Field(min_length=1)
    tolerance: float = Field(default=0.0, ge=0.0)


class MetricDefinition(ContractModel):
    """A governed KPI definition (MET-1)."""

    metric_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    synonyms: tuple[str, ...] = ()
    formula: str = Field(min_length=1)
    required_filters: tuple[str, ...] = ()
    grain: tuple[str, ...] = ()
    date_column: str = Field(min_length=1)
    allowed_dimensions: tuple[MetricAllowedDimension, ...] = ()
    base_table: str = Field(min_length=1)
    join_path: tuple[MetricJoinPath, ...] = ()
    reconciliation: MetricReconciliation | None = None
    caveats: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)
    approved_by: str = "seed"
    approved_at: str = "1970-01-01T00:00:00Z"


class ResolvedDimension(ContractModel):
    requested: str = Field(min_length=1)
    allowed: bool
    column: str | None = None
    table: str | None = None
    reason: str | None = None


class MetricFilter(ContractModel):
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    operator: MetricFilterOperator = "="
    value: str | tuple[str, ...]

    @model_validator(mode="after")
    def _operator_matches_value_shape(self) -> MetricFilter:
        if self.operator == "in":
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("an IN filter needs a non-empty tuple of values")
        elif not isinstance(self.value, str):
            raise ValueError("a scalar filter needs one string value")
        return self


class MetricResolution(ContractModel):
    """Step 4 output and the compiler's input."""

    coverage: MetricCoverage
    metric_id: str | None = None
    definition: MetricDefinition | None = None
    resolved_dimensions: tuple[ResolvedDimension, ...] = ()
    grain: str | None = None
    date_column: str | None = None
    required_filters: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    filters: tuple[MetricFilter, ...] = ()
    period: Period | None = None
    time_grain: MetricTimeGrain | None = None
    reasoning: str | None = None
    model: ModelUsage | None = None

    @model_validator(mode="after")
    def _full_resolution_names_a_definition(self) -> MetricResolution:
        if self.coverage == "full":
            if self.metric_id is None or self.definition is None:
                raise ValueError(
                    "a full metric resolution needs metric_id and definition"
                )
        if (
            self.metric_id is not None
            and self.definition is not None
            and self.metric_id != self.definition.metric_id
        ):
            raise ValueError("metric_id must match definition.metric_id")
        return self


class ReconciliationComparison(ContractModel):
    metric_id: str = Field(min_length=1)
    observed: float
    expected: float
    tolerance: float = Field(ge=0.0)
    within: bool


class ReconciliationCheck(ContractModel):
    name: ReconciliationCheckName
    status: ReconciliationCheckStatus
    detail: str | None = None


class ReconciliationResult(ContractModel):
    """Step 10 output (SQL-10, MET-5)."""

    status: ReconciliationStatus
    checks: tuple[ReconciliationCheck, ...] = ()
    registry_comparison: ReconciliationComparison | None = None
    caveats: tuple[str, ...] = ()
    retry_used: bool = False
    diagnosis: str | None = None

    @model_validator(mode="after")
    def _flags_need_a_caveat(self) -> ReconciliationResult:
        if self.status == "flags" and not self.caveats:
            raise ValueError("a flagged reconciliation result needs a caveat")
        if self.status == "pass" and self.caveats:
            raise ValueError("a passing reconciliation result cannot have caveats")
        return self


RouteLabel = Literal[
    "lookup",
    "anomaly",
    "driver",
    "risk",
    "clarify",
    "refused",
    "blocked",
]
IntentLabel = Literal[
    "Descriptive",
    "Comparative",
    "Diagnostic",
    "Prescriptive",
]
AnalystColumnRole = Literal["dimension", "measure", "time", "key", "label"]
AnomalyVerdict = Literal[
    "unusual", "within_normal_range", "insufficient_evidence"
]
AnomalyPersistence = Literal["one_off", "sustained", "drift", "unknown"]
AnalystStatus = Literal["ok", "insufficient_evidence"]
OrchestrationStatus = Literal[
    "ok",
    "clarification",
    "refused",
    "blocked",
    "insufficient_evidence",
    "error",
]
PlanStepStatus = Literal["pending", "completed", "skipped", "failed"]
GroundTruthSplit = Literal["build", "heldout"]
PlantedAnomalyKind = Literal["level_shift", "spike", "dip", "gradual_decay"]
PlantedDriverCauseKind = Literal["segment", "category", "carrier", "price_change"]
NegativeControlKind = Literal[
    "ordinary", "holiday_peak", "promotion_peak", "small_volume", "noise"
]


class TimeSlot(ContractModel):
    raw: str = ""
    current: Period | None = None
    comparison: Period | None = None
    grain: str | None = None


class SlotFilter(ContractModel):
    term: str = Field(min_length=1)
    value_phrase: str = Field(min_length=1)


class RouteSlots(ContractModel):
    metric_terms: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[SlotFilter, ...] = ()
    time: TimeSlot = Field(default_factory=TimeSlot)
    action_intent: bool = False


class RulesSignal(ContractModel):
    matched: tuple[str, ...] = ()
    label: RouteLabel | None = None


class ClassifierSignal(ContractModel):
    label: RouteLabel | None = None
    prob: float = Field(default=0.0, ge=0.0, le=1.0)
    metric_terms: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()


class ModelRouteSignal(ContractModel):
    proposed_label: RouteLabel | None = None
    slots: RouteSlots | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str | None = None
    usage: ModelUsage | None = None


class RouterSignals(ContractModel):
    rules: RulesSignal = Field(default_factory=RulesSignal)
    classifier: ClassifierSignal = Field(default_factory=ClassifierSignal)
    model: ModelRouteSignal | None = None
    agreement: bool = False


class RouterResult(ContractModel):
    route_labels: tuple[RouteLabel, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    intent_label: IntentLabel
    slots: RouteSlots = Field(default_factory=RouteSlots)
    signals: RouterSignals = Field(default_factory=RouterSignals)
    reason: str = Field(min_length=1)
    clarification: ClarificationResult | None = None

    @property
    def primary_route(self) -> RouteLabel:
        return self.route_labels[0]

    @model_validator(mode="after")
    def _clarification_matches_confidence(self) -> RouterResult:
        if "clarify" in self.route_labels and self.clarification is None:
            raise ValueError("a clarify route needs a clarification envelope")
        if "blocked" in self.route_labels and len(self.route_labels) != 1:
            raise ValueError("a blocked route cannot carry another route label")
        if self.confidence < 0.70 and self.route_labels != ("clarify",):
            raise ValueError("routing below 0.70 must be a clarification")
        return self


class AnalystColumn(ContractModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    role: AnalystColumnRole


class TableRef(ContractModel):
    query_id: str = Field(min_length=1)
    columns: tuple[AnalystColumn, ...] = ()
    row_count: int = Field(default=0, ge=0)
    uri: str = Field(min_length=1)
    rows: tuple[tuple[Any, ...], ...] = ()

    @model_validator(mode="after")
    def _rows_match_columns(self) -> TableRef:
        width = len(self.columns)
        if self.rows and width and any(len(row) != width for row in self.rows):
            raise ValueError("every TableRef row must match its columns")
        if self.rows and self.row_count != len(self.rows):
            raise ValueError("row_count must match the number of rows")
        return self


class AnalystInput(ContractModel):
    module: Literal["anomaly", "driver", "risk"]
    params: dict[str, Any] = Field(default_factory=dict)
    tables: dict[str, TableRef] = Field(default_factory=dict)
    metric: MetricDefinition | None = None
    run_id: str = Field(min_length=1)
    seed: int | None = None


class AnomalyParams(ContractModel):
    metric: str = Field(min_length=1)
    grain: MetricTimeGrain = "month"
    test_window: Period
    history_window: Period | None = None
    series_dimension: str | None = None
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    min_volume: float = Field(default=0.0, ge=0.0)
    use_calendar: bool = False


class AnomalyResult(ContractModel):
    verdict: AnomalyVerdict
    window: str = Field(min_length=1)
    actual: float
    expected: float
    expected_range: tuple[float, float]
    deviation_pct: float
    robust_score: float
    persistence: AnomalyPersistence
    threshold: float = Field(ge=0.0)
    correction_used: str | None = None
    calendar_effects: tuple[str, ...] = ()
    baseline_kind: Literal["seasonal", "robust_trailing"]

    @model_validator(mode="after")
    def _range_is_ordered(self) -> AnomalyResult:
        if self.expected_range[0] > self.expected_range[1]:
            raise ValueError("expected_range must be ordered low to high")
        return self


class DriverContribution(ContractModel):
    dimension: str = Field(min_length=1)
    value: str = Field(min_length=1)
    contribution: float
    share: float
    interval: tuple[float, float]
    sample_size: int = Field(ge=0)
    unstable: bool
    grade: int = Field(ge=0, le=4)
    data_needed_to_strengthen: tuple[str, ...] = ()


class DriverResult(ContractModel):
    metric: str = Field(min_length=1)
    current_period: str = Field(min_length=1)
    comparison_period: str = Field(min_length=1)
    total_change: float
    drivers: tuple[DriverContribution, ...] = ()
    reconciliation_error: float
    candidates_examined: int = Field(ge=0)
    correction_used: str | None = None


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_UNSAFE_TEXT = ("/", "\\", "\x00", "\n", "\r")


def _identifier(value: str, field: str) -> str:
    text = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(text):
        raise ValueError(
            f"{field} must start with a letter and contain only letters, "
            "digits, underscores or hyphens"
        )
    return text


def _safe_text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be blank")
    if any(character in text for character in _UNSAFE_TEXT):
        raise ValueError(
            f"{field} must not contain path separators, control characters "
            "or line breaks"
        )
    return text


def _finite(value: float, field: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value


class TruthUnit(ContractModel):
    """The dimension and value a planted truth record applies to."""

    dimension: str = Field(min_length=1)
    value: str = Field(min_length=1)

    @field_validator("dimension")
    @classmethod
    def _dimension_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "unit dimension")

    @field_validator("value")
    @classmethod
    def _value_is_a_safe_label(cls, value: str) -> str:
        return _safe_text(value, "unit value")


class PlantedAnomaly(ContractModel):
    """A generator-planted anomaly and the unit it affects (design C3)."""

    anomaly_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: TruthUnit
    kind: PlantedAnomalyKind
    start: date
    end: date | None = None
    magnitude_pct: float

    @field_validator("anomaly_id", "metric")
    @classmethod
    def _identifier_fields(cls, value: str) -> str:
        return _identifier(value, "anomaly identifier")

    @field_validator("magnitude_pct")
    @classmethod
    def _magnitude_is_finite(cls, value: float) -> float:
        return _finite(value, "anomaly magnitude_pct")

    @model_validator(mode="after")
    def _end_is_not_before_start(self) -> PlantedAnomaly:
        if self.end is not None and self.end < self.start:
            raise ValueError("anomaly end must not be before its start")
        return self


class PlantedDriver(ContractModel):
    """The true cause of a planted anomaly and its share of the change."""

    anomaly_id: str = Field(min_length=1)
    cause_kind: PlantedDriverCauseKind
    cause: TruthUnit
    true_share: float

    @field_validator("anomaly_id")
    @classmethod
    def _anomaly_id_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "driver anomaly_id")

    @field_validator("true_share")
    @classmethod
    def _true_share_is_finite(cls, value: float) -> float:
        return _finite(value, "driver true_share")


class Confounder(ContractModel):
    """A factor that moves with a planted driver but is explicitly not causal."""

    anomaly_id: str = Field(min_length=1)
    moves_with: TruthUnit
    is_cause: Literal[False] = False

    @field_validator("anomaly_id")
    @classmethod
    def _anomaly_id_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "confounder anomaly_id")


class NegativeControl(ContractModel):
    """A period that should not be flagged as an anomaly (design C3)."""

    control_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: TruthUnit
    period: Period
    kind: NegativeControlKind

    @field_validator("control_id", "metric")
    @classmethod
    def _identifier_fields(cls, value: str) -> str:
        return _identifier(value, "negative-control identifier")


class TrueRiskSegment(ContractModel):
    """A planted relative-risk segment for the future churn process."""

    segment: str = Field(min_length=1)
    relative_risk: float

    @field_validator("segment")
    @classmethod
    def _segment_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "risk segment")

    @field_validator("relative_risk")
    @classmethod
    def _relative_risk_is_finite(cls, value: float) -> float:
        return _finite(value, "relative_risk")


class ChurnProcessMetadata(ContractModel):
    """Documented stochastic churn process metadata for future risk work."""

    process_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    params: dict[str, float] = Field(default_factory=dict)
    true_risk_segments: tuple[TrueRiskSegment, ...] = ()
    label_table: str = Field(min_length=1)

    @field_validator("process_id")
    @classmethod
    def _process_id_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "churn process_id")

    @field_validator("description")
    @classmethod
    def _description_is_safe_text(cls, value: str) -> str:
        return _safe_text(value, "churn description")

    @field_validator("label_table")
    @classmethod
    def _label_table_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "churn label_table")

    @field_validator("params")
    @classmethod
    def _params_are_named_finite_numbers(
        cls,
        value: dict[str, float],
    ) -> dict[str, float]:
        cleaned: dict[str, float] = {}
        for key, item in value.items():
            name = _identifier(key, "churn parameter name")
            cleaned[name] = _finite(float(item), f"churn parameter {name!r}")
        return dict(sorted(cleaned.items()))


class InsufficientEvidenceCase(ContractModel):
    """An evaluation case whose expected outcome is insufficient evidence.

    This record is a Phase 3 proposal. ``reason`` is the documented reason the
    generator considers the case unevaluable; it is not a runtime instruction.
    """

    case_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: TruthUnit | None = None
    period: Period | None = None
    reason: str = Field(min_length=1)

    @field_validator("case_id", "metric")
    @classmethod
    def _identifier_fields(cls, value: str) -> str:
        return _identifier(value, "insufficient-evidence identifier")

    @field_validator("reason")
    @classmethod
    def _reason_is_safe_text(cls, value: str) -> str:
        return _safe_text(value, "insufficient-evidence reason")


class GroundTruthManifest(ContractModel):
    """Generator-written planted truth, readable only by scoring code (DATA-4/9).

    The manifest carries no SQL, code, path, import or runtime instruction.
    ``split`` distinguishes the development/build snapshot from the locked
    held-out snapshot; scoring code receives records, never the held-out file.
    """

    snapshot_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    generator_version: str = Field(min_length=1)
    split: GroundTruthSplit
    anomalies: tuple[PlantedAnomaly, ...] = ()
    drivers: tuple[PlantedDriver, ...] = ()
    confounders: tuple[Confounder, ...] = ()
    negative_controls: tuple[NegativeControl, ...] = ()
    churn_process: ChurnProcessMetadata | None = None
    insufficient_evidence_cases: tuple[InsufficientEvidenceCase, ...] = ()

    @field_validator("snapshot_id")
    @classmethod
    def _snapshot_id_is_an_identifier(cls, value: str) -> str:
        return _identifier(value, "snapshot_id")

    @field_validator("generator_version")
    @classmethod
    def _generator_version_is_safe_text(cls, value: str) -> str:
        return _safe_text(value, "generator_version")

    @model_validator(mode="after")
    def _ids_are_unique_and_references_resolve(self) -> GroundTruthManifest:
        anomaly_ids = [item.anomaly_id for item in self.anomalies]
        if len(anomaly_ids) != len(set(anomaly_ids)):
            raise ValueError("anomaly_id values must be unique")
        control_ids = [item.control_id for item in self.negative_controls]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("negative control_id values must be unique")
        case_ids = [item.case_id for item in self.insufficient_evidence_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("insufficient-evidence case_id values must be unique")
        known = set(anomaly_ids)
        for driver in self.drivers:
            if driver.anomaly_id not in known:
                raise ValueError(
                    f"driver references unknown anomaly_id {driver.anomaly_id!r}"
                )
        for confounder in self.confounders:
            if confounder.anomaly_id not in known:
                raise ValueError(
                    "confounder references unknown anomaly_id "
                    f"{confounder.anomaly_id!r}"
                )
        return self

    @property
    def is_heldout(self) -> bool:
        """Whether this manifest belongs to the locked held-out split."""

        return self.split == "heldout"


class AnalystArtifact(ContractModel):
    artifact_id: str = Field(min_length=1)
    kind: Literal["chart_data", "table", "model_card"]
    uri: str = Field(min_length=1)


class AnalystOutput(ContractModel):
    module: Literal["anomaly", "driver", "risk"]
    status: AnalystStatus
    reason: str | None = None
    result: AnomalyResult | DriverResult | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    artifacts: tuple[AnalystArtifact, ...] = ()

    @model_validator(mode="after")
    def _status_matches_payload(self) -> AnalystOutput:
        if self.status == "ok" and self.result is None:
            raise ValueError("an ok analyst output needs a typed result")
        if self.status != "ok" and self.result is not None:
            raise ValueError("a non-ok analyst output cannot carry a result")
        if self.status == "insufficient_evidence" and not self.reason:
            raise ValueError("insufficient evidence needs a reason")
        return self


class ExecutionBudget(ContractModel):
    max_queries: int = Field(default=3, ge=0)
    max_tokens: int = Field(default=4096, ge=0)
    max_wall_ms: int = Field(default=10_000, ge=1)


class BudgetPolicy(ContractModel):
    """Per-route execution budgets (OPS-2, OPS-6, V2-PRE-2).

    One flat budget cannot serve every route: a governed lookup runs one or
    two queries and should stay inside the fast-path SLA, while a driver run
    needs a query per window, and the V2 diagnostic chain needs more again.
    Before this existed, a route that legitimately needed a fourth query hit
    ``BudgetExceeded`` and reported an error instead of an answer.

    ``default`` keeps V1's values, so a policy with no overrides behaves
    exactly as the single ``ExecutionBudget`` did.
    """

    default: ExecutionBudget = Field(default_factory=ExecutionBudget)
    per_route: dict[RouteLabel, ExecutionBudget] = Field(default_factory=dict)

    def for_route(self, route: RouteLabel) -> ExecutionBudget:
        """Return the budget for ``route``, falling back to ``default``."""

        return self.per_route.get(route, self.default)

    @classmethod
    def defaults(cls) -> BudgetPolicy:
        """The calibrated starting policy.

        Query counts come from what each route actually executes; wall-clock
        and token values follow the tiers in ``DESIGN_DETAIL.md`` B14. These
        are starting values to be calibrated on the development set and frozen
        in ``spec/thresholds.md`` before any held-out run (EVAL-7, OPS-6).
        """

        return cls(
            default=ExecutionBudget(),
            per_route={
                # One compiled query, or two when the question is comparative.
                "lookup": ExecutionBudget(
                    max_queries=2, max_tokens=4096, max_wall_ms=10_000
                ),
                # One series query, plus headroom for a repair.
                "anomaly": ExecutionBudget(
                    max_queries=2, max_tokens=8192, max_wall_ms=15_000
                ),
                # One query per window, plus headroom for an indicator query.
                "driver": ExecutionBudget(
                    max_queries=3, max_tokens=8192, max_wall_ms=20_000
                ),
                # Routes that must never reach the warehouse.
                "risk": ExecutionBudget(max_queries=0),
                "clarify": ExecutionBudget(max_queries=0),
                "refused": ExecutionBudget(max_queries=0),
                "blocked": ExecutionBudget(max_queries=0),
            },
        )


class BudgetUsage(ContractModel):
    queries: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    wall_ms: int = Field(default=0, ge=0)


class QueryRecord(ContractModel):
    query_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    status: ExecutionStatus
    row_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class PlanStep(ContractModel):
    step_id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    status: PlanStepStatus = "pending"
    detail: str | None = None


class OrchestrationResult(ContractModel):
    status: OrchestrationStatus
    route_labels: tuple[RouteLabel, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    intent_label: IntentLabel
    reason: str = Field(min_length=1)
    router: RouterResult
    clarification: ClarificationResult | None = None
    refusal: str | None = None
    candidate: SqlCandidate | None = None
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    executions: tuple[ExecutionResult, ...] = ()
    reconciliation: ReconciliationResult | None = None
    analyst_outputs: tuple[AnalystOutput, ...] = ()
    queries: tuple[QueryRecord, ...] = ()
    budget: BudgetUsage = Field(default_factory=BudgetUsage)
    plan: tuple[PlanStep, ...] = ()
    latency_ms: int = Field(ge=0)

    @property
    def primary_route(self) -> RouteLabel:
        return self.route_labels[0]


class AskRequest(ContractModel):
    question: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    clarification_of: str | None = None

    @field_validator("question")
    @classmethod
    def _question_is_trimmed(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


class AskResponse(ContractModel):
    contract_version: str = "1.0.0"
    run_id: str = Field(min_length=1)


RunStatus = Literal[
    "answered",
    "clarify",
    "refused",
    "blocked",
    "insufficient_evidence",
    "error",
]
ClaimKind = Literal[
    "fact",
    "concentration",
    "co_movement",
    "comparison",
    "consistent_with",
    "hypothesis",
]
FactCheckViolationKind = Literal[
    "number_not_in_ledger",
    "causal_language_without_grade4",
    "claim_without_source",
    "grade_exceeded",
]
FactCheckAction = Literal["pass", "repaired", "template_fallback"]


class ClaimNumber(ContractModel):
    token: str = Field(min_length=1)
    value: float
    unit: str | None = None


class ClaimSource(ContractModel):
    type: Literal["query", "artifact"]
    id: str = Field(min_length=1)


class LedgerClaim(ContractModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    numbers: tuple[ClaimNumber, ...] = ()
    source: ClaimSource
    grade: int = Field(ge=0, le=4)
    kind: ClaimKind


class DroppedClaim(ContractModel):
    text: str = Field(min_length=1)
    reason: Literal["no_source", "grade_too_low_for_wording"]


class Ledger(ContractModel):
    run_id: str = Field(min_length=1)
    claims: tuple[LedgerClaim, ...] = ()
    dropped: tuple[DroppedClaim, ...] = ()
    hypotheses: tuple[str, ...] = ()


class FactCheckViolation(ContractModel):
    sentence: str = Field(min_length=1)
    kind: FactCheckViolationKind
    token: str | None = None
    claim_id: str | None = None


class FactCheckResult(ContractModel):
    passed: bool
    violations: tuple[FactCheckViolation, ...] = ()
    repaired_narrative: str | None = None
    action: FactCheckAction

    @model_validator(mode="after")
    def _action_matches_violations(self) -> FactCheckResult:
        if self.passed and self.violations:
            raise ValueError("a passing fact check cannot carry violations")
        if not self.passed and not self.violations:
            raise ValueError("a failed fact check needs at least one violation")
        return self


class EnvelopeScope(ContractModel):
    metric: str | None = None
    window: str | None = None
    filters: tuple[str, ...] = ()
    grain: str | None = None
    data_range: str | None = None
    governed: bool = False


class EnvelopeQueryRecord(ContractModel):
    query_id: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    status: Literal["ok", "rejected", "error"]
    duration_ms: int = Field(ge=0)
    rows_scanned: int | None = Field(default=None, ge=0)
    est_cost: float | None = Field(default=None, ge=0)
    origin: Literal["compiler", "generator", "repair"]
    repair_of: str | None = None
    validation_mode: ValidationMode | None = None


class EvidenceBlock(ContractModel):
    module: Literal["lookup", "anomaly", "driver", "risk"]
    output: Any
    source_claims: tuple[str, ...] = ()


class ActionOption(ContractModel):
    action_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rank: int = Field(ge=1)
    assumptions: tuple[str, ...] = ()
    trade_offs: tuple[str, ...] = ()
    sensitivity: str = ""
    monitor: tuple[str, ...] = ()
    data_that_would_change_ranking: tuple[str, ...] = ()
    kind: Literal["intervention", "information_gathering"]


class MethodStep(ContractModel):
    name: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class RouteSummary(ContractModel):
    labels: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


class RefusalBlock(ContractModel):
    missing: tuple[str, ...] = ()
    closest_answerable: str | None = None


class BlockBlock(ContractModel):
    reason: GuardReason
    detail: str = Field(min_length=1)


class RunMetrics(ContractModel):
    latency_ms: int = Field(ge=0)
    tokens: int = Field(ge=0)
    queries: int = Field(ge=0)
    rows: int = Field(ge=0)
    retries: int = Field(default=0, ge=0)


class Provenance(ContractModel):
    model_name: str = ""
    model_version: str = ""
    commit: str = ""
    snapshot_id: str = ""
    catalog_version: str = ""
    timestamp: str = Field(min_length=1)


class AnswerEnvelope(ContractModel):
    contract_version: str = "1.0.0"
    run_id: str = Field(min_length=1)
    status: RunStatus
    route: RouteSummary
    conclusion: str | None = None
    scope: EnvelopeScope = Field(default_factory=EnvelopeScope)
    evidence: tuple[EvidenceBlock, ...] = ()
    claims: tuple[LedgerClaim, ...] = ()
    method: tuple[MethodStep, ...] = ()
    queries: tuple[EnvelopeQueryRecord, ...] = ()
    caveats: tuple[str, ...] = ()
    causal_boundary_note: str | None = None
    next_actions: tuple[ActionOption, ...] = ()
    clarification: ClarificationResult | None = None
    refusal: RefusalBlock | None = None
    block: BlockBlock | None = None
    run_metrics: RunMetrics
    provenance: Provenance


__all__ = [
    "AllowlistedColumn",
    "ClarificationResult",
    "IntendedColumn",
    "ModelUsage",
    "RepairAttempt",
    "RepairError",
    "RepairErrorKind",
    "RepairOutcome",
    "RepairRequest",
    "SchemaAllowlist",
    "SqlCandidate",
    "SqlOrigin",
    "AnswerabilityResult",
    "ColumnRole",
    "ContractModel",
    "EstimatedCost",
    "ExecutionColumn",
    "ExecutionError",
    "ExecutionErrorKind",
    "ExecutionResult",
    "ExecutionStatus",
    "GatewayConfig",
    "GuardReason",
    "GuardResult",
    "JoinCardinality",
    "LinkedValue",
    "MetricAllowedDimension",
    "MetricCoverage",
    "MetricDefinition",
    "MetricFilter",
    "MetricFilterOperator",
    "MetricJoinPath",
    "MetricReconciliation",
    "MetricResolution",
    "MetricTimeGrain",
    "Period",
    "ReconciliationCheck",
    "ReconciliationCheckName",
    "ReconciliationCheckStatus",
    "ReconciliationComparison",
    "ReconciliationResult",
    "ReconciliationStatus",
    "ResolvedDimension",
    "PerceptionResult",
    "PerceptorConfig",
    "ValidationCheck",
    "ValidationCheckName",
    "ValidationCheckStatus",
    "ValidationMode",
    "ValidationResult",
    "AnalystArtifact",
    "AnalystColumn",
    "AnalystColumnRole",
    "AnalystInput",
    "AnalystOutput",
    "AnalystStatus",
    "AnomalyParams",
    "AnomalyPersistence",
    "AnomalyResult",
    "AnomalyVerdict",
    "BudgetPolicy",
    "BudgetUsage",
    "ClassifierSignal",
    "ChurnProcessMetadata",
    "Confounder",
    "DriverContribution",
    "DriverResult",
    "ExecutionBudget",
    "GroundTruthManifest",
    "GroundTruthSplit",
    "InsufficientEvidenceCase",
    "IntentLabel",
    "ModelRouteSignal",
    "NegativeControl",
    "NegativeControlKind",
    "OrchestrationResult",
    "OrchestrationStatus",
    "PlantedAnomaly",
    "PlantedAnomalyKind",
    "PlantedDriver",
    "PlantedDriverCauseKind",
    "PlanStep",
    "PlanStepStatus",
    "QueryRecord",
    "RouteLabel",
    "RouteSlots",
    "RouterResult",
    "RouterSignals",
    "RulesSignal",
    "SlotFilter",
    "TableRef",
    "TimeSlot",
    "TrueRiskSegment",
    "TruthUnit",
    "ActionOption",
    "AnswerEnvelope",
    "AskRequest",
    "AskResponse",
    "BlockBlock",
    "ClaimKind",
    "ClaimNumber",
    "ClaimSource",
    "DroppedClaim",
    "EnvelopeQueryRecord",
    "EnvelopeScope",
    "EvidenceBlock",
    "FactCheckAction",
    "FactCheckResult",
    "FactCheckViolation",
    "FactCheckViolationKind",
    "Ledger",
    "LedgerClaim",
    "MethodStep",
    "Provenance",
    "RefusalBlock",
    "RouteSummary",
    "RunMetrics",
    "RunStatus",
]
