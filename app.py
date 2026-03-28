import base64
import io
import math
import os
import random
import struct
import time
import wave
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from openai import OpenAI


# -------------------------------
# Page Config and Global UI Theme
# -------------------------------
st.set_page_config(
    page_title="AI Scrum Master Assistant",
    layout="wide",
    page_icon="🚀",
)

st.title("AI Scrum Master Assistant")
st.caption("Smarter retrospectives | Better decisions | Faster delivery")

# Create Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "😊 Mood",
    "📊 Sprint Insights",
    "🎡 Spin Wheel",
    "👑 Dashboard",
    "📌 Action Tracker"
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

FILE_NAME = "sprint_data.csv"
GOOGLE_SHEET_NAME = "Retro Data"
GOOGLE_SHEETS_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
SPRINT_WORKSHEET_NAME = "Sprint Insights"
CONFIG_WORKSHEET_NAME = "Config"
RESPONSES_WORKSHEET_NAME = "Responses"
spin_questions = [
    "🚀 What went well?",
    "😕 What didn't go well?",
    "⛔ Biggest blocker?",
    "💡 Improvement idea?",
    "🔥 What frustrated you?",
    "🎯 One experiment for next sprint?",
    "🤝 Team collaboration feedback?",
]


def get_openai_api_key() -> tuple[str | None, str, list[str]]:
    """Resolve OpenAI API key across local env and multiple Streamlit secrets layouts."""
    candidates: list[tuple[str | None, str]] = [
        (os.getenv("OPENAI_API_KEY"), "env:OPENAI_API_KEY"),
    ]

    secret_keys: list[str] = []
    try:
        secret_keys = list(st.secrets.keys())
    except Exception:
        secret_keys = []

    if "OPENAI_API_KEY" in st.secrets:
        candidates.append((st.secrets.get("OPENAI_API_KEY"), "secrets:OPENAI_API_KEY"))
    if "openai_api_key" in st.secrets:
        candidates.append((st.secrets.get("openai_api_key"), "secrets:openai_api_key"))
    if "api_key" in st.secrets:
        candidates.append((st.secrets.get("api_key"), "secrets:api_key"))

    if "openai" in st.secrets:
        openai_section = st.secrets["openai"]
        if hasattr(openai_section, "get"):
            candidates.extend(
                [
                    (openai_section.get("api_key"), "secrets:openai.api_key"),
                    (openai_section.get("OPENAI_API_KEY"), "secrets:openai.OPENAI_API_KEY"),
                ]
            )

    # Last resort: scan nested secrets recursively for key-like fields.
    def scan_mapping(mapping, prefix: str = "secrets"):
        discovered: list[tuple[str | None, str]] = []
        if not hasattr(mapping, "items"):
            return discovered
        for key, value in mapping.items():
            key_str = str(key)
            lower_key = key_str.lower()
            path = f"{prefix}.{key_str}"
            if lower_key in {"openai_api_key", "api_key"}:
                discovered.append((value, path))
            if hasattr(value, "items"):
                discovered.extend(scan_mapping(value, path))
        return discovered

    candidates.extend(scan_mapping(st.secrets))

    for value, source in candidates:
        if value and str(value).strip():
            return str(value).strip(), source, secret_keys

    return None, "not-found", secret_keys


