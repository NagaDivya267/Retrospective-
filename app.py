import streamlit as st
# Create Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "😊 Mood",
    "📊 Sprint Insights",
    "🎯 AI Questions",
    "✅ Action Tracker"
])
with tab1:
    st.subheader("Team Mood Check")
    st.write("Select your mood:")

    col1, col2, col3, col4, col5 = st.columns(5)

    moods = {
        "😡": 1,
        "😟": 2,
        "😐": 3,
        "😊": 4,
        "🚀": 5
    }

    selected_mood = None

    for i, (emoji, value) in enumerate(moods.items()):
        if [col1, col2, col3, col4, col5][i].button(emoji):
            selected_mood = value
            st.session_state["last_mood"] = value

    if "last_mood" in st.session_state:
        mood = st.session_state["last_mood"]

        if mood <= 2:
            st.error("⚠️ Team morale is low")
        elif mood == 3:
            st.warning("🙂 Neutral mood")
        else:
            st.success("🚀 Positive team energy")
if "mood_history" not in st.session_state:
    st.session_state.mood_history = []
if selected_mood:
    st.session_state.mood_history.append(selected_mood)
    if st.session_state.mood_history:
        avg_mood = sum(st.session_state.mood_history) / len(st.session_state.mood_history)

        st.metric("Average Mood", f"{avg_mood:.2f}")

    if avg_mood < 2.5: # type: ignore
        st.error("Team is struggling 😟")
    elif avg_mood < 4: # type: ignore
        st.warning("Team is okay but needs improvement")
    else:
        st.success("Team is performing great 🚀")
import pandas as pd
import os

FILE_NAME = "sprint_data.csv"


def ensure_spill_over_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if all(col in df.columns for col in ["Committed", "Scope Added", "Completed"]):
        df["Spill Over"] = (
            pd.to_numeric(df["Committed"], errors="coerce").fillna(0)
            + pd.to_numeric(df["Scope Added"], errors="coerce").fillna(0)
            - pd.to_numeric(df["Completed"], errors="coerce").fillna(0)
        )
    return df

with tab2:
    import pandas as pd
import streamlit as st

with tab2:
    st.subheader("Sprint Insights Tracker")

    sprint_columns = ["Sprint", "Committed", "Completed", "Scope Added", "Spill Over"]

    # Initialize storage
    if "sprint_df" not in st.session_state:
        st.session_state.sprint_df = pd.DataFrame(
            columns=sprint_columns
        )
        st.session_state.sprint_df = ensure_spill_over_column(st.session_state.sprint_df)

    # Always recompute and reorder columns before rendering so Spill Over is visible.
    st.session_state.sprint_df = ensure_spill_over_column(st.session_state.sprint_df)
    st.session_state.sprint_df = st.session_state.sprint_df.reindex(columns=sprint_columns)

    # ------------------ OPTION 1: CSV Upload ------------------
    st.write("### Upload CSV")
    uploaded_file = st.file_uploader("Upload Sprint Data CSV", type=["csv"])

    if uploaded_file:
        df_uploaded = pd.read_csv(uploaded_file)

        required_cols = ["Sprint", "Committed", "Completed", "Scope Added"]
        if all(col in df_uploaded.columns for col in required_cols):
            st.session_state.sprint_df = ensure_spill_over_column(df_uploaded.tail(6)).reindex(columns=sprint_columns)
            st.success("CSV uploaded successfully!")
        else:
            st.error("CSV must contain: Sprint, Committed, Completed, Scope Added")

    # ------------------ OPTION 2: Manual Entry ------------------
    st.write("### Add Sprint Data Manually")

    sprint_name = st.text_input("Sprint Name")
    committed = st.number_input("Committed Story Points", min_value=0)
    completed = st.number_input("Completed Story Points", min_value=0)
    scope_added = st.number_input("Scope Added", min_value=0)

    if st.button("Add Sprint"):
        if sprint_name:
            new_row = pd.DataFrame([{
                "Sprint": sprint_name,
                "Committed": committed,
                "Completed": completed,
                "Scope Added": scope_added
            }])

            st.session_state.sprint_df = pd.concat(
                [st.session_state.sprint_df, new_row],
                ignore_index=True
            ).tail(6)
            st.session_state.sprint_df = ensure_spill_over_column(st.session_state.sprint_df).reindex(columns=sprint_columns)

            st.success("Sprint added!")

    # ------------------ EDITABLE TABLE ------------------
    st.write("### Edit Sprint Data")

    edited_df = st.data_editor(
        st.session_state.sprint_df,
        num_rows="dynamic",
        column_order=sprint_columns,
        disabled=["Spill Over"],
        use_container_width=True
    )

    st.session_state.sprint_df = ensure_spill_over_column(edited_df).reindex(columns=sprint_columns)

    # ------------------ DELETE OPTION ------------------
    st.write("### Delete Sprint")

    if not st.session_state.sprint_df.empty:
        sprint_to_delete = st.selectbox(
            "Select sprint to delete",
            st.session_state.sprint_df["Sprint"]
        )

        if st.button("Delete Sprint"):
            st.session_state.sprint_df = st.session_state.sprint_df[
                st.session_state.sprint_df["Sprint"] != sprint_to_delete
            ]
            st.session_state.sprint_df = ensure_spill_over_column(st.session_state.sprint_df).reindex(columns=sprint_columns)
            st.success("Sprint deleted!")

    # ------------------ METRICS ------------------
    df = st.session_state.sprint_df

    if not df.empty:
        st.write("### Key Metrics")

        total_committed = df["Committed"].sum()
        total_completed = df["Completed"].sum()
        total_scope = df["Scope Added"].sum()

        avg_velocity = df["Completed"].mean()
        predictability = (total_completed / total_committed) * 100 if total_committed > 0 else 0
        scope_change = (total_scope / total_committed) * 100 if total_committed > 0 else 0
        avg_spill_over_percentage = df["Spill Over"].sum() / len(df) if len(df) > 0 else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Avg Velocity", f"{avg_velocity:.2f}")
        col2.metric("Predictability %", f"{predictability:.2f}%")
        col3.metric("Scope Change %", f"{scope_change:.2f}%")
        col4.metric("Average Spill Over %", f"{avg_spill_over_percentage:.2f}")

        # ------------------ TREND ------------------
        st.write("### Velocity Trend")
        st.line_chart(df.set_index("Sprint")[["Completed"]])

        st.write("### Spill Over Trend")
        st.line_chart(df.set_index("Sprint")[["Spill Over"]])

        # ------------------ INSIGHTS ------------------
        st.write("### Insights")

        if predictability < 70:
            st.error("⚠️ Low predictability → Overcommitment / dependencies")
        elif predictability < 90:
            st.warning("⚠️ Moderate predictability")
        else:
            st.success("✅ Strong delivery")

        if scope_change > 20:
            st.error("⚠️ High scope creep")
        else:
            st.success("✅ Stable scope")
