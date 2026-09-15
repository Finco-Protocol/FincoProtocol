"""
finco_core.exports — Typed export output contract.

Extraction target (V2-5): ExportResult — a fully typed representation of
the financial model output suitable for serialisation to Excel, CSV, or JSON.
Produced from AuditResult; never modifies upstream financial fields.

The export layer depends on finco_core.audit. It has no dependency on
finco_app, finco_ui, or any web framework.
"""