@st.cache_data(show_spinner=False)
def generate_spin_sound() -> bytes:
    """Synthesise a short spinning-wheel whoosh as WAV bytes (stdlib only)."""
    sample_rate = 44100
    duration = 1.5
    num_samples = int(sample_rate * duration)
    buf = io.BytesIO()
    with wave.open(buf, "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = []
        for i in range(num_samples):
            t = i / sample_rate
            progress = t / duration
            # frequency sweeps 800 Hz → 200 Hz (wheel slowing down)
            freq = 800 * (1 - progress) + 200 * progress
            # amplitude envelope peaks in the middle
            amplitude = 32767 * math.sin(math.pi * progress) * 0.7
            sample = int(amplitude * math.sin(2 * math.pi * freq * t))
            frames.append(struct.pack("<h", max(-32768, min(32767, sample))))
        wav.writeframes(b"".join(frames))
    return buf.getvalue()


def get_credentials_file_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_paths = [
        os.path.join(base_dir, "credentials.json"),
        os.path.join(base_dir, "..", "credentials.json"),
        os.path.join(base_dir, "..", "..", "credentials.json"),
        os.path.join(base_dir, "..", "..", "..", "credentials.json"),
    ]

    for candidate_path in candidate_paths:
        resolved_path = os.path.abspath(candidate_path)
        if os.path.exists(resolved_path):
            return resolved_path

    raise FileNotFoundError(
        "credentials.json was not found. Add it near the app or configure st.secrets['gcp_service_account']."
    )


@st.cache_resource(show_spinner=False)
def get_google_workbook():
    if "gcp_service_account" in st.secrets:
        credentials = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=GOOGLE_SHEETS_SCOPE,
        )
    else:
        credentials = Credentials.from_service_account_file(
            get_credentials_file_path(),
            scopes=GOOGLE_SHEETS_SCOPE,
        )

    client = gspread.authorize(credentials)
    return client.open(GOOGLE_SHEET_NAME)


def get_or_create_worksheet(title: str, rows: int = 100, cols: int = 20):
    workbook = get_google_workbook()
    try:
        return workbook.worksheet(title)
    except gspread.WorksheetNotFound:
        return workbook.add_worksheet(title=title, rows=rows, cols=cols)


def save_sprint_data_to_google_sheet(df: pd.DataFrame, columns: list[str]) -> None:
    sheet = get_or_create_worksheet(SPRINT_WORKSHEET_NAME, rows=200, cols=len(columns) + 5)
    rows = df.reindex(columns=columns).fillna("").values.tolist()

    sheet.clear()
    sheet.append_row(columns)
    if rows:
        sheet.append_rows(rows)


def ensure_spill_over_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if all(col in df.columns for col in ["Committed", "Scope Added", "Completed"]):
        df["Spill Over"] = (
            pd.to_numeric(df["Committed"], errors="coerce").fillna(0)
            + pd.to_numeric(df["Scope Added"], errors="coerce").fillna(0)
            - pd.to_numeric(df["Completed"], errors="coerce").fillna(0)
        )
    return df


def mark_sync_event(label: str) -> None:
    st.session_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["last_sync_event"] = label

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

    # ------------------ GOOGLE SHEETS ------------------
    st.write("### Google Sheets")
    sheet_col1, sheet_col2 = st.columns(2)

    if sheet_col1.button("Test Sheet"):
        try:
            workbook = get_google_workbook()
            st.success(f"Connected successfully to {workbook.title}!")
        except Exception as error:
            st.error(f"Google Sheets connection failed: {error}")

    if sheet_col2.button("Save Sprint Data"):
        try:
            save_sprint_data_to_google_sheet(st.session_state.sprint_df, sprint_columns)
            mark_sync_event("Saved sprint data")
            st.success("Sprint data saved to Google Sheet successfully!")
        except Exception as error:
            st.error(f"Unable to save sprint data: {error}")

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

