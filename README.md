# Alexa Plus — local personal assistant

A small, self-hosted Python assistant for typed questions, optional browser voice, meetings/reminders, arithmetic and allowlisted website searches. The web interface is served only on `127.0.0.1` by default.

> **Important: revoke the API key previously included in your original `.env` upload and replace it.** The included `.env.example` is intentionally blank. Never commit or share `.env`.

## Quick start (Windows)

1. Install Python 3.11 or newer.
2. Extract the complete `alexa_plus` folder.
3. Double-click `run_assistant.bat` (or run `python app.py`).
4. Open `http://127.0.0.1:8765` if the browser does not open automatically.
5. For AI answers, copy `.env.example` to `.env`, insert a **new** Groq key after revoking the exposed one, save, and restart the server. `GROQ_API_KEY=` is read by the Python backend only. It is never sent to the browser.

## macOS / Linux

```sh
cd alexa_plus
cp .env.example .env   # optional, only if configuring Groq
python3 -m venv .venv
. .venv/bin/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Browse to `http://127.0.0.1:8765`. The assistant can also run in basic terminal text mode using `python assistant.py`.

## Features

- **Voice and text:** keyboard chat; browser speech recognition when supported and microphone permission is granted; browser speech synthesis for replies. There is no always-on microphone or wake-word listener. Depending on the browser, speech recognition may send audio to a browser speech service.
- **Answers:** Groq streaming, compact local arithmetic, and a Wikipedia excerpt fallback. Toggle “Wiki off/on” to retrieve an excerpt and include it as model context. An excerpt link is shown when retrieved. Models can make mistakes; this does not guarantee correctness. Current news/weather/prices are not live-verified; a search link is offered instead.
- **Schedule:** persistent local SQLite meetings/reminders; list, cancel with confirmation, reminder notification while app/server are running, and `.ics` calendar export. No calendar integration, invitations, attendee email, or external calendar sync is implemented.
- **Browser tasks:** YouTube, Google, Wikipedia, GitHub, Amazon, Gmail, Netflix. Search results open in a clearly labeled new tab. Search actions use allowlisted HTTPS URLs and never run shell commands or control arbitrary apps/files.
- **Performance:** fast deterministic actions remain local; AI output streams. Network latency depends on Groq, network, and device. The UI reports measured request time rather than promising a fixed response time.

## Example commands

- `What is photosynthesis?`
- `What time is it?`
- `Open YouTube and search for India`
- `Search for Python tutorials on Google`
- `Schedule a meeting called Team sync tomorrow at 3 PM`
- `Remind me to call the dentist in 30 minutes`
- `List my meetings`
- `Calculate 15% of 8500`

Natural-language date parsing intentionally supports explicit, narrow forms such as `today at 18:00`, `tomorrow at 3 PM`, `next Monday at 10 AM`, `2027-10-25 at 15:00`, and `in 30 minutes`. Explicit time avoids ambiguity. Default timezone is `Asia/Kolkata`; set `ASSISTANT_TIMEZONE` in `.env` to an installed IANA timezone such as `America/New_York` (on Windows, the included `tzdata` package provides timezone data).

## Configuration

`.env.example` lists the settings. Copy to `.env` and set:

- `GROQ_API_KEY` — optional, **server-side only**; use a freshly rotated key.
- `GROQ_MODEL` — default `llama-3.1-8b-instant`; select an available model in your Groq account.
- `ASSISTANT_TIMEZONE` — default `Asia/Kolkata`.
- `ASSISTANT_PORT` — default `8765`.
- `ASSISTANT_DB` — optional database path. Default is `data/alexa_plus_v2.db`; the older uploaded database is not modified.

The server reports whether a key is configured, not whether the provider accepted it. Provider response/errors establish connection. Groq/Wikipedia questions leave the local computer to those providers. Do not enter sensitive data you would not share with them.

## Safety and operations

- Server binds to loopback (`127.0.0.1`) and checks the Host, browser Origin, and a random per-run token. Do not expose it to a public network or reverse proxy without adding authentication and a security review.
- The calendar button downloads an `.ics` file; it does not send meeting invitations. Users must import the file themselves.
- Reminders need the process running; browser notifications need an open page and permission. Closing the server stops reminder delivery. Missed events remain in SQLite.
- The UI preview can be opened separately but does not answer or save until connected to the locally running Python service.
- Python stdlib powers the app. `tzdata` is the only listed dependency (useful for Windows time zones). Browser speech support varies. No Selenium, PyAudio, or local model is required.

## Tests

From this directory run `python -m unittest discover -s tests -v`. Tests use a temporary database and local loopback HTTP only; they do not call Groq/Wikipedia or require a microphone.
