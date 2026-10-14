"""Original, deterministic FINCO example; not market data or saved assumptions."""
def example(start="2028-01-01T00:00:00Z", end="2028-01-03T00:00:00Z"):
    return {
        "version": 1, "technology": "STANDALONE_GRID_BESS", "time_convention": "UTC_HOURLY_END_EXCLUSIVE",
        "degradation_convention": "ADDITIVE_CALENDAR_ACT365_AND_CYCLE",
        "efc_convention": "DC_TWO_WAY_OVER_2_NOMINAL_USABLE", "cohort_policy": "AGGREGATE_DC_POOL_NOMINAL_CYCLE_ALLOCATION",
        "outage_policy": "SUSPEND_FIXED_PLAN_VALIDATE_EXPLICIT", "price_unit": "EUR_PER_MWH",
        "settlement_policy": "CANONICAL_FINANCIAL_PERIOD_END", "information_policy": "USER_DECLARED_EX_ANTE_FIXED_PLAN",
        "source_ref": "finco-original-synthetic-plan", "start": start, "end": end,
        "battery": {"charge_power_mw": 1, "discharge_power_mw": 1, "grid_import_limit_mw": 1.1,
            "grid_export_limit_mw": 1, "installed_energy_mwh": 2.5, "usable_energy_mwh": 2,
            "duration_hours": 2, "soc_min": 0, "soc_max": .9, "initial_energy_mwh": 0, "terminal_energy_mwh": 0,
            "charge_efficiency": .9, "discharge_efficiency": .9, "round_trip_efficiency": .81,
            "calendar_loss_per_year": .01, "cycle_loss_per_efc": .00001, "minimum_soh": .6, "useful_life_years": 5},
        "dispatch_mode": "FIXED_DAILY_PLAN", "dispatch": [
            {"utc_hour": hour, "charge_mw": 1 if hour == 2 else 0, "discharge_mw": .81 if hour == 20 else 0,
             "auxiliary_grid_mw": .01, "available": True, "buy_price_eur_mwh": 40, "sell_price_eur_mwh": 100,
             "import_charge_eur_mwh": 2, "export_charge_eur_mwh": 1, "source_ref": "finco-original-hourly-assumption"}
            for hour in range(24)], "outages": [], "events": [],
    }
