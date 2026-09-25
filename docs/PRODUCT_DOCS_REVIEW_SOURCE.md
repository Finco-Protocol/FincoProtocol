# Product Docs review source boundary

The public product-documentation copy in this branch is based on the reviewed
`FINCO_Docs_Review_2026-09-24` draft prepared before implementation.

Implementation rules applied here:

- task-first documentation rather than an engineering specification;
- preserve the reviewed separation between Model, Radar, API and evidence;
- preserve Working vs Last Run semantics;
- describe Solar/Wind as current production modelling verticals and broader
  infrastructure as future work;
- describe Stocks, Crypto and Economy as separate Radar domains;
- keep execution simulation explicitly non-executing (no order submission);
- keep verification claims narrow: deterministic identity/lineage, not truth of
  an external source;
- keep `$FINCO` planned and outside financial/calculation authority;
- do not introduce provider branding into the public Docs surface;
- distinguish repository capability from deployed availability.

This file is implementation provenance only. It does not replace the public
`/docs/start` page and does not introduce a second product authority.
