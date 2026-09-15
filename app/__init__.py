"""Application layer — Streamlit UI integration only.

This layer contains ONLY Streamlit-specific code (@st.cache_data, session state).
Domain layer has NO knowledge of Streamlit.

S2-1: All @st.cache_data moved here from domain/ and utils/
S2-2: WaterfallRunner orchestrator for clean waterfall invocation
S2-3: Typed session schema for cleaner session state management
"""