# Run the project locally on Windows (Command Prompt + VS Code)

Everything below is typed into **Command Prompt** (`cmd.exe`). Inside VS Code, open a
Command Prompt terminal with **Terminal > New Terminal**, then the `v` arrow next to the
`+` > **Command Prompt** (VS Code's default terminal on Windows is PowerShell; PowerShell
differences are listed at the end).

You need: Git, Python 3.11+ (`python --version`), Node.js 20+ (`node --version`),
VS Code with the `code` command on PATH (VS Code > `Ctrl+Shift+P` > "Shell Command:
Install 'code' command in PATH"), and the Olist snapshot `brazil_ecommerce.sqlite`.

## 1. Get the code and open it in VS Code

First time:

```bat
cd %USERPROFILE%\Documents
git clone https://github.com/mra-2007/Data_Scientist_Agent.git
cd Data_Scientist_Agent
git checkout major-project-update
code .
```

Already cloned:

```bat
cd %USERPROFILE%\Documents\Data_Scientist_Agent
git fetch origin
git checkout major-project-update
git pull origin major-project-update
code .
```

`code .` opens the folder in VS Code. Run the rest in VS Code's Command Prompt terminal.

## 2. Python environment (once)

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e "backend[dev]"
pip install -r TextToSQL\requirements-dev.txt
```

Every new terminal needs `.venv\Scripts\activate` again (the prompt then starts with `(.venv)`).

## 3. Build the V2 database (once, and after every pull that changes `scripts/synth` or `semantics`)

Copy `brazil_ecommerce.sqlite` into the repository root, then:

```bat
python scripts\build_v2.py --source brazil_ecommerce.sqlite
```

This writes `data\brazil_ecommerce_v2.sqlite`: the real tables copied verbatim, the ten
synthetic tables, the precomputed analytical tables and the indexes. The snapshot itself is
opened read-only and never changed. It takes a few minutes.

**This step is what fixes "What if we raise prices 5%?" showing INSUFFICIENT EVIDENCE.**
The raw snapshot has no price history, no promotions, no marketing or stock data, no
analytical tables and no indexes; a backend started on it can only refuse those questions,
and slow, unindexed queries can time out on others.

No snapshot? `python scripts\build_v2.py --fixture` builds the same thing from a small
seeded stand-in (its figures describe nothing real).

## 4. Terminal 1 - the backend

```bat
cd %USERPROFILE%\Documents\Data_Scientist_Agent
.venv\Scripts\activate
set DS_AGENT_DB=%CD%\data\brazil_ecommerce_v2.sqlite
set DS_AGENT_TOKEN=replace-with-any-random-text-of-32-or-more-characters
python scripts\check_setup.py
```

`check_setup.py` must end with `OK`. It prints which database the backend will open and
what it is missing, with the fix. Then start the API from **the same terminal** (the
`set` values only exist in that window):

```bat
cd backend
python -m uvicorn app:app --app-dir src --port 8000
```

Leave it running. `http://127.0.0.1:8000/docs` shows the API.

## 5. Terminal 2 - the web app

Open a second Command Prompt terminal (`+` > Command Prompt):

```bat
cd %USERPROFILE%\Documents\Data_Scientist_Agent\frontend\web
set DS_AGENT_TOKEN=replace-with-any-random-text-of-32-or-more-characters
npm install
npm run dev
```

Use **exactly the same token** as terminal 1 (the dev server forwards it to the API; a
different or missing token gives "401 Bearer authentication is required"). Then open
**http://localhost:5173**.

`npm install` is needed once, and again after a pull that changes `package.json`.

## 6. Check that it works

With both terminals running, in a third terminal:

```bat
cd %USERPROFILE%\Documents\Data_Scientist_Agent
.venv\Scripts\activate
set DS_AGENT_TOKEN=replace-with-any-random-text-of-32-or-more-characters
python scripts\verify_demo.py --base-url http://127.0.0.1:8000 --token %DS_AGENT_TOKEN%
```

It asks every demo question through the running backend and must print `18/18 demo steps
passed`. In the browser, click **New topic**, then the **What if we raise prices 5%?** chip:
the plan shows four steps (an analytical table, the baseline, the price panel, the scenario)
and the answer states the fitted elasticity with its interval.

Optional, with the backend stopped: `python -m pytest backend\tests -q`.

## Every day after that

```bat
cd %USERPROFILE%\Documents\Data_Scientist_Agent
git pull origin major-project-update
code .
```

Then terminal 1 (step 4, from `.venv\Scripts\activate`) and terminal 2 (step 5, without
`npm install`).

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "What if we raise prices 5%?" -> INSUFFICIENT EVIDENCE, plan has 3 steps | the backend is on the raw snapshot | step 3, then `set DS_AGENT_DB=...` in the backend terminal and restart it; `check_setup.py` shows which file is in use |
| the answer says "Only price-change scenarios have a fitted response..." | old code | `git pull origin major-project-update`, restart the backend |
| 401 in the browser | token differs between the two terminals, or set only in one | same `set DS_AGENT_TOKEN=...` in both, restart both |
| the top bar says **OFFLINE** instead of **LIVE** | terminal 1 is not running or not on port 8000 | start it (step 4) |
| `'python' is not recognized` | Python not on PATH | reinstall Python with "Add python.exe to PATH" ticked, or use `py` instead of `python` |
| `code` is not recognized | the VS Code shell command is missing | VS Code > `Ctrl+Shift+P` > "Shell Command: Install 'code' command in PATH", open a new Command Prompt |
| an old answer still shows | the app restores the last answers from browser storage | click **New topic** and ask again |
| `build_v2.py` cannot open a file | the folder path contains `#` or `?` | move the repository to a plain path such as `C:\dev\Data_Scientist_Agent` |

## PowerShell equivalents

| Command Prompt | PowerShell |
| --- | --- |
| `.venv\Scripts\activate` | `.\.venv\Scripts\Activate.ps1` (if blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once) |
| `set DS_AGENT_DB=%CD%\data\brazil_ecommerce_v2.sqlite` | `$env:DS_AGENT_DB = "$PWD\data\brazil_ecommerce_v2.sqlite"` |
| `set DS_AGENT_TOKEN=...` | `$env:DS_AGENT_TOKEN = "..."` |
| `%USERPROFILE%` | `$HOME` |
| `--token %DS_AGENT_TOKEN%` | `--token $env:DS_AGENT_TOKEN` |
