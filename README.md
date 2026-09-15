<p align="center">
  <img src="assets/logo.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center">
  <a href="README.md"><b>English</b></a> |
  <a href="README.zh.md"><b>中文</b></a>
</p>

LAVOCADO is a local-first desktop protection tool for Windows and macOS.

It detects visually explicit content on screen, confirms detections across multiple frames, and displays a local intervention on the affected monitor.

Screenshots are processed locally and are **not stored or transmitted**.

## Features

- Local visual content detection
- Multi-frame confirmation to reduce false positives
- Multi-monitor support
- Application and website blocklists
- Trusted application and website whitelists
- Local dashboard for settings, rules, diagnostics, and history
- Windows 10/11 and macOS support

## Privacy

LAVOCADO is designed to keep screen content local.

It does not store:

- Screenshots or image crops
- Full URLs
- Window titles

Protection history contains only limited metadata such as the event time, trigger type, confidence, monitor number, and whether an intervention was shown.

Website rules store only the hostname, not URL paths or query parameters.

## Protection Rules

Rules can be configured from the dashboard for:

- Blocked applications
- Whitelisted applications
- Blocked websites
- Whitelisted websites

Rule priority is:

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

- **Blocked context:** protection is triggered immediately.
- **Whitelisted context:** visual protection is temporarily skipped.
- **No matching rule:** normal visual detection runs.

A blacklist always takes priority over a whitelist.

Whitelists are intended for trusted contexts such as medical, educational, artistic, or news content that may legitimately contain explicit anatomy.

## Requirements

- Python 3.12
- Windows 10/11 or macOS

## Setup

Clone the repository and create a virtual environment.

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

On macOS, allow LAVOCADO or your terminal under:

- **System Settings → Privacy & Security → Screen & System Audio Recording**
- **System Settings → Privacy & Security → Accessibility**

Screen Recording is required for protection. Accessibility is required for application and browser context detection.

## Usage

Start protection directly:

```bash
python main.py
```

Open the dashboard:

```bash
python main.py dashboard
```

The dashboard can be used to:

- Start and stop protection
- Configure application and website rules
- Change vision settings
- Manage local models
- View diagnostics
- Test the intervention
- View recent protection events

### AI typing meditation

