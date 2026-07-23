# 0006 — Use a secure view for column masking, not a masking policy

Status: accepted
Date: 2026-07-23

## Context

The plan was to protect sensitive columns with Snowflake's Dynamic Data Masking: attach a
masking policy to a column, and Snowflake resolves it per role at query time. It is the
right tool, and it is what a production account would use.

Applying it failed with `Unsupported feature 'MASKING POLICY'`. Dynamic Data Masking is
an Enterprise Edition feature, and the trial account backing this project is Standard.
This is an account entitlement, not something configuration can work around.

A second thing worth stating plainly: the generated data contains no personal data at
all. Suppliers are companies. There is no RGPD obligation over this dataset. What the
mechanism protects here is commercially sensitive information — what a supplier charges
and how reliable they are is leverage in a negotiation, and analysts building reports have
no need for it.

## Decision

Reach the same outcome with a secure view, `dim_suppliers_secure`, which resolves the
sensitive columns against `current_role()`. Privileged roles see real values; everyone
else sees `*** RESTRICTED ***` for the supplier name and null for the reliability score.
The banded `reliability_tier` stays visible, because that is what reporting actually needs.

The view is marked `secure`. An ordinary view can leak filtered-out data through query
plans and error messages; a secure view closes those side channels at some cost to
optimisation, which is the right trade when the filtering is the entire purpose.

It is disabled on DuckDB via `enabled = (target.type == 'snowflake')`, since DuckDB has
neither roles nor secure views.

## Consequences

Verified working: querying the view as `NOVASUPPLY_TRANSFORMER` returns real supplier
names and scores, and as `NOVASUPPLY_ANALYST` returns restricted values, from the same
view definition.

The limitation compared to a masking policy is real and worth being honest about. A
masking policy attaches to the *column*, so it protects that column everywhere it is
queried, including the base table. A secure view only protects whoever is pointed at the
view — an analyst granted access to `dim_suppliers` directly would see everything. Access
control has to keep the two consistent, whereas a masking policy is enforced centrally.

If the account were upgraded to Enterprise, the migration would be to create the policies
and attach them to `dim_suppliers`, then drop this view. Nulling rather than zeroing the
masked numeric is deliberate either way: a fake zero silently corrupts any average
computed over it, while a null is visibly absent.