with tab3:
    st.subheader("🎡 Spin the Retro Wheel")

    try:
        config_sheet = get_or_create_worksheet(CONFIG_WORKSHEET_NAME, rows=20, cols=5)
        response_sheet = get_or_create_worksheet(RESPONSES_WORKSHEET_NAME, rows=500, cols=10)

        if "spin_count" not in st.session_state:
            st.session_state["spin_count"] = 0
        if "current_spin_question" not in st.session_state:
            st.session_state["current_spin_question"] = None
        if "used_questions" not in st.session_state:
            st.session_state["used_questions"] = []

        # Check if all spins are complete
        spins_complete = st.session_state["spin_count"] >= 7
        
        # Disable spin button after 7 spins
        spin_button = st.button("🎯 Spin the Wheel", disabled=spins_complete)

        if spin_button and not spins_complete:
            # Increment spin count
            st.session_state["spin_count"] += 1
            is_last_spin = st.session_state["spin_count"] >= 7
            
            # Get remaining unused questions
            remaining_questions = [q for q in spin_questions if q not in st.session_state["used_questions"]]
            
            # If all questions used, reset the list (shouldn't happen at 7 spins)
            if not remaining_questions:
                remaining_questions = spin_questions
                st.session_state["used_questions"] = []
            
            # Pick final question from remaining
            final_question = random.choice(remaining_questions)
            st.session_state["used_questions"].append(final_question)
            
            # Generate and inject audio (autoplay during spinner)
            audio_data = generate_spin_sound()
            audio_base64 = base64.b64encode(audio_data).decode()
            
            st.markdown(
                f'<audio autoplay><source src="data:audio/wav;base64,{audio_base64}" type="audio/wav"></audio>',
                unsafe_allow_html=True
            )
            
            # Show spinner while audio plays
            with st.spinner("🎡 Spinning the wheel..."):
                time.sleep(1.5)
            
            # Save question to sheet
            config_sheet.update_acell("A1", final_question)
            st.session_state["current_spin_question"] = final_question
            
            # Show balloons only on last spin (7th spin)
            if is_last_spin:
                st.balloons()
            
            # Rerun to show updated question
            st.rerun()

        # Display spin completion status
        if spins_complete:
            st.success("✅ All 7 questions completed! Great job! 🎉")

        # Display the current question persistently until next spin
        current_question = st.session_state.get("current_spin_question") or config_sheet.acell("A1").value

        if current_question:
            st.write("### 📌 Current Question")
            st.success(current_question)
            
            # Show spin count indicator with progress
            progress_text = f"Question {st.session_state['spin_count']}/7"
            if st.session_state["spin_count"] >= 7:
                progress_text += " ✨ FINAL!"
            st.caption(f"🎡 {progress_text}")

            if not spins_complete:  # Only show input if spins not complete
                user_input = st.text_area("💬 Your response", key=f"response_{current_question}")

                if st.button("Submit Response"):
                    if user_input.strip():
                        existing_header = response_sheet.row_values(1)
                        expected_header = ["Timestamp", "Question", "Response"]

                        if existing_header != expected_header:
                            response_sheet.clear()
                            response_sheet.append_row(expected_header)

                        response_sheet.append_row([
                            datetime.now().isoformat(),
                            current_question,
                            user_input.strip(),
                        ])
                        mark_sync_event("Saved spin wheel response")
                        st.success("✅ Submitted successfully")
                        st.rerun()
                    else:
                        st.warning("Please add something")
            else:
                st.info("🎊 All responses collected! Session complete.")
        
    except Exception as error:
        st.error(f"Unable to load spin wheel data: {error}")

