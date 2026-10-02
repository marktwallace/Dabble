from dataclasses import dataclass, field


@dataclass
class SessionState:
    """Tool state for one conversation.

    Held by ClaudeHandler so the tool loop runs without Streamlit. The
    conversation page points st.session_state at these same objects, so the
    rendering code and the review pages read what the tools wrote.
    """

    analytic_db: object = None
    dataframes: dict = field(default_factory=dict)
    figures: dict = field(default_factory=dict)
    artifact_order: list = field(default_factory=list)
    tables_to_show: list = field(default_factory=list)
    shown_dataframes: set = field(default_factory=set)
    exported_files: dict = field(default_factory=dict)
