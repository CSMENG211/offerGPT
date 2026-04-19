## SecondVoice

SecondVoice is a voice-triggered mock interview evaluator.

It captures audio from your microphone, transcribes it locally with
faster-whisper, and sends each transcript segment to ChatGPT for role
classification, context tracking, and answer feedback.

### Setup

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```sh
python main.py
```

By default, SecondVoice streams continuously and submits transcript segments to
ChatGPT.

Logs are written to `python.log` in the current working directory.

### Stream Mode

Continuously record mock-interview segments, transcribe each segment, and submit
it to ChatGPT:

```sh
python main.py
```

Recording starts automatically when speech begins. After 5 seconds of silence,
SecondVoice transcribes that segment, sends it to ChatGPT, and continues
listening. ChatGPT classifies the segment as interviewer or interviewee.
Interviewer segments are added to the problem context; interviewee segments get
an ideal response and evaluation against that ideal.

To only print transcripts without sending them to ChatGPT:

```sh
python main.py --no-ask-chatgpt
```

### Ask ChatGPT

Install Playwright's browser once:

```sh
python -m playwright install chromium
```

Then stream, transcribe segments, open ChatGPT, paste each prompt, and submit it:

```sh
python main.py
```

The first time, ChatGPT may ask you to log in. The browser profile is stored at
`~/.secondvoice/browser-profile`, so future runs can reuse that login.

There are two browser modes:

```sh
python main.py --browser-mode cdp
python main.py --browser-mode persistent
```

`cdp` is the default and connects to a Chrome instance that you start with
remote debugging. `persistent` launches installed Chrome with a dedicated
profile.

```sh
open -na 'Google Chrome' --args \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.secondvoice/cdp-browser-profile
```

Then run:

```sh
python main.py --browser-mode cdp
```

On macOS, your terminal may ask for microphone permission the first time this
runs.