with tab4:
    st.subheader("👑 Scrum Master Dashboard")

    st.write("### 🩺 System Health")
    health_col2, health_col3 = st.columns(2)

    try:
        workbook = get_google_workbook()
        health_col2.success(f"Google Sheets: Connected ({workbook.title})")
    except Exception:
        health_col2.error("Google Sheets: Not connected")

    last_sync_time = st.session_state.get("last_sync_time", "Never")
    last_sync_event = st.session_state.get("last_sync_event", "No sync yet")
    health_col3.info(f"Last Sync: {last_sync_time}")
    st.caption(f"Sync Event: {last_sync_event}")

    if st.button("🔁 Retry Connection", key="retry_connection_button"):
        get_google_workbook.clear()
        st.session_state["last_sync_event"] = "Manual health retry"
        st.rerun()

    col_refresh, _ = st.columns([1, 5])
    if col_refresh.button("🔄 Refresh Data"):
        for key in ["ai_last_question", "ai_chat_history", "ai_clustered_data"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    try:
        config_sheet = get_or_create_worksheet(CONFIG_WORKSHEET_NAME, rows=20, cols=5)
        response_sheet = get_or_create_worksheet(RESPONSES_WORKSHEET_NAME, rows=500, cols=10)
        discussion_sheet = get_or_create_worksheet("Discussions", rows=500, cols=5)

        # Load all response rows from Google Sheets.
        data = response_sheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.warning("No responses yet")
        else:
            st.write("### 🔍 Filter by Question")
            questions = df["Question"].dropna().unique()

            if len(questions) == 0:
                st.info("No question data found in responses yet.")
            else:
                current_question = config_sheet.acell("A1").value
                default_index = 0
                if current_question and current_question in questions:
                    default_index = list(questions).index(current_question)

                selected_question = st.selectbox("Select Question", questions, index=default_index)
                filtered_df = df[df["Question"] == selected_question]

                st.write("### 🧾 Responses for Selected Question")
                st.dataframe(filtered_df, use_container_width=True)

                st.write("### 📈 Insights")
                col1, col2 = st.columns(2)
                col1.metric("Total Responses", len(df))
                col2.metric("Unique Questions", df["Question"].nunique())

                st.write("### 💬 Discussion View")
                if filtered_df.empty:
                    st.info("No responses for this question yet")
                else:
                    for _, row in filtered_df.iterrows():
                        st.write(f"🟢 {row['Response']}")
                        st.write("---")

                # ---- Capture Discussion Points ----
                st.write("### 🧠 Capture Discussion Points")
                discussion_input = st.text_area("Summarize team discussion for this question", key=f"discussion_{selected_question}")

                if st.button("Save Discussion"):
                    if discussion_input.strip():
                        # Ensure header row exists
                        existing_header = discussion_sheet.row_values(1)
                        if existing_header != ["Question", "Discussion"]:
                            discussion_sheet.clear()
                            discussion_sheet.append_row(["Question", "Discussion"])
                        discussion_sheet.append_row([selected_question, discussion_input.strip()])
                        mark_sync_event("Saved discussion point")
                        st.success("Discussion saved!")
                        st.rerun()
                    else:
                        st.warning("Please enter a discussion summary before saving.")

                # ---- Show Saved Discussions ----
                st.write("### 📌 Saved Discussion Points")
                discussion_data = discussion_sheet.get_all_records()
                filtered_discussion = pd.DataFrame(columns=["Question", "Discussion"])
                if discussion_data:
                    discussion_df = pd.DataFrame(discussion_data)
                    filtered_discussion = discussion_df[
                        discussion_df["Question"] == selected_question
                    ]
                    if filtered_discussion.empty:
                        st.info("No discussion points saved for this question yet.")
                    else:
                        st.dataframe(filtered_discussion[["Discussion"]], use_container_width=True)
                else:
                    st.info("No discussion points saved yet.")

                # ---- AI Analysis: Team Inputs -> Clustering -> Summary -> Chat Follow-ups ----
                st.write("### 🤖 AI Scrum Master")

                if "ai_chat_history" not in st.session_state:
                    st.session_state.ai_chat_history = []
                if "ai_clustered_data" not in st.session_state:
                    st.session_state.ai_clustered_data = ""
                if "ai_last_question" not in st.session_state:
                    st.session_state.ai_last_question = None

                # Reset conversation context when question changes.
                if st.session_state.ai_last_question != selected_question:
                    st.session_state.ai_chat_history = []
                    st.session_state.ai_clustered_data = ""
                    st.session_state.ai_last_question = selected_question

                api_key, key_source, secret_keys = get_openai_api_key()
                if not api_key:
                    st.error("OpenAI key is missing. Add OPENAI_API_KEY in Streamlit secrets and restart the app.")
                    st.caption(
                        f"Diagnostics: key_source={key_source}; top_level_secrets={', '.join(secret_keys) if secret_keys else 'none'}"
                    )
                else:
                    sprint_df = st.session_state.get("sprint_df", pd.DataFrame())

                    sprint_summary = ""
                    if not sprint_df.empty:
                        sprint_summary = "Sprint,Committed,Completed,ScopeAdded\n"
                        for _, srow in sprint_df.tail(6).iterrows():
                            sprint_summary += (
                                f"{srow.get('Sprint', '?')},"
                                f"{int(srow.get('Committed', 0) or 0)},"
                                f"{int(srow.get('Completed', 0) or 0)},"
                                f"{int(srow.get('Scope Added', 0) or 0)}\n"
                            )

                    discussion_text = ""
                    if not filtered_discussion.empty:
                        seen = set()
                        unique_lines = []
                        for line in filtered_discussion["Discussion"].dropna().astype(str):
                            stripped = line.strip()
                            if stripped and stripped not in seen:
                                seen.add(stripped)
                                unique_lines.append(stripped)
                        discussion_text = "\n".join(unique_lines)[:3000]

                    system_prompt = (
                        "You are an experienced Scrum Master assistant. "
                        "Use ONLY the provided data. No assumptions. If data is insufficient, say 'Not enough data'.\n\n"
                        f"Selected Question: {selected_question}\n"
                        f"Sprint Data:\n{sprint_summary or 'none'}\n"
                        f"Team Discussions:\n{discussion_text or 'none'}"
                    )

                    def generate_clustered_summary(client: OpenAI) -> str:
                        cluster_prompt = (
                            "Cluster similar discussion responses.\n"
                            "Output:\n"
                            "🔹 Theme: <name>\n- Description: ...\n- Mentions: <count>\n\n"
                            "⚠️ Key Problems:\n- ...\n\n"
                            "✅ Positive Signals:\n- ..."
                        )

                        response = client.chat.completions.create(
                            model="gpt-4.1-mini",
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": cluster_prompt},
                            ],
                            temperature=0.2,
                            max_tokens=500,
                        )
                        return response.choices[0].message.content or "Not enough data"

                    if st.button("Generate Smart Insights", key=f"ai_generate_{selected_question}"):
                        if discussion_text.strip() == "":
                            st.warning("No discussion data available")
                        else:
                            try:
                                client = OpenAI(api_key=api_key)
                                with st.spinner("Generating clustered insights..."):
                                    clustered_output = generate_clustered_summary(client)

                                st.session_state.ai_clustered_data = clustered_output
                                st.session_state.ai_chat_history = [
                                    {"role": "assistant", "content": clustered_output}
                                ]
                                st.rerun()
                            except Exception as ai_error:
                                st.error(f"Unable to generate AI insights: {ai_error}")

                    # Display chat history
                    for msg in st.session_state.ai_chat_history:
                        with st.chat_message(msg["role"]):
                            st.markdown(msg["content"])

                    user_follow_up = st.chat_input(
                        "Ask follow-up (e.g., top blockers, trimmed actions, owner-wise tasks)",
                        key=f"ai_chat_input_{selected_question}",
                    )

                    if user_follow_up:
                        st.session_state.ai_chat_history.append(
                            {"role": "user", "content": user_follow_up}
                        )

                        history = st.session_state.ai_chat_history[-6:]
                        message_payload: list[dict[str, str]] = [
                            {
                                "role": "system",
                                "content": system_prompt
                                + "\n\nClustered Insights:\n"
                                + str(st.session_state.ai_clustered_data or "none"),
                            }
                        ]
                        for entry in history:
                            role = str(entry.get("role", "user"))
                            content = str(entry.get("content", ""))
                            message_payload.append({"role": role, "content": content})

                        try:
                            client = OpenAI(api_key=api_key)
                            with st.spinner("Generating follow-up insight..."):
                                response = client.chat.completions.create(
                                    model="gpt-4.1-mini",
                                    messages=message_payload,  # type: ignore[arg-type]
                                    temperature=0.2,
                                    max_tokens=450,
                                )

                            reply = response.choices[0].message.content or "Not enough data"
                            st.session_state.ai_chat_history.append(
                                {"role": "assistant", "content": reply}
                            )
                            st.rerun()
                        except Exception as ai_error:
                            st.error(f"Unable to generate follow-up insight: {ai_error}")

                    if st.button("🧹 Clear Chat", key=f"ai_clear_{selected_question}"):
                        st.session_state.ai_chat_history = []
                        st.session_state.ai_clustered_data = ""
                        st.rerun()
    except Exception as error:
        st.error(f"Unable to load Scrum Master dashboard: {error}")

