# Staging Tokenized Markets collector

Staging uses the same authority and append-only contracts as production, but
writes only to the staging canonical venue database. The collector is disabled
in the example environment until an operator performs the one-shot smoke check.

The staging web process and collector must share
`FINCO_VENUE_DB_PATH=/opt/finco_staging/storage/radar/venues_market_observations.db`.

No deployment is performed by this repository change.
