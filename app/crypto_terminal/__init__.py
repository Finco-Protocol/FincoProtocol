"""FINCO Crypto Terminal shared read layer.

Composition/serialization ONLY.  Every authority stays in its existing
canonical module:

    Tokenized Markets  finco_radar.venues.*  +  app.radar_ui.tokenized_*
    Yield              finco_yield.*         (market view / intelligence)
    Radar              app.radar_crypto / app.radar_ui.*
    Entitlement        app.crypto_resource_access / app.crypto_api_access

The UI routers and the read-only crypto API both consume this layer so a
value is computed exactly once per authority — never independently per
router, and never inside templates.
"""
