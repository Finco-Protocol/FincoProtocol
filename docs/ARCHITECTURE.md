# Architecture

FINCO Protocol separates product surfaces from deterministic financial authority.

## FINCO Model

The model stack is layered:

1. typed project inputs,
2. deterministic financial-engine calculations,
3. scenario / persistence services,
4. read-only presentation and export adapters,
5. FastAPI / HTMX application surfaces.

User-facing AI or natural-language interfaces must not become calculation authority. They may translate intent into typed inputs or explain deterministic outputs.

## FINCO Radar

Radar is a separate market-intelligence stack. It must not introduce blockchain polling, quote routing, wallet state, or token-market dependencies into the classic project-finance engine.

## Reference data

Public references use only synthetic Generic Market A/B/C assumptions. Real client or source-workbook lineage is not part of the corporate repository.
