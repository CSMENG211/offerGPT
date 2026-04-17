## offerGPT

A small Python prototype for turning microphone input into text locally, then
using that text as the prompt for a later browser automation step.

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

Press ENTER to start recording, speak, then press ENTER again to stop and
transcribe.

Choose a local model size:

```sh
python main.py --model tiny
python main.py --model small
python main.py --model medium
```

### Ask ChatGPT

Install Playwright's browser once:

```sh
python -m playwright install chromium
```

Then record, transcribe, open ChatGPT, paste the transcript, and submit it:

```sh
python main.py --ask-chatgpt
```

The first time, ChatGPT may ask you to log in. The browser profile is stored at
`~/.offergpt/browser-profile`, so future runs can reuse that login.

There are two browser modes:

```sh
python main.py --ask-chatgpt --browser-mode persistent
python main.py --ask-chatgpt --browser-mode cdp
```

`persistent` launches installed Chrome with a dedicated profile. `cdp` connects
to a Chrome instance that you start with remote debugging:

```sh
open -na 'Google Chrome' --args \
  --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.offergpt/cdp-browser-profile
```

Then run:

```sh
python scripts/test_chatgpt_submit.py --browser-mode cdp
```

By default, the automation reuses an existing ChatGPT tab. To force a fresh tab:

```sh
python main.py --ask-chatgpt --new-tab
python scripts/test_chatgpt_submit.py --browser-mode cdp --new-tab
```

### Pick a Microphone

```sh
python main.py --list-mics
python main.py --device 2
```

On macOS, your terminal may ask for microphone permission the first time this
runs.
