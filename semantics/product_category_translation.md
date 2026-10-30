# Table: product_category_translation

- **Data Layer:** Real
- **Grain:** category
- **Primary / Composite Key:** product_category_name
- **Synthetic Flag:** False

## Description
Mapping table translating Portuguese category names to standard English names.

## Caveats & Usage Rules
- Governed joins must match approved keys (product_category_name).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
