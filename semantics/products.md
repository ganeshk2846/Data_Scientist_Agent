# `products`

**Layer:** real — Olist Brazilian e-commerce snapshot, read-only, never modified (`V2-SYN-1`).

Product attributes.

**Grain:** product.

## Columns

| Column | Meaning | Unit |
| --- | --- | --- |
| `product_id` | Product key. | text |
| `product_category_name` | Portuguese category name (71 values; some null). The `category` key of the synthetic tables. | text |
| `product_name_lenght` | Length of the product name (sic: the source misspells *length*). | characters |
| `product_description_lenght` | Length of the description (sic). | characters |
| `product_photos_qty` | Number of photos. | count |
| `product_weight_g` | Weight. | grams |
| `product_length_cm` | Length. | cm |
| `product_height_cm` | Height. | cm |
| `product_width_cm` | Width. | cm |

## Join keys

- `products.product_id = order_items.product_id` (1:N)
- `products.product_category_name = product_category_translation.product_category_name` (N:1)
- `products.product_id = price_history.product_id` (1:N, synthetic)

## Caveats

- Category names are Portuguese; translate through `product_category_translation` for display.