with tab5:
    st.subheader("📌 Action Tracker")

    try:
        main_sheet = get_google_workbook()
        try:
            action_sheet = main_sheet.worksheet("Actions")
        except gspread.WorksheetNotFound:
            action_sheet = main_sheet.add_worksheet(title="Actions", rows=500, cols=10)

        existing_header = [header.strip() for header in action_sheet.row_values(1)]
        if not existing_header:
            action_sheet.append_row(["Action", "Priority"])

        action_data = action_sheet.get_all_records()
        action_df = pd.DataFrame(action_data)

        # Backward compatibility: support older schemas and normalize to Action/Priority.
        if not action_df.empty:
            if "Action" not in action_df.columns:
                if "Action Item" in action_df.columns:
                    action_df["Action"] = action_df["Action Item"]
                elif "Task" in action_df.columns:
                    action_df["Action"] = action_df["Task"]
                else:
                    action_df["Action"] = ""

            if "Priority" not in action_df.columns:
                if "Status" in action_df.columns:
                    status_series = action_df["Status"].astype(str).str.strip().str.lower()
                    action_df["Priority"] = status_series.map(
                        {
                            "open": "Medium",
                            "in progress": "High",
                            "done": "Low",
                            "high": "High",
                            "medium": "Medium",
                            "low": "Low",
                        }
                    ).fillna("Medium")
                else:
                    action_df["Priority"] = "Medium"

            action_df["Action"] = action_df["Action"].astype(str).str.strip()
            action_df["Priority"] = action_df["Priority"].astype(str).str.strip().str.title()
            action_df = action_df[action_df["Action"] != ""].copy()
            action_df.loc[~action_df["Priority"].isin(["High", "Medium", "Low"]), "Priority"] = "Medium"
            action_df = action_df[["Action", "Priority"]]

        if action_df.empty:
            st.info("No actions yet")
        else:
            normalized_priority = action_df["Priority"].astype(str).str.strip().str.title()
            high_count = int((normalized_priority == "High").sum())
            medium_count = int((normalized_priority == "Medium").sum())
            low_count = int((normalized_priority == "Low").sum())

            st.write("### 📊 Priority Summary")
            summary_col1, summary_col2, summary_col3 = st.columns(3)
            summary_col1.metric("High", high_count)
            summary_col2.metric("Medium", medium_count)
            summary_col3.metric("Low", low_count)

            st.write("### 🔎 Filter & Sort")
            filter_col, sort_col = st.columns(2)

            selected_priority_filter = filter_col.selectbox(
                "Priority Filter",
                ["All", "High", "Medium", "Low"],
                key="priority_filter",
            )
            selected_sort = sort_col.selectbox(
                "Sort By",
                ["Priority (High to Low)", "Priority (Low to High)", "Action (A-Z)", "Action (Z-A)"],
                key="priority_sort",
            )

            filtered_actions_df = action_df.copy()
            filtered_actions_df["Priority"] = (
                filtered_actions_df["Priority"].astype(str).str.strip().str.title()
            )

            if selected_priority_filter != "All":
                filtered_actions_df = filtered_actions_df[
                    filtered_actions_df["Priority"] == selected_priority_filter
                ]

            priority_rank = {"High": 0, "Medium": 1, "Low": 2}
            filtered_actions_df["_priority_rank"] = filtered_actions_df["Priority"].map(priority_rank).fillna(3)

            if selected_sort == "Priority (High to Low)":
                filtered_actions_df = filtered_actions_df.sort_values(
                    by=["_priority_rank", "Action"],
                    ascending=[True, True],
                )
            elif selected_sort == "Priority (Low to High)":
                filtered_actions_df = filtered_actions_df.sort_values(
                    by=["_priority_rank", "Action"],
                    ascending=[False, True],
                )
            elif selected_sort == "Action (A-Z)":
                filtered_actions_df = filtered_actions_df.sort_values(by="Action", ascending=True)
            else:
                filtered_actions_df = filtered_actions_df.sort_values(by="Action", ascending=False)

            filtered_actions_df = filtered_actions_df.drop(columns=["_priority_rank"])

            def highlight_priority(cell_value):
                value = str(cell_value).strip().lower()
                if value == "high":
                    return "background-color: #ffe4e6; color: #9f1239; font-weight: 700;"
                if value == "medium":
                    return "background-color: #fff7ed; color: #9a3412; font-weight: 700;"
                if value == "low":
                    return "background-color: #ecfdf5; color: #065f46; font-weight: 700;"
                return ""

            styled_df = filtered_actions_df.style.map(highlight_priority, subset=["Priority"])
            st.dataframe(styled_df, use_container_width=True)

            if filtered_actions_df.empty:
                st.info("No actions match the selected filter.")

        st.write("### ➕ Add Action Item")
        add_col1, add_col2 = st.columns(2)

        action_item = add_col1.text_input("Action Item", key="action_item_input")
        priority = add_col2.selectbox(
            "Priority",
            ["High", "Medium", "Low"],
            index=1,
            key="action_priority_input",
        )

        if st.button("Add Action", key="add_action_button"):
            if action_item.strip():
                action_sheet.append_row([action_item.strip(), priority])
                mark_sync_event("Added action item")
                st.success("Action added!")
                st.rerun()
            else:
                st.warning("Please fill Action Item")

        st.write("### 🤖 Generate Actions from AI")

        ai_action_text = st.session_state.get("ai_actions_text", "")
        source_insights = st.session_state.get("ai_clustered_data", "") or st.session_state.get("clustered_data", "")

        if st.button("Generate AI Actions", key="generate_ai_actions_button"):
            api_key, key_source, secret_keys = get_openai_api_key()
            if not api_key:
                st.error("OpenAI key is missing. Add OPENAI_API_KEY in Streamlit secrets and restart the app.")
                st.caption(
                    f"Diagnostics: key_source={key_source}; top_level_secrets={', '.join(secret_keys) if secret_keys else 'none'}"
                )
            elif not str(source_insights).strip():
                st.warning("No AI insights found. Generate Smart Insights in Dashboard first.")
            else:
                prompt = f"""
Based on the following retrospective insights, generate actionable tasks.

Insights:
{source_insights}

Rules:
- Provide 3-5 actions
- Each must be specific and implementable
- Priority must be one of: High, Medium, Low
- Keep output concise

Output format:
Action Item | Priority
"""

                try:
                    client = OpenAI(api_key=api_key)
                    response = client.chat.completions.create(
                        model="gpt-4.1-mini",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                    )

                    ai_action_text = (response.choices[0].message.content or "").strip()
                    st.session_state.ai_actions_text = ai_action_text
                except Exception as ai_error:
                    st.error(f"Unable to generate AI actions: {ai_error}")

        if ai_action_text:
            st.write("### Suggested Actions")

            parsed_ai_actions: list[dict[str, str]] = []
            lines = [ln.strip() for ln in ai_action_text.split("\n") if ln.strip()]

            for line in lines:
                if "|" not in line:
                    continue

                left, right = [part.strip() for part in line.split("|", 1)]
                if not left or not right:
                    continue

                # Skip markdown table headers and separator rows.
                if left.lower() in {"action item", "action", "task"}:
                    continue
                if set(left).issubset({"-", ":"}) or set(right).issubset({"-", ":"}):
                    continue

                raw_priority = right.lower()
                if raw_priority.startswith("high"):
                    clean_priority = "High"
                elif raw_priority.startswith("medium"):
                    clean_priority = "Medium"
                elif raw_priority.startswith("low"):
                    clean_priority = "Low"
                else:
                    continue

                parsed_ai_actions.append({"Action Item": left, "Priority": clean_priority})

            editable_ai_actions_df = pd.DataFrame(columns=["Action Item", "Priority"])
            if parsed_ai_actions:
                ai_actions_df = pd.DataFrame(parsed_ai_actions)
                editable_ai_actions_df = st.data_editor(
                    ai_actions_df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="ai_actions_editor",
                    column_config={
                        "Priority": st.column_config.SelectboxColumn(
                            "Priority",
                            options=["High", "Medium", "Low"],
                            required=True,
                        )
                    },
                )
            else:
                st.warning("AI response could not be parsed into table format. Showing raw output below.")
                st.text(ai_action_text)

            if st.button("Save AI Actions", key="save_ai_actions_button"):
                saved_count = 0
                existing_actions = set(action_df["Action"].astype(str).str.strip().str.lower()) if not action_df.empty else set()

                rows_to_save = editable_ai_actions_df.to_dict("records")

                for row in rows_to_save:
                    action_text = str(row.get("Action Item", "")).strip()
                    clean_priority = str(row.get("Priority", "")).strip().title()

                    if not action_text or clean_priority not in {"High", "Medium", "Low"}:
                        continue

                    if action_text.lower() in existing_actions:
                        continue

                    action_sheet.append_row([action_text, clean_priority])
                    existing_actions.add(action_text.lower())
                    saved_count += 1

                if saved_count > 0:
                    mark_sync_event("Saved AI actions")
                    st.success(f"Saved {saved_count} AI actions!")
                    st.rerun()
                else:
                    st.warning("No valid AI actions found to save.")

        st.write("### ✏️ Edit Action")
        if not action_df.empty and all(col in action_df.columns for col in ["Action", "Priority"]):
            action_options = [
                f"{row_num}: {getattr(row, 'Action', '')} ({getattr(row, 'Priority', '')})"
                for row_num, row in enumerate(action_df.itertuples(index=False), start=2)
            ]
            selected_action_label = st.selectbox(
                "Select Action",
                action_options,
                key="action_select_to_edit",
            )
            selected_index = action_options.index(selected_action_label)
            selected_sheet_row = int(selected_action_label.split(":", 1)[0])
            selected_row = action_df.iloc[selected_index]

            new_action = st.text_input("Action", str(selected_row["Action"]), key="edit_action_text")

            priority_options = ["High", "Medium", "Low"]
            current_priority = str(selected_row["Priority"]).strip().title()
            if current_priority not in priority_options:
                current_priority = "Medium"

            new_priority = st.selectbox(
                "Priority Status",
                priority_options,
                index=priority_options.index(current_priority),
                key="edit_action_priority",
            )

            if st.button("Update Action", key="update_action_button"):
                if new_action.strip():
                    action_sheet.update_acell(f"A{selected_sheet_row}", new_action.strip())
                    action_sheet.update_acell(f"B{selected_sheet_row}", new_priority)
                    mark_sync_event("Updated action item")
                    st.success("Updated!")
                    st.rerun()
                else:
                    st.warning("Action cannot be empty.")
    except Exception as error:
        st.error(f"Unable to load Action Tracker: {error}")
