"""UI constants for financial charts and KPI display.

Standardized layouts and hover templates for Plotly charts.
"""
import plotly.graph_objects as go

# =============================================================================
# Standard Financial Chart Layout
# =============================================================================

FINANCIAL_CHART_LAYOUT = dict(
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="white",
        font_size=12,
        font_family="monospace",
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    xaxis=dict(showgrid=False),
    yaxis=dict(
        showgrid=True,
        gridcolor="rgba(128,128,128,0.15)",
        zeroline=True,
        zerolinecolor="rgba(128,128,128,0.4)",
    ),
    margin=dict(l=60, r=20, t=40, b=40),
    height=380,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)

# =============================================================================
# Hover Templates
# =============================================================================

KEUR_HOVER = "<b>%{y:,.0f} k€</b><extra>%{fullData.name}</extra>"
PCT_HOVER = "<b>%{y:.2f}x</b><extra>%{fullData.name}</extra>"
MW_HOVER = "<b>%{y:,.1f} MW</b><extra>%{fullData.name}</extra>"
MWh_HOVER = "<b>%{y:,.0f} MWh</b><extra>%{fullData.name}</extra>"
EUR_HOVER = "<b>%{y:,.2f} €/MWh</b><extra>%{fullData.name}</extra>"


# =============================================================================
# Chart Colors
# =============================================================================

COLORS = dict(
    revenue="#2E7D4A",
    opex="#EF4444",
    debt="#3B82F6",
    equity="#8B5CF6",
    dscr="#3498DB",
    lockup="#F59E0B",
    distribution="#10B981",
    tax="#6B7280",
    cfads="#1E40AF",
)


# =============================================================================
# DSCR Threshold Lines
# =============================================================================

DSCR_TARGET = 1.15
DSCR_LOCKUP = 1.10
DSCR_COLORS = dict(
    target="#F59E0B",  # orange
    lockup="#EF4444",  # red
)


def add_dscr_thresholds(fig: go.Figure, yanchor: str = "right") -> go.Figure:
    """Add DSCR target and lockup threshold lines to a figure."""
    fig.add_hline(
        y=DSCR_TARGET,
        line_dash="dash",
        line_color=DSCR_COLORS["target"],
        annotation_text=f"Target {DSCR_TARGET}x",
        annotation_position="right",
    )
    fig.add_hline(
        y=DSCR_LOCKUP,
        line_dash="dash",
        line_color=DSCR_COLORS["lockup"],
        annotation_text=f"Lockup {DSCR_LOCKUP}x",
        annotation_position="right",
    )
    return fig


# =============================================================================
# Standard Chart Config
# =============================================================================

CHART_CONFIG = dict(
    displayModeBar=False,
    responsive=True,
)
