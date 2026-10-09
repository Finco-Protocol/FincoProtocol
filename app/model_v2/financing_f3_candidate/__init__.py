"""NON-AUTHORITATIVE Financing F3 candidate contracts (design evidence only).

This package is a *specification prototype*.  It is NOT a financial authority:

* it is not imported by the engine, the Run path, persistence, the workbook, the UI or any route;
* its objects are never persisted as live financing inputs and never enter any Run fingerprint;
* it computes no financial result (no interest, no draw allocation, no Sources & Uses);
* it does not activate or imply multi-tranche economics — the single-Senior canonical path is unchanged.

A future canonical financing-instrument authority belongs in a reviewed ``finco_core`` namespace
(see docs/model_v2/financing_f3/F3_TYPED_CONTRACT_SPEC.md).  Tests pin the isolation.
"""
NON_AUTHORITATIVE = True
SCHEMA_VERSION = "f3-candidate-0.1"
