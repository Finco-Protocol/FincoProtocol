"""Shared UI components for FINCO Model."""
from typing import Any

from app.streamlit_compat import require_streamlit

STATUS_LABELS = {
    "ok": "✅ Full model",
    "full": "✅ Full model",
    "partial": "⚠️ Partial integration",
    "experimental": "🧪 Experimental",
    "placeholder": "⏳ Placeholder",
    "warning": "⚠️ Warning",
    "error": "❌ Error",
}

def status_badge(label: str, status: str) -> None:
    """Render a status badge with label and colored text."""
    st = require_streamlit("app.ui.components")
    emoji_label = STATUS_LABELS.get(status, status)
    if status in ("ok", "full"):
        color = "green"
    elif status in ("partial", "warning"):
        color = "orange"
    elif status in ("experimental", "placeholder"):
        color = "blue"
    else:
        color = "red"
    st.markdown(f"**{label}:** :{color}[{emoji_label}]")

def kpi_card(label: str, value: Any, help_text: str | None = None, status: str | None = None) -> None:
    """Render a single KPI metric card."""
    st = require_streamlit("app.ui.components")
    if value is None:
        value = "n/a"
    if status:
        emoji_label = STATUS_LABELS.get(status, status)
        if status in ("ok", "full"):
            color = "green"
        elif status in ("partial", "warning"):
            color = "orange"
        elif status in ("experimental", "placeholder"):
            color = "blue"
        else:
            color = "red"
        st.markdown(f"**{label}:** :{color}[{emoji_label}]  \nValue: {value}")
    else:
        st.metric(label=label, value=value)

def render_warning_list(messages: list[str]) -> None:
    """Display a list of warning/info messages."""
    st = require_streamlit("app.ui.components")
    for msg in messages:
        if msg.startswith("⚠️"):
            st.warning(msg)
        elif msg.startswith("❌"):
            st.error(msg)
        else:
            st.info(msg)

def format_metric_value(value: Any, kind: str | None = None) -> str:
    """Format a numeric value for display.

    kind: 'currency', 'percent', 'ratio', 'number', or None (auto-detect)
    """
    if value is None:
        return "n/a"
    try:
        val = float(value)
    except (TypeError, ValueError):
        return str(value)

    if kind is None:
        if abs(val) < 1 and val != 0:
            kind = "percent"
        elif abs(val) >= 1_000_000:
            kind = "currency"
        elif abs(val) < 100:
            kind = "ratio"
        else:
            kind = "number"

    if kind == "currency":
        if abs(val) >= 1_000_000:
            return f"{val/1_000_000:.1f}M"
        elif abs(val) >= 1_000:
            return f"{val/1_000:.0f}k"
        return f"{val:.0f}"
    elif kind == "percent":
        return f"{val*100:.2f}%"
    elif kind == "ratio":
        return f"{val:.3f}"
    elif kind == "number":
        return f"{val:.2f}"
    return str(value)

def render_dataframe_with_download(df, label: str, filename: str) -> None:
    """Render a dataframe with a CSV download button."""
    st = require_streamlit("app.ui.components")
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv().encode("utf-8")
    st.download_button(
        label=f"Download {label} CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
    )