**Recommended starting configuration: OpenAI `gpt-4o-mini`.** The model name contains the letter **o**: it is not `gpt-4-mini` or `gpt-5-mini`. This is the application's default model, and its short text conversations fit this model's intended lightweight use. See the [official model page for capabilities, pricing and limits](https://developers.openai.com/api/docs/models/gpt-4o-mini). This recommendation does not guarantee response quality or availability for every account.

#### Purpose and conversation flow

The application owns the system prompts. They explicitly describe LAVOCADO as an app for quitting pornography browsing, and the AI as a supportive companion helping the user stop viewing, close the triggering page and choose another action. Emotional support and typing meditation serve this goal. It must not shame the user, invent health consequences, promise recovery or impersonate a therapist. Knowing the product's purpose does not mean knowing what triggered this particular overlay: false positives, application rules and manual tests are possible. A trigger count is not a relapse count.

1. Local protection opens the overlay. After Pause and Breathe, the Ready stage shows the Catppuccin AI panel above the original intervention content. Continue and Exit remain independent of the AI.
2. The companion receives the product instructions, today's trigger count, a coarse time-of-day bucket and the current conversation. It should answer direct questions and respond to what the user actually says, with at most one useful follow-up question per reply. Online conversation has no fixed interview length.
3. The model returns a reflection, an optional question and a readiness signal. The application uses that signal to move toward practice once there is enough context about the user's situation, feelings or needs and a useful direction. A reply without a question does not itself start practice. The user can also choose **Start practice** early.
4. The AI introduces typing meditation and generates the first sentence. The user types and submits a response; subsequent sentences are requested one at a time using the conversation and recent practice text. There are **five rounds**, followed by a closing response. This is not five prewritten exercises fetched at startup. Submission currently requires nonempty text, not an exact character-for-character copy.
5. The user can leave at any time. Finishing the conversation or all five rounds is not a condition for the AI to authorize closing the overlay.

This is session-based personalization, **not long-term memory**. The companion does not read previous conversations or build a psychological profile from browsing history. The historical input currently used is today's aggregate trigger count. The prompts and request implementation are in [app/intervention/llm.py](app/intervention/llm.py); the dashboard does not expose a custom system-prompt editor.

The conversation language can be English or Chinese. Settings defaults to following the dashboard language; panel text, generated conversation and local guidance follow the selected language.

#### Recommended setup in Settings

1. Obtain a key from the [OpenAI API key page](https://platform.openai.com/api-keys). Check the [API billing page](https://platform.openai.com/settings/organization/billing/overview) for available credit and billing setup. API usage is billed separately from a ChatGPT subscription; buying ChatGPT Plus does not fund API calls.
2. Start `python main.py dashboard`, open Settings and find **AI typing meditation**.
3. Enter the following values, choose the conversation language and enable AI meditation:

| Field | Recommended value |
| --- | --- |
| API key | Your OpenAI API key; never share it in a screenshot or commit it |
| Model | `gpt-4o-mini` |
| Compatible endpoint | `https://api.openai.com/v1/chat/completions` |

4. Select **Save AI settings**, then **Test saved connection**. Saving alone does not send a request or prove the key works. A connection test makes a small API request and can incur a charge.
5. After a successful test, start a new **Test intervention** and try a conversation and practice. Settings take effect on the next intervention, not in an already-open AI panel. If the application's prompt code was updated, restart the application too.

The endpoint is the provider's API address, not a ChatGPT web page. A full `/chat/completions` endpoint is used as supplied; a URL ending in `/v1` has `/chat/completions` appended; other base URLs have `/v1/chat/completions` appended. Prefer the full URL above to avoid ambiguity. Never send an OpenAI key to an untrusted gateway.

#### Which providers and models work?

The current client implements **one protocol: non-streaming, OpenAI-style Chat Completions**. It sends `Authorization: Bearer ...` and a JSON body containing `model`, `messages`, `temperature` and **`max_tokens`**, then reads `choices[0].message.content`. It does not automatically select a different protocol or request shape based on the model name.

| Provider / model | Current compatibility |
| --- | --- |
| OpenAI `gpt-4o-mini` | Default and recommended configuration for the current request format. Account access, credit and network availability still need testing. |
| OpenAI `gpt-4o`, `gpt-4.1-mini` | Candidates using the same text Chat Completions format. Not separately certified end to end by this project; test both the connection and the meditation flow. See the [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) and [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) documentation. |
| OpenAI GPT-5 and reasoning models, such as `gpt-5`, `gpt-5-mini` and o-series models | **Not specifically adapted by this client.** Legacy `max_tokens`, custom temperatures, short output budgets and the timeout can be incompatible or unsuitable. Changing only the model name is not a supported migration path. |
| DeepSeek or another OpenAI-compatible provider | **Conditional protocol compatibility, not guaranteed model support.** The chosen endpoint/model must accept all the current parameters and return the expected text field within the timeout. There is no dedicated DeepSeek adapter or handling of thinking/reasoning options. A provider's compatibility claim alone is not an end-to-end test. |
| Claude / Anthropic native Messages API | **Not supported.** Its request format, authentication headers and response format need a separate adapter. An OpenAI-compatible third-party gateway is a different service, not native Claude support. |
| OpenAI Responses API, Gemini native API or other non-Chat-Completions endpoints | **Not supported by the current serializer.** Changing the endpoint field does not change the protocol. |

The endpoint is **not exclusive to mini models**. What matters is protocol and parameter compatibility, then the account's access to that model. The model field is free text, not a verified list of supported models. Check provider documentation and the saved-connection test before assuming a name works. The [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) documents model-dependent parameter restrictions.

Current implementation limits also matter: requests are non-streaming, use an 8-second network timeout and have output caps of 320 tokens for conversation, 520 for the practice introduction, 180 for each subsequent sentence and 160 for closing. The connection probe uses only 8 output tokens. These are not dashboard options, and a lightweight probe passing does not prove a longer or reasoning-heavy request will succeed. There is no automatic retry/backoff loop.

#### Connection status and local fallback

| Status | What it actually means |
| --- | --- |
| Configured / Not verified | Settings contain a key, but no successful request has been confirmed for that configuration. |
| Last test passed | The dashboard's last small test returned nonempty text. This is not continuous monitoring or a guarantee that the next meditation request will work. |
| API test failed | The saved-connection test failed; review the displayed error and configuration. |
| API NOT VERIFIED / REQUESTING API | The overlay has not verified a response yet, or is waiting for the current request. |
| API REPLY RECEIVED | The current overlay operation received a usable model response. |
| LOCAL GUIDANCE / API FAILED / LOCAL | The displayed guidance is produced by the application's local script, not a successful LLM reply. |

Dashboard test results and overlay request results are separate. Saving settings clears the previous test result; restarting also loses the in-memory test result. A previous successful test does not override a later timeout, rate limit or invalid response.

Without a key, with AI disabled, or when a request fails or its response cannot be used, the panel falls back to a fixed local guidance flow. It may select text using simple state or time information, but **it is not a free local AI model**. Fixed system introductions are also application text, not generated replies. A later request can succeed again; check the status and message speaker for the current turn. The UI waits for a response before allowing another submission, while exit remains available.

#### Privacy, context and key storage

- Remote requests include application prompts, today's trigger count, a coarse time-of-day bucket, current user and assistant messages, and recent typed practice responses. Context is bounded: individual messages are truncated and recent practice history is limited.
- LAVOCADO does not automatically attach screenshots, detection labels, confidence values, application names, URLs, window titles or browsing history to the LLM. **Anything the user types or pastes into the conversation can be sent**, including a URL or private information entered manually.
- Conversation text is kept in application memory, not written to the protection-event database or a chat history file. This does not promise that the API provider or gateway retains nothing; its own data policies apply. Using a remote LLM is distinct from local-only visual detection.
- Saved credentials are stored in a local **plaintext JSON file**, `llm_settings.json`, not the system keychain or an encrypted vault. The application attempts restrictive file permissions. Default locations are `~/Library/Application Support/LAVOCADO/llm_settings.json` on macOS and `%LOCALAPPDATA%\LAVOCADO\llm_settings.json` on Windows.
- The backend does not return the saved raw key to the dashboard or write it to protection events. Leaving the key field blank keeps the saved key; use **Clear saved API key** to remove it. Do not commit or share the settings file.

#### Environment-variable configuration

Settings is the recommended entry point. For terminal use, configure the same OpenAI model explicitly before launching:

```bash
export LAVOCADO_LLM_API_KEY="your API key"
export LAVOCADO_LLM_ENDPOINT="https://api.openai.com/v1/chat/completions"
export LAVOCADO_LLM_MODEL="gpt-4o-mini"
export LAVOCADO_LLM_LANGUAGE="en"
python main.py
```

Windows PowerShell:

```powershell
$env:LAVOCADO_LLM_API_KEY = "your API key"
$env:LAVOCADO_LLM_ENDPOINT = "https://api.openai.com/v1/chat/completions"
$env:LAVOCADO_LLM_MODEL = "gpt-4o-mini"
$env:LAVOCADO_LLM_LANGUAGE = "en"
python main.py
```

For key, endpoint and model, a nonempty saved setting takes precedence over environment variables. Environment lookup then uses `LAVOCADO_LLM_*`, followed by `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`, then `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`, independently for each field. The endpoint and model finally default to the OpenAI values above. These aliases **do not auto-detect the provider**: a DeepSeek key alone does not select a DeepSeek endpoint or model.

An explicit saved conversation language takes precedence over `LAVOCADO_LLM_LANGUAGE` (`en` or `zh`), then the dashboard language is used. Clearing a saved key can expose an environment key as the fallback. To stop remote requests regardless of environment variables, disable AI meditation in Settings.

#### Troubleshooting

| Error / symptom | Check |
| --- | --- |
| 400 / 422, request parameters rejected | Model and parameter compatibility. Adding API credit does not fix unsupported `max_tokens` or `temperature`; try the recommended configuration. |
| 401, authentication failed | Key validity and whether the key belongs to the configured provider. |
| 403, permission denied | Model/project permissions and provider regional restrictions. |
| 404, endpoint or model not found | Full endpoint URL, exact model name and account access. |
| 429, limited requests or quota | Both request-rate limits and API credit/quota; a positive balance does not eliminate rate limits. |
| Timeout, network or 5xx error | Network/TLS, provider availability and the client's short timeout; retry later. |
| Connection test passes but practice falls back | The longer request or expected structured response can still fail. Inspect the overlay's current status; a test is not a full practice validation. |
| Replies feel preset | Check whether the speaker is local guidance rather than AI. Online personalization uses this session's messages, not past conversations. Restart after prompt-code updates. |

For provider-side explanations, see [OpenAI API error codes](https://developers.openai.com/api/docs/guides/error-codes). No model or provider listed here is a promise of free, unlimited or always-available service.

### Protection history

View recent events from the terminal:

```bash
python main.py events --limit 20
```

## Self Check

Verify the local installation and required assets:

```bash
python main.py --self-check
```

This checks the application environment, settings, local database, platform integration, and required models.

## Build

Install the build dependencies:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py --model all
```

Build with PyInstaller:

```bash
python -m PyInstaller --noconfirm --clean lavocado.spec
```

The generated application is written to `dist/`.

Windows and macOS applications must be built on their respective target operating systems.

## Tests

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```
