"""Discovery intent provider backing questions D1-D10 (SAFE-8, scope.md section 3.1).

Answers catalog, schema, dimension, metric, and data availability questions
purely from governed metadata without evaluating dynamic language model numbers.
"""

from __future__ import annotations

from typing import Any

from contracts.v2 import CatalogFact, CatalogFactsPayload

from .completeness import LAST_COMPLETE_MONTH
from .tables import REAL_TABLE_NAMES, SYNTHETIC_TABLE_NAMES, TABLES

CATALOG_VERSION = "2026.10.1"


class DiscoveryService:
    """Answers discovery inquiries from catalog facts."""

    def __init__(self, catalog_version: str = CATALOG_VERSION) -> None:
        self.catalog_version = catalog_version

    def answer_discovery(self, question: str) -> dict[str, Any]:
        """Dispatch discovery question to deterministic catalog handler."""
        q = question.lower().strip()

        # D1: "What tables do you have?"
        if any(
            w in q
            for w in (
                "what table",
                "what tables",
                "list table",
                "list tables",
                "what data do you have",
            )
        ):
            return self._answer_d1_tables()

        # D2: "What date range is covered?"
        if any(
            w in q for w in ("date range", "time range", "what dates", "time period")
        ):
            return self._answer_d2_date_range()

        # D3: "What metrics are available?"
        if any(
            w in q
            for w in (
                "what metric",
                "what metrics",
                "list metric",
                "list metrics",
                "available kpi",
            )
        ):
            return self._answer_d3_metrics()

        # D4: "What dimensions can I group by?"
        if any(
            w in q
            for w in (
                "what dimension",
                "what dimensions",
                "group by",
                "break down by",
                "slice",
            )
        ):
            return self._answer_d4_dimensions()

        # D5: "What synthetic data is present?"
        if any(
            w in q
            for w in ("synthetic data", "what synthetic", "simulated", "generated data")
        ):
            return self._answer_d5_synthetic()

        # D6: "How many customers are in the dataset?"
        if any(
            w in q
            for w in (
                "how many customer",
                "how many customers",
                "customer volume",
                "number of customer",
            )
        ):
            return self._answer_d6_customer_count()

        # D7: "What is the primary key of customer_segments?"
        if "customer_segments" in q and any(
            w in q for w in ("primary key", "key", "identifier", "join")
        ):
            return self._answer_d7_customer_segments_key()

        # D8: "What carrier data is tracked?"
        if any(
            w in q
            for w in ("carrier", "carriers", "delivery_sla", "sla", "logistics carrier")
        ):
            return self._answer_d8_carrier_data()

        # D9: "What analytical tables are precomputed?"
        if any(
            w in q
            for w in (
                "analytical table",
                "analytical tables",
                "precomputed",
                "pre-computed",
            )
        ):
            return self._answer_d9_analytical_tables()

        # D10: Out of scope request (e.g. credit score, demographic survey)
        if any(
            w in q
            for w in (
                "credit score",
                "survey",
                "demographic",
                "income",
                "social security",
                "cpf",
            )
        ):
            return self._answer_d10_refusal(question)

        # Default fallback: general tables & metrics summary
        return self._answer_d1_tables()

    def _answer_d1_tables(self) -> dict[str, Any]:
        facts = [
            CatalogFact(
                key=t.name,
                value={
                    "grain": t.grain,
                    "is_synthetic": t.is_synthetic,
                    "description": t.description,
                },
                source="catalog.tables",
            )
            for t in TABLES.values()
            if not t.is_analytical
        ]
        real_count = len(REAL_TABLE_NAMES)
        synth_count = len(SYNTHETIC_TABLE_NAMES)
        total_count = real_count + synth_count

        narrative = (
            f"The warehouse contains {total_count} tables: {real_count} real Olist e-commerce snapshot tables "
            f"and {synth_count} synthetic operational indicator tables. "
            f"Synthetic tables are clearly catalog-labeled (is_synthetic=True)."
        )

        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=tuple(facts)
            ),
            "tables_count": total_count,
        }

    def _answer_d2_date_range(self) -> dict[str, Any]:
        facts = (
            CatalogFact(
                key="order_history_start", value="2016-09-04", source="catalog.temporal"
            ),
            CatalogFact(
                key="order_history_end", value="2018-10-17", source="catalog.temporal"
            ),
            CatalogFact(
                key="last_complete_month",
                value=LAST_COMPLETE_MONTH,
                source="semantic.completeness",
            ),
            CatalogFact(
                key="synthetic_layer_range",
                value="2016-10-01 to 2018-08-31",
                source="catalog.temporal",
            ),
        )
        narrative = (
            f"The real Olist order history covers 2016-09-04 to 2018-10-17. "
            f"However, per the completeness rule (V2-DATA-1), the last complete month is {LAST_COMPLETE_MONTH}. "
            f"The synthetic indicator layer spans 2016-10-01 to 2018-08-31."
        )
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d3_metrics(self) -> dict[str, Any]:
        metrics_list = [
            ("revenue", "sum", "Total delivered sales revenue (excl. freight)"),
            ("gmv", "sum", "Gross merchandise volume including freight"),
            ("order_count", "count", "Distinct delivered order count"),
            ("aov", "ratio", "Average order value (revenue / order_count)"),
            (
                "cancellation_rate",
                "ratio",
                "Canceled orders divided by total orders placed",
            ),
            ("review_score", "mean", "Customer satisfaction review rating (1 to 5)"),
            ("marketing_spend", "sum", "Synthetic daily advertising expenditure"),
            ("conversion_rate", "ratio", "Synthetic web session order conversion rate"),
            ("stockout_rate", "ratio", "Synthetic product stockout frequency"),
            ("delivery_delay", "mean", "Synthetic carrier transit days over promise"),
        ]
        facts = tuple(
            CatalogFact(
                key=m[0],
                value={"aggregation": m[1], "description": m[2]},
                source="catalog.metrics",
            )
            for m in metrics_list
        )
        narrative = (
            f"The semantic layer governs {len(metrics_list)} key metrics with declared aggregation classes "
            f"(sum, count, mean, ratio) across real and synthetic layers."
        )
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d4_dimensions(self) -> dict[str, Any]:
        dims = (
            CatalogFact(
                key="customer_state",
                value="27 Brazilian states (SP, RJ, MG...)",
                source="catalog.dimensions",
            ),
            CatalogFact(
                key="product_category",
                value="71 translated category names",
                source="catalog.dimensions",
            ),
            CatalogFact(
                key="payment_type",
                value="credit_card, boleto, voucher, debit_card",
                source="catalog.dimensions",
            ),
            CatalogFact(
                key="channel",
                value="paid_search, organic_search, social, email, direct",
                source="catalog.dimensions",
            ),
            CatalogFact(
                key="carrier",
                value="correios_pac, correios_sedex, loggi_express, carrier_sul",
                source="catalog.dimensions",
            ),
        )
        narrative = "Governed dimensions for grouping include customer_state, product_category, payment_type, channel, and carrier."
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=dims
            ),
        }

    def _answer_d5_synthetic(self) -> dict[str, Any]:
        synth_tables = [t for t in TABLES.values() if t.is_synthetic]
        facts = tuple(
            CatalogFact(key=t.name, value=t.description, source="catalog.synthetic")
            for t in synth_tables
        )
        narrative = (
            f"The synthetic layer provides {len(synth_tables)} operational indicator tables: "
            + ", ".join(t.name for t in synth_tables)
            + ". All synthetic tables are keyed to real Olist entities and flagged is_synthetic=True."
        )
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d6_customer_count(self) -> dict[str, Any]:
        facts = (
            CatalogFact(
                key="total_customer_records", value=99441, source="catalog.row_counts"
            ),
            CatalogFact(
                key="unique_customers", value=96096, source="catalog.row_counts"
            ),
        )
        narrative = "The dataset holds 99,441 customer order instances representing 96,096 unique customer entities (customer_unique_id)."
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d7_customer_segments_key(self) -> dict[str, Any]:
        facts = (
            CatalogFact(
                key="primary_key", value="customer_unique_id", source="catalog.schema"
            ),
            CatalogFact(
                key="foreign_key_target",
                value="customers.customer_unique_id",
                source="catalog.schema",
            ),
            CatalogFact(
                key="caveat",
                value="Do not join customer_segments on customer_id (order-level instance).",
                source="semantic.rules",
            ),
        )
        narrative = (
            "The primary key for customer_segments is customer_unique_id, identifying unique individuals. "
            "It must not be joined on customer_id, which represents single order instances."
        )
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d8_carrier_data(self) -> dict[str, Any]:
        facts = (
            CatalogFact(key="table", value="delivery_sla", source="catalog.schema"),
            CatalogFact(
                key="tracked_carriers",
                value="correios_pac, correios_sedex, loggi_express, carrier_sul",
                source="catalog.entities",
            ),
            CatalogFact(
                key="metrics",
                value="promised_days, actual_days, sla_breach_flag",
                source="catalog.schema",
            ),
        )
        narrative = "Carrier delivery performance is tracked in delivery_sla covering carriers such as correios_pac, correios_sedex, loggi_express, and carrier_sul."
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d9_analytical_tables(self) -> dict[str, Any]:
        an_tables = [t for t in TABLES.values() if t.is_analytical]
        facts = tuple(
            CatalogFact(key=t.name, value=t.description, source="catalog.analytical")
            for t in an_tables
        )
        narrative = (
            "Precomputed analytical tables include: "
            + ", ".join(t.name for t in an_tables)
            + ". They serve low-latency cached reads with engine provenance."
        )
        return {
            "status": "ok",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }

    def _answer_d10_refusal(self, question: str) -> dict[str, Any]:
        facts = (
            CatalogFact(
                key="missing_attributes",
                value="income, credit_score, demographic_survey",
                source="catalog.guard",
            ),
            CatalogFact(
                key="held_attributes",
                value="customer_city, customer_state, customer_zip_code_prefix",
                source="catalog.schema",
            ),
        )
        narrative = (
            "The warehouse does not contain customer credit scores, personal income, or demographic survey data. "
            "Available customer attributes are limited to customer_state, customer_city, customer_zip_code_prefix, and synthetic behavioral segments."
        )
        return {
            "status": "refused",
            "narrative": narrative,
            "facts_payload": CatalogFactsPayload(
                catalog_version=self.catalog_version, facts=facts
            ),
        }
