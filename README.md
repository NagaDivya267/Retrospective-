# Retrospective-

AI Scrum Master retrospective app built with Streamlit.

## Features
- Mood Indicator
- Sprint Insights Dashboard
- Google Sheets save/test integration
- AI Generated Questions
- Action Tracker

## Project Structure
- `app.py`: the only Streamlit entrypoint used for local runs and Streamlit Cloud
- `requirements.txt`: Python dependencies for deployment
- `.streamlit/secrets.toml`: local-only secrets file, not committed

## Local Run
1. Install dependencies:
	`pip install -r requirements.txt`
2. Add a local `.streamlit/secrets.toml` or place a local `credentials.json` next to `app.py`.
3. Start the app:
	`streamlit run app.py`

## Streamlit Cloud
1. Deploy using the repository root.
2. Set the main file path to `app.py`.
3. Add the Google service account JSON in Streamlit Cloud secrets as `gcp_service_account`.
4. Add the OpenAI API key in Streamlit Cloud secrets as `OPENAI_API_KEY`.

Example secrets structure:

```toml
OPENAI_API_KEY = "your-openai-api-key"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
universe_domain = "googleapis.com"
```

## Hosted Use
- Running the app locally with `streamlit run app.py` depends on your machine staying on.
- If your laptop or desktop is shut down, a local run stops immediately.
- To keep the app available, deploy it to Streamlit Community Cloud or another always-on host.
- In hosted mode, Google Sheets and OpenAI features continue to work as long as the secrets above are configured there.

## Deployment Checklist
1. Push the latest repository changes to GitHub.
2. In Streamlit Community Cloud, create an app from this repository.
3. Set the main file to `app.py`.
4. Add `OPENAI_API_KEY` in app secrets.
5. Add the full `gcp_service_account` JSON in app secrets.
6. Share the target Google Sheet with the service account email as Editor.
7. Confirm the sheet contains or can create these tabs: `Sprint Insights`, `Config`, `Responses`, `Discussions`, and `Actions`.
8. Redeploy and test one flow each for Sprint save, Spin Wheel response save, and Action Tracker save.

## Notes
- The app first looks for `st.secrets["gcp_service_account"]`.
- The app first looks for `st.secrets["OPENAI_API_KEY"]`, then local environment variables.
- If that is not present, it falls back to a local `credentials.json`.
- `credentials.json` is only for local runs and should not be used for cloud deployment.
- Do not commit service account keys to the repository.
