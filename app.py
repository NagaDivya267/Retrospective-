import streamlit as st
import sqlite3
import datetime
import pandas as pd
import random

st.set_page_config(page_title="AI Scrum Master", layout="wide")

st.title("🤖 AI Scrum Master Retrospective Tool")

# ---------------------------------------------------------------------------
# SQLite database helpers for mood data
# ---------------------------------------------------------------------------

DB_PATH = "mood_data.db"


def init_mood_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS mood_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            team_size INTEGER,
            total_mood_score INTEGER,
            average_mood REAL,
            mood_label TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_mood_to_db(team_size, total_score, avg_mood, label):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO mood_records (timestamp, team_size, total_mood_score, average_mood, mood_label)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          team_size, total_score, avg_mood, label))
    conn.commit()
    conn.close()


def load_mood_history_db():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT timestamp, team_size, total_mood_score, average_mood, mood_label "
        "FROM mood_records ORDER BY timestamp DESC LIMIT 20",
        conn
    )
    conn.close()
    return df


def get_mood_label(avg_mood):
    """Return the mood label for the given average score."""
    if avg_mood <= 2:
        return "Low"
    elif avg_mood <= 3:
        return "Neutral"
    else:
        return "Excited"


init_mood_db()

# ---------------------------------------------------------------------------
# Create Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([
    "😊 Mood",
    "📊 Sprint Insights",
    "🎯 AI Questions",
    "✅ Action Tracker"
])

with tab1:
    st.subheader("Team Mood Check")

    # ------ Team size input ------
    team_size = st.number_input(
        "Number of team members", min_value=1, max_value=50, value=5, step=1
    )

    # ------ Session state initialisation ------
    if "mood_history" not in st.session_state:
        st.session_state.mood_history = []
    if "last_mood" not in st.session_state:
        st.session_state.last_mood = None

    # ------ Emoji mood buttons ------
    moods = {
        "😡": 1,
        "😟": 2,
        "😐": 3,
        "😊": 4,
        "🚀": 5,
    }

    st.write("Each team member selects their mood:")
    col1, col2, col3, col4, col5 = st.columns(5)

    selected_mood = None
    for i, (emoji, value) in enumerate(moods.items()):
        if [col1, col2, col3, col4, col5][i].button(emoji):
            selected_mood = value
            st.session_state.last_mood = value
            st.session_state.mood_history.append(value)

    # Show last individual selection
    if st.session_state.last_mood is not None:
        mood = st.session_state.last_mood
        emoji_label = "".join(k for k, v in moods.items() if v == mood)
        st.info(f"Last selected: {emoji_label} — score {mood}")

    votes_so_far = len(st.session_state.mood_history)
    st.write(f"**Votes collected:** {votes_so_far} / {team_size}")

    # ------ Average mood (sum / team_size) ------
    if votes_so_far > 0:
        total_score = sum(st.session_state.mood_history)
        avg_mood = round(total_score / team_size)  # always divide by configured team size

        if votes_so_far < team_size:
            st.caption(f"⚠️ Partial result — {votes_so_far} of {team_size} members have voted.")

        st.metric("Average Mood Score", avg_mood, help="Sum of all mood scores ÷ number of team members (rounded)")

        # Mood label intervals: Low ≤ 2 < Neutral ≤ 3 < Excited
        mood_label = get_mood_label(avg_mood)
        if mood_label == "Low":
            st.warning(f"😐 Team mood: **{mood_label}** — The team energy is moderate, consider a check-in.")
        elif mood_label == "Neutral":
            st.info(f"🙂 Team mood: **{mood_label}** — The team is steady. Room to grow!")
        else:
            st.success(f"🚀 Team mood: **{mood_label}** — Great energy! Keep it up!")

    # ------ Submit button: save to DB ------
    if st.button("Submit Team Mood to Database"):
        if votes_so_far == 0:
            st.error("No mood votes recorded yet. Please select moods first.")
        else:
            total_score = sum(st.session_state.mood_history)
            avg_mood = round(total_score / team_size)
            mood_label = get_mood_label(avg_mood)

            save_mood_to_db(team_size, total_score, avg_mood, mood_label)
            st.success(f"✅ Mood saved! Average: {avg_mood} ({mood_label})")
            # Reset for next round
            st.session_state.mood_history = []
            st.session_state.last_mood = None

    # ------ Reset button ------
    if st.button("Reset Mood Votes"):
        st.session_state.mood_history = []
        st.session_state.last_mood = None
        st.info("Mood votes reset.")

    # ------ Display saved mood history from DB ------
    st.write("---")
    st.write("### 📋 Saved Mood History")
    history_df = load_mood_history_db()
    if history_df.empty:
        st.write("No mood records saved yet.")
    else:
        st.dataframe(history_df, use_container_width=True)

with tab2:
    st.subheader("Sprint Insights Tracker")

    # Initialize storage
    if "sprint_df" not in st.session_state:
        st.session_state.sprint_df = pd.DataFrame(
            columns=["Sprint", "Committed", "Completed", "Scope Added"]
        )

    # ------------------ OPTION 1: CSV Upload ------------------
    st.write("### Upload CSV")
    uploaded_file = st.file_uploader("Upload Sprint Data CSV", type=["csv"])

    if uploaded_file:
        df_uploaded = pd.read_csv(uploaded_file)

        required_cols = ["Sprint", "Committed", "Completed", "Scope Added"]
        if all(col in df_uploaded.columns for col in required_cols):
            st.session_state.sprint_df = df_uploaded.tail(6)
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

            st.success("Sprint added!")

    # ------------------ EDITABLE TABLE ------------------
    st.write("### Edit Sprint Data")

    edited_df = st.data_editor(
        st.session_state.sprint_df,
        num_rows="dynamic",
        use_container_width=True
    )

    st.session_state.sprint_df = edited_df

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

        col1, col2, col3 = st.columns(3)
        col1.metric("Avg Velocity", f"{avg_velocity:.2f}")
        col2.metric("Predictability %", f"{predictability:.2f}%")
        col3.metric("Scope Change %", f"{scope_change:.2f}%")

        # ------------------ TREND ------------------
        st.write("### Velocity Trend")
        st.line_chart(df.set_index("Sprint")[["Completed"]])

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

        if avg_velocity < 20:
            st.warning("⚠️ Low velocity trend")
        else:
            st.success("🚀 Healthy velocity")
