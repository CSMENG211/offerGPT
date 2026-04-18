## SecondVoice

SecondVoice is a voice-triggered GPT answer assistant for concise read-aloud
responses.

This first step captures audio from your microphone and transcribes it locally
with faster-whisper.

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

By default, SecondVoice listens continuously and submits triggered prompts to
ChatGPT.

### Listen Loop

Continuously listen for mock-interview questions, then stop the utterance after
silence:

```sh
python main.py
```

By default, listen mode catches explicit question-start phrases and transcripts
that end in a question mark, like:

```text
How would you debug this?
```

The listen loop uses three trigger layers:

```text
Audio start trigger: speech begins
Audio stop trigger: silence lasts N seconds
Question trigger: question mark detected, or explicit start phrase
```

Question start phrases, silence timing, and the local transcription model live
in `src/constants.py`.

Choose an answer style:

```sh
python main.py --mode helpful
python main.py --mode generic
```

`helpful` gives concise, useful answers for interview-style practice. `generic`
gives safe, neutral workplace answers without invented commitments.

The selected mode prompt is prepended only to the first question sent to ChatGPT
in each run.

To transcribe triggered prompts without sending them to ChatGPT:

```sh
python main.py --no-ask-chatgpt
```

### Ask ChatGPT

Install Playwright's browser once:

```sh
python -m playwright install chromium
```

Then listen, transcribe triggered prompts, open ChatGPT, paste each prompt, and
submit it:

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

### One-Shot Recording

To record one utterance manually instead of listening continuously:

```sh
python main.py --no-listen
```

On macOS, your terminal may ask for microphone permission the first time this
runs.
