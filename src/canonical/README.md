# Canonical value contract, v1

This package depends only on the standard library. It does not import `Nomina`,
parsers, repositories, SQLite or UI code. It defines no economic aggregation.

## Exact values

`ExactDecimal(coefficient, scale)` represents `coefficient × 10^(-scale)`.
Scale is an integer in 0..9; the **normalized** coefficient is a signed 64-bit
integer. These are portable contract limits, not database-dependent checks.
Booleans and floats are rejected. Trailing fractional zeros are removed exactly;
all zero representations become `(0, 0)`. Equality is numeric: `1.20 == 1.2`.
Original printed notation must be preserved separately by future document facts.

`from_decimal` and `to_decimal` do not depend on Decimal context precision.
Conversion never rounds. Extra fractional zeros may be removed, but an additional
significant decimal place or an out-of-range coefficient raises `ValueError`.

`from_text` accepts an optional sign, ASCII digits and an optional fractional
part. The separator defaults to `.`; comma requires `decimal_separator=","`.
No whitespace, grouping separators, scientific notation or locale guessing is
accepted. Use `from_decimal` for an already parsed finite Decimal.

`CurrencyCode` validates three uppercase ASCII letters, not membership of an
external currency registry. An absent currency stays `None`, never implicit EUR.

## State and candidate

`CanonicalValue` is immutable and keyword-only. Its value is `ExactDecimal`, text
or `None`. A plain int/float/Decimal is not silently converted.

| State | Value | Reason |
| --- | --- | --- |
| present | Required; zero and empty text are values | Optional |
| technical_null | None | Optional |
| not_extracted | None | Optional |
| not_present | None | Optional |
| not_applicable | None | Required |
| unknown | None | Optional |
| unreliable | Optional candidate | Required |

Reasons are lowercase dotted identifiers, e.g. `source.conflict`. Currency may
be known for an absent amount but cannot accompany text. A numeric value without
currency does not assert monetary eligibility; that belongs to later semantics.

## Identity bytes

`canonical_bytes` returns compact UTF-8 JSON with the envelope
`{"contract":"canonical","value":TAGGED_TREE,"version":1}`. Keys are sorted;
strings are not Unicode-normalized. Surrogates that cannot encode as UTF-8 fail.

The tree is tagged at **every** node:

- `None`: `["null"]`
- bool: `["bool", value]`
- int: `["int", decimal_string]`
- str: `["str", value]`
- decimal: `["decimal", coefficient_string, scale]`
- currency: `["currency", code]`
- ID: `["id", full_string]`
- value state / ID namespace: `["value_state", value]` / `["id_namespace", value]`
- list: `["list", [encoded_items...]]`
- dict: `["map", [[plain_string_key, encoded_value]...]]`, sorted by Unicode code point
- canonical value: `["canonical_value", encoded_map_of_all_four_fields]`

Only plain lists/dicts and the documented types are supported; no generic
dataclass conversion, `repr`, float, tuple/set or arbitrary-object fallback.
Cycles fail; repeated references to acyclic values are allowed. An ID and a plain
string with the same characters intentionally have different identity bytes.
User data cannot impersonate a type tag by supplying a dict or list.

The v1 format is pinned by golden tests. Any encoding change requires a new
contract version and an explicit compatibility decision; do not silently change
v1. This increment does not provide deserialization or entity-specific policies.

## Hashes and IDs

`sha256_bytes` hashes bytes. `canonical_sha256` hashes the versioned encoding.
`deterministic_id(namespace, content)` produces
`namespace:sha256:<64 lowercase hex digits>`. The hash preimage is the canonical
encoding of `{"namespace": str(namespace), "content": content}`.

Namespaces match `[a-z][a-z0-9_]{0,63}`. `IdNamespace` lists the initial entity
names; additional valid namespaces are possible. `CanonicalId` is a validated
immutable string. Syntax alone proves neither existence nor correct entity
identity. No generated-person registry or PDF identity policy is implemented.

`ReproducibilityConflict` is the reusable error for an identity associated with
different content. Comparison and persistence policies belong to later increments.
