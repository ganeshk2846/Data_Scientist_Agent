# Table: order_payments

- **Data Layer:** Real
- **Grain:** payment_installment
- **Primary / Composite Key:** order_id, payment_sequential
- **Synthetic Flag:** False

## Description
Payment transaction records by method (credit card, boleto, voucher) and installment.

## Caveats & Usage Rules
- Governed joins must match approved keys (order_id, payment_sequential).
- For customer analytics, group by customer_unique_id.
- Period completeness applies (2018-08 last complete month).
