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

# Create Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "😊 Mood",
    "📊 Sprint Insights",
    "🎡 Spin Wheel",
    "👑 Scrum Master Dashboard"
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
                        st.success("✅ Response submitted!")
                        st.rerun()
                    else:
                        st.warning("Please add something")
            else:
                st.info("🎊 All responses collected! Session complete.")
        
    except Exception as error:
        st.error(f"Unable to load spin wheel data: {error}")

with tab4:
    st.subheader("👑 Scrum Master Dashboard")

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
            st.write("###  Filter by Question")
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

                # ---- AI Analysis ----
                st.write("### 🤖 AI Analysis")
                if st.button("Generate AI Insights", key=f"ai_insights_{selected_question}"):
                    api_key = st.secrets.get("OPENAI_API_KEY")
                    if not api_key:
                        st.error("OPENAI_API_KEY is missing. Add it in Streamlit secrets.")
                    elif filtered_discussion.empty:
                        st.warning("No discussion data available")
                    else:
                        discussion_text = "\n".join(
                            filtered_discussion["Discussion"].dropna().astype(str).tolist()
                        ).strip()

                        if not discussion_text:
                            st.warning("No discussion data available")
                        else:
                            # Keep payload bounded for predictable latency/cost.
                            discussion_text = discussion_text[:8000]
                            prompt = f"""
You are a highly experienced Scrum Master working with Agile teams.

Analyze ONLY the discussion provided below. Do NOT assume anything beyond this data.

Discussion:
{discussion_text}

Instructions:
- Be precise and practical
- Do NOT hallucinate or invent problems
- Base every insight ONLY on the provided inputs
- Keep language simple, human-like, and relatable
- Avoid generic statements

If the data is insufficient, say: "Not enough data to derive insight"

Output format:

🔍 Key Themes:
- ...

⚠️ Observed Problems:
- ...

✅ Positive Signals:
- ...

🎯 Actionable Improvements:
- ...
- ...
- ...
"""

                            try:
                                client = OpenAI(api_key=api_key)
                                with st.spinner("Generating AI insights..."):
                                    response = client.chat.completions.create(
                                        model="gpt-4.1-mini",
                                        messages=[
                                            {
                                                "role": "system",
                                                "content": "You are a practical Scrum Master assistant. Only use provided discussion text.",
                                            },
                                            {"role": "user", "content": prompt},
                                        ],
                                        temperature=0.2,
                                        max_tokens=700,
                                    )

                                ai_output = response.choices[0].message.content or "Not enough data to derive insight"
                                st.write("### 📊 AI Insights")
                                st.markdown(ai_output)
                            except Exception as ai_error:
                                st.error(f"Unable to generate AI insights: {ai_error}")
    except Exception as error:
        st.error(f"Unable to load Scrum Master dashboard: {error}")
