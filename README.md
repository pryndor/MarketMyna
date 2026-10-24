<p align="center">
  <a href="https://marketmyna.com/"><img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/banner.png" alt="MarketMyna: AI stock analysis and ethical screening" width="760"></a>
</p>

<p align="center">
  <b>Stock analysis, screening, portfolios and alerts in one app.</b><br>
  AI analysts, Shariah screening and alerts on Telegram, for India, the US, China, Hong Kong and crypto.
</p>

<p align="center">
  <a href="https://github.com/pryndor/MarketMyna/actions/workflows/ci.yml"><img src="https://github.com/pryndor/MarketMyna/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/pryndor/MarketMyna/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License: Apache 2.0"></a>
  <a href="https://pypi.org/project/marketmyna/"><img src="https://img.shields.io/pypi/v/marketmyna?color=blue" alt="PyPI version"></a>
  <a href="https://pypi.org/project/marketmyna/"><img src="https://img.shields.io/pypi/pyversions/marketmyna" alt="Python versions"></a>
  <a href="#quick-start"><img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey" alt="Platforms"></a>
  <a href="https://github.com/pryndor/MarketMyna/stargazers"><img src="https://img.shields.io/github/stars/pryndor/MarketMyna?style=flat" alt="Stars"></a>
  <a href="https://github.com/sponsors/pryndor"><img src="https://img.shields.io/badge/Sponsor-GitHub-EA4AAA?logo=githubsponsors&logoColor=white" alt="Sponsor"></a>
</p>

<p align="center">
  <a href="https://marketmyna.com/"><b>Try it online</b></a> ·
  <a href="#quick-start"><b>Run your own copy</b></a> ·
  <a href="#features"><b>Features</b></a> ·
  <a href="https://github.com/pryndor/MarketMyna/issues"><b>Report a bug</b></a>
</p>

Use it at **<https://marketmyna.com/>**, or run your own copy with `pipx install marketmyna`. Your copy has no sign-up,
no login, no plans and no limits: it has one owner (you), and every feature is on.

> MarketMyna is an analysis tool, not investment advice.

## Features

<table>
  <tr>
    <td width="45%" valign="top">
      <h3>🤖 AI analysis</h3>
      A set of AI analysts (technical, risk, news) explains a stock in plain language, with a
      bullish / neutral / bearish outlook, never a buy or sell call. Paste your own key (Gemini, OpenAI,
      Claude, Groq, OpenRouter, DeepSeek, Mistral) or point it at a local Ollama.
    </td>
    <td width="55%"><img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/analyze.webp" alt="AI analysis of a stock"></td>
  </tr>
  <tr>
    <td width="55%"><img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/screener.webp" alt="Markets: every listing with the ethical filter and the insights menu"></td>
    <td width="45%" valign="top">
      <h3>🔎 Screeners and Shariah screening</h3>
      India (NSE, BSE, mutual funds, ETFs), US, China A-shares, Hong Kong and crypto, with ready-made
      and custom screens. Ethical / Shariah checks for stocks, mutual funds and ETFs, with dividend
      purification.
    </td>
  </tr>
  <tr>
    <td width="45%" valign="top">
      <h3>🧭 Market insights</h3>
      Sector and fund rotation, trending stocks, market mood, FII / DII flows, world markets, rates
      and macro, all on one page.
    </td>
    <td width="55%"><img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/sector-rotation.webp" alt="Sector rotation chart"></td>
  </tr>
  <tr>
    <td width="55%"><img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/bot-console.webp" alt="Bot console with chat commands"></td>
    <td width="45%" valign="top">
      <h3>💬 Telegram bot and console</h3>
      Every tool is also a chat command. Ask the Telegram bot, or use the same commands in the
      built-in console.
    </td>
  </tr>
</table>

| | |
| --- | --- |
| 📈 **Charts and trading tools** | Candlestick charts and indicators, scanner, backtesting, options payoff, pairs trading, position sizing, trading journal |
| 💼 **Portfolios and funds** | Holdings and returns, CAS import, fund overlap, SIP planner, XIRR |
| 🔔 **Alerts and scheduled reports** | Telegram, email, browser push, Discord, Slack, Teams, ntfy and more, on any schedule you like |
| 🔀 **Trader and Investor areas** | One switch flips the menus and pages between short-term trading tools and long-term investing |
| 🌍 **Seven languages** | The whole app, with light and dark themes |
| 🔒 **Private by default** | One SQLite file on your computer; nothing leaves it except calls to the data and AI providers you choose |

