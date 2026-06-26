# models

One folder per layer. See `../docs/layering.md` for what belongs in each.

- `staging/` — source cleanup (views)
- `base/` — first logic, dedup, unions (views)
- `core/` — facts & dimensions, enforced grain (tables)
- `intermediate/` — multi-step transforms / features (views)
- `marts/` — app-ready consumption tables (tables)
