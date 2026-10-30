# Synthetic Ground Truth Answer Key (V2 Evaluation)

> **CONFIDENTIAL / EVALUATION ONLY** (DATA-4, DATA-9)
> This document records the planted causal mechanisms, windows, effect sizes,
> and confounders across the synthetic data layer (`brazil_ecommerce_v2.sqlite`).
> Agents must never read this document during live reasoning.

## Summary of Planted Effects

| ID | Name | Window | Table | Dimension | Expected Effect Size | Recovery Engine | Confounder |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **E1** | Marketing Cut | `2018-03 to 2018-05` | `marketing_spend` | channel='paid_search', customer_state in ('SP', 'RJ') | Spend -40.0%, Sessions -18.0% | `driver` | Category-mix shift in computers_accessories channel spend during the same period. |
| **E2** | Top-Category Stockouts | `2017-11 to 2017-12` | `inventory_daily` | product_category in ('bed_bath_table', 'health_beauty', 'sports_leisure') | Stockout rate 25.0% in peak window, ~12% item volume suppression | `driver` | Black-Friday seasonal demand surge in late November (2017-11-24 to 2017-11-27). |
| **E3** | Promo AOV Dilution | `2018-01 to 2018-02` | `promotions` | discount_pct=0.20 | Order Count +15.0%, AOV -12.0%, GMV ~0.0% change | `driver` | Payment method mix shift toward boleto payment options. |
| **E4** | Delivery Delay Spike | `2018-06` | `delivery_sla` | carrier='carrier_sul', customer_state in ('RS', 'SC', 'PR') | Actual delivery days +11, SLA breach rate 35.0%, Review score drop -0.80 | `anomaly` | Simultaneous increase in average regional freight costs due to expedited rerouting. |
| **E5** | Price Elasticity Shift | `2018-04 to 2018-06` | `price_history` | product_category='telefonia' | List price +10.0%, Unit volume -15.0%, Elasticity -1.50 | `scenario` | Competitor price movement (+8%) lagged by 1 week. |

## Detailed Effect Specifications

### E1: Marketing Cut
- **Target Window:** `2018-03 to 2018-05`
- **Target Table:** `marketing_spend`
- **Dimension Filter:** `channel='paid_search', customer_state in ('SP', 'RJ')`
- **True Mechanism:** Paid-search marketing spend reduced by 40% in SP and RJ; traffic follows with a ~2-week lag.
- **Expected Effect Size:** Spend -40.0%, Sessions -18.0%
- **Recovery Engine:** `driver`
- **Planted Confounder:** Category-mix shift in computers_accessories channel spend during the same period.
- **Parameters:** `{"spend_reduction": 0.4, "lag_days": 14, "states": ["SP", "RJ"], "channel": "paid_search"}`

### E2: Top-Category Stockouts
- **Target Window:** `2017-11 to 2017-12`
- **Target Table:** `inventory_daily`
- **Dimension Filter:** `product_category in ('bed_bath_table', 'health_beauty', 'sports_leisure')`
- **True Mechanism:** 25% of catalog items in top 3 categories marked out-of-stock (stockout_flag=1), suppressing item volume.
- **Expected Effect Size:** Stockout rate 25.0% in peak window, ~12% item volume suppression
- **Recovery Engine:** `driver`
- **Planted Confounder:** Black-Friday seasonal demand surge in late November (2017-11-24 to 2017-11-27).
- **Parameters:** `{"target_categories": ["bed_bath_table", "health_beauty", "sports_leisure"], "stockout_ratio": 0.25, "window_start": "2017-11-15", "window_end": "2017-12-15"}`

### E3: Promo AOV Dilution
- **Target Window:** `2018-01 to 2018-02`
- **Target Table:** `promotions`
- **Dimension Filter:** `discount_pct=0.20`
- **True Mechanism:** 20% discount across major categories lifts order count by ~15% while AOV drops by ~12%, GMV remains flat.
- **Expected Effect Size:** Order Count +15.0%, AOV -12.0%, GMV ~0.0% change
- **Recovery Engine:** `driver`
- **Planted Confounder:** Payment method mix shift toward boleto payment options.
- **Parameters:** `{"discount_pct": 0.2, "order_lift": 0.15, "aov_drop": -0.12, "promo_id": "PROMO_2018_SUMMER_DEAL"}`

### E4: Delivery Delay Spike
- **Target Window:** `2018-06`
- **Target Table:** `delivery_sla`
- **Dimension Filter:** `carrier='carrier_sul', customer_state in ('RS', 'SC', 'PR')`
- **True Mechanism:** Regional logistics congestion for carrier_sul increases transit days by +11, driving SLA breach to 35% with lagged review score drop.
- **Expected Effect Size:** Actual delivery days +11, SLA breach rate 35.0%, Review score drop -0.80
- **Recovery Engine:** `anomaly`
- **Planted Confounder:** Simultaneous increase in average regional freight costs due to expedited rerouting.
- **Parameters:** `{"carrier": "carrier_sul", "states": ["RS", "SC", "PR"], "actual_days_increase": 11, "target_month": "2018-06"}`

### E5: Price Elasticity Shift
- **Target Window:** `2018-04 to 2018-06`
- **Target Table:** `price_history`
- **Dimension Filter:** `product_category='telefonia'`
- **True Mechanism:** +10% list price adjustment results in -15% demand reduction; empirical elasticity = -1.50.
- **Expected Effect Size:** List price +10.0%, Unit volume -15.0%, Elasticity -1.50
- **Recovery Engine:** `scenario`
- **Planted Confounder:** Competitor price movement (+8%) lagged by 1 week.
- **Parameters:** `{"category": "telefonia", "price_delta_pct": 0.1, "volume_delta_pct": -0.15, "elasticity": -1.5}`

