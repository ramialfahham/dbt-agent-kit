# dbt layer rules

Data flows in one direction: **staging → base → core → intermediate → marts.**
A model may only `ref()` its own layer or an earlier one. Putting logic in a
convenient-but-wrong layer is a defect even when the SQL is correct.

## staging (views)
Source cleanup only — one staging model per source table. Rename, cast, light
typing, flatten nested fields. No joins across sources, no dedup, no aggregation,
no business logic.

## base (views)
First business logic: deduplication, unioning sources together, aligning
entities. Reads from staging. Base models stay views.

## core (tables)
The system of record: canonical facts and dimensions, surrogate keys, enforced
grain. Reads from base — never from staging, never re-parses raw. Cross-source
unions do not belong here (they belong in base).

## intermediate (views)
Complex multi-step transforms and feature engineering between core and marts.
Never reads from a mart — the flow goes intermediate → mart, never back.

## marts (tables)
Consumption: denormalised, app-ready tables. No hardcoded tenant / partition /
category identifier in business logic — a mart should work for any partition
unchanged. New metrics, labels, or formats are owner-level decisions.

## Consumption (export scripts / app code, outside dbt)
May select, filter, group, rename, serialise — but **never** compute a metric,
choose a window, derive a result, rank, or map identity. If no mart serves what a
consumer needs, that is a data gap: fix it upstream in dbt, never bridge it in
the consumer.

## Tests
Every model has a grain test (unique + not_null on its key). Every metric has a
range / consistency test. Tests run in CI on every PR and block the merge — they
are the first safety net, ahead of code review.