<details>
<summary><b>More screenshots</b></summary>
<br>

| Compare stocks side by side | Scheduled reports |
| --- | --- |
| <img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/compare.webp" alt="Compare up to five stocks: performance, returns and risk"> | <img src="https://raw.githubusercontent.com/pryndor/MarketMyna/main/docs/images/scheduled-reports.webp" alt="Choosing what goes into scheduled reports"> |

</details>

## Quick start

MarketMyna is on [PyPI](https://pypi.org/project/marketmyna/). With
[Python 3.11 or newer](https://www.python.org/downloads/) on Linux, macOS or Windows:

```bash
pipx install marketmyna
marketmyna
```

The app opens in your browser at <http://127.0.0.1:8001>. Paste an AI key in **Settings** and look up any stock.
No Node.js and no git needed: the web app comes inside the package.

**No pipx?** Install it ([how to install pipx](https://pipx.pypa.io/stable/installation/)), or use `pip` in a
virtual environment:

```bash
python3 -m venv ~/marketmyna-venv           # Windows: py -m venv %USERPROFILE%\marketmyna-venv
. ~/marketmyna-venv/bin/activate            # Windows: %USERPROFILE%\marketmyna-venv\Scripts\activate
pip install marketmyna
marketmyna
```

**Update:** **Settings -> Updates -> Update now** in the app, or `pipx upgrade marketmyna`
(`pip install --upgrade marketmyna` in a venv). Your data is kept.

**Your data** (database, settings, keys, cache) lives in `~/.marketmyna`; set `MARKETMYNA_HOME` to use another
folder. Uninstalling (`pipx uninstall marketmyna`) leaves it in place.

**Options:** `marketmyna --port 9000`, `marketmyna --no-browser`, `marketmyna --version`.

## Run it from the source code

To follow the latest code with `git pull`, or to change it. Runs on **Linux, macOS and Windows** (tested on all three on every change). Needs
[Python 3.12](https://www.python.org/downloads/) and [Node.js 22](https://nodejs.org/). All your data goes
into one SQLite file, so there is no database server to set up.

**1. Get the code and install** (one time)

Linux and macOS:

```bash
git clone https://github.com/pryndor/MarketMyna.git marketmyna
cd marketmyna
python3 -m venv venv
. venv/bin/activate
pip install -r requirements-web.txt
```

Windows (PowerShell):

```powershell
git clone https://github.com/pryndor/MarketMyna.git marketmyna
cd marketmyna
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements-web.txt
```

If PowerShell refuses to run the activate script, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt with `venv\Scripts\activate.bat`.

**2. Start it** (every time; activate the venv first as above)

```bash
python start.py
```

The first start builds the frontend (about a minute), then the app opens in your browser at
<http://127.0.0.1:8001>. Other options: `--port 9000`, `--no-browser`, `--rebuild`.

**3. Update** (whenever you like)

```bash
git pull
pip install -r requirements-web.txt
python start.py
```

The frontend rebuilds by itself when it has changed, and your data is kept.

Then open <http://127.0.0.1:8001> and go to **Settings**:

- **AI keys**: paste a key; add several for automatic fallback.
- **Notifications**: Telegram, email and the other channels, and which messages go where.
- **Data sources** (optional): live US prices, backup price sources, Reddit.

Everything can also be set with environment variables; `.env.example` lists them.

Run only one copy at a time: the scheduler, price alerts and the Telegram bot run inside it.

### Your data

Everything is under `~/.marketmyna` (on Windows `C:\Users\<you>\.marketmyna`; set `MARKETMYNA_HOME` to use
another folder):

- `marketmyna.db`: the SQLite database (watchlists, portfolios, alerts, journal, reports, settings).
  The tables are created on first start, and columns are added on later updates.
- `config.json` and `secret.key`: your settings, and the key that encrypts saved API keys and passwords.

To back up or move the app, copy the whole folder while the API is stopped. An existing `stockpulse.db` from
before the rename is still used.

### Keep it private

There is no login, so **anyone who can reach the port can use the app and see your data.**
The app listens on `127.0.0.1` only by default, so only this computer can reach it. To use it from your
phone, use a private network such as Tailscale or WireGuard. Don't open the port to the internet.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Install the requirements first` | Activate the venv, then `pip install -r requirements-web.txt` |
| `The frontend is built once with Node.js 22` | Install [Node.js 22](https://nodejs.org/) and run `python start.py` again |
| `marketmyna: command not found` after `pipx install` | Run `pipx ensurepath`, then open a new terminal |
| Port 8001 is already in use | Another copy is running, or use `--port 9000` |
| The page looks old after an update | Source install: `python start.py --rebuild`. pipx: reload the page with Ctrl+Shift+R |
| AI analysis says no key | Add a key in **Settings → AI keys**, or point it at a local Ollama |

Still stuck? [Open an issue](https://github.com/pryndor/MarketMyna/issues) with your OS, Python version
and the error text.

## Development

Run the API on its own, and the Vite dev server for live reload of the frontend:

```bash
python -m uvicorn marketmyna.api.app:app --port 8001 --reload
cd frontend && npm run dev   # another terminal: http://localhost:5174, sends /api to :8001
```

If the API runs on another port, start the frontend with `MARKETMYNA_API=http://127.0.0.1:<port> npm run dev`.

Tests: `pip install pytest && python -m pytest -q`. GitHub Actions runs them, builds the frontend and starts the
app on Linux, Windows and macOS for every push (`.github/workflows/ci.yml`).

## Layout

| Folder | What's in it |
| --- | --- |
| `start.py` | Starts the app from the source code (builds the frontend when needed) |
| `marketmyna/` | The Python package: data, analysis, AI agents, scheduler, alerts, notifiers, SQLite storage |
| `marketmyna/api/` | FastAPI app and routes; it also serves the built frontend |
| `marketmyna/strategies/` | AI strategy playbooks |
| `frontend/` | React + Vite + Tailwind app |
| `tests/` | pytest suite |

## Built with

[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white)](https://vite.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![LiteLLM](https://img.shields.io/badge/AI-LiteLLM-8A2BE2)](https://github.com/BerriAI/litellm)
[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Node.js](https://img.shields.io/badge/node.js-22-5FA04E?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## Roadmap

- More options for scheduled reports: what goes in them, when they run, and where they are sent
- More markets and data sources
- More AI analysts and strategy playbooks

Ideas and requests are welcome in [Issues](https://github.com/pryndor/MarketMyna/issues).

## Support

MarketMyna is free and open source. If it helps you, you can support its development:

- [GitHub Sponsors](https://github.com/sponsors/pryndor), monthly or one-time
- [Buy Me A Coffee](https://www.buymeacoffee.com/lixplore)

<a href="https://www.buymeacoffee.com/lixplore" target="_blank" rel="noopener noreferrer"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50"></a>

## License

MarketMyna is free and open source under the **[Apache License 2.0](https://github.com/pryndor/MarketMyna/blob/main/LICENSE)**.
Copyright 2026 Balasubramanian Periannan; see [NOTICE](https://github.com/pryndor/MarketMyna/blob/main/NOTICE).

In short (the [LICENSE](https://github.com/pryndor/MarketMyna/blob/main/LICENSE) file is what counts):

| You can | As long as you |
| --- | --- |
| Use it for anything, personal or commercial | Keep the copyright, license and [NOTICE](https://github.com/pryndor/MarketMyna/blob/main/NOTICE) |
| Change it, and keep your changes private if you want | Mark the files you changed when you share them |
| Run it as a website or service for other people | Don't use the MarketMyna name or logo for your copy |
| Share copies or build it into your own product, open or closed | Include a copy of the license |

The license also gives you a patent license from the contributors. It comes with no warranty, and the
authors are not liable for any loss.

### Contributing

Pull requests are welcome. Contributions are accepted under the Apache License 2.0; see
[CONTRIBUTING.md](https://github.com/pryndor/MarketMyna/blob/main/CONTRIBUTING.md).

### Name and logo

The license does not cover the MarketMyna name and logos (`frontend/public/brand/`).
If you publish a changed copy, give it your own name and logo.

### Third-party software

Each package the app installs keeps its own license. The frontend packages and the Python packages are MIT,
BSD, ISC or Apache-2.0, except PyMuPDF (AGPL-3.0), which is used only to make PDF reports. If you ship
MarketMyna inside a closed product, check PyMuPDF's terms or remove it.

### Not investment advice

MarketMyna is an analysis tool. Nothing it shows is investment advice, and you trade at your own risk.
