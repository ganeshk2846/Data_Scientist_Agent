# Reasoning rules

Retrieved into prompts for **reasoning only**. Nothing in this file is a
source of figures: every number in an answer comes from SQL or a registered
engine and is linked to evidence (`SAFE-8`).

1. **Never compute a number.** Choose, plan and explain; let SQL or an engine
   produce every figure. Do not add, divide, round or restate a figure.
2. **Use complete periods.** "Now", "latest" and "this year" mean up to the
   last complete month (2018-08 on the real data). Say so as an assumption.
   Never report 2018-09, 2018-10 or 2016-09 as findings.
3. **Label synthetic data.** If any synthetic table is read, the answer says
   so and names the tables. A synthetic figure is never presented as a
   measurement of the real business.
4. **People are `customer_unique_id`.** `customer_id` is one per order.
5. **Mind the grain.** GMV is item grain, revenue is order grain; do not sum
   payments across an item join.
6. **Ratios and means are not summed.** Re-aggregate numerator and
   denominator; decompose a ratio's change into its parts.
7. **Joins need approval.** Use only governed or approved join edges; an
   ingested table's proposed edges are not approved until a person says so.
8. **Correlation is not cause.** A driver answer states its evidence grade
   and the causal-boundary note. Feature importance is association only.
9. **Answer with stated assumptions.** Prefer a bounded answer with its
   assumptions to a refusal. Refuse only when an input does not exist in
   either layer — for example customer age or gender — and name what *is*
   held instead.
10. **Never read the answer key.** `data/SYNTHETIC_GROUND_TRUTH.md` is for
    scoring code only.
