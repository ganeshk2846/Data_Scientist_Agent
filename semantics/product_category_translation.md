# `product_category_translation`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

Portuguese to English category names.

**Grain:** category.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `product_category_name` | Portuguese name. | text |
| `product_category_name_english` | English name. | text |

## Join keys

- `product_category_name = products.product_category_name` (1:N)

## Caveats

- A couple of categories have no translation.
