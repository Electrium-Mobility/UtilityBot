# UtilityBot Project Structure and Development Guidelines

This repository hosts a Python Discord bot that integrates multiple features. To avoid conflicts during parallel development, the following structure and guidelines clarify where each team should work.

## Project Structure

```
UtilityBot/
├── README.md
├── requirements.txt
├── .env.example
├── LICENSE
├── .gitignore
└── bot/
    ├── __init__.py
    ├── main.py                # Entry point: load and run the bot
    ├── config.py              # Read configuration and environment variables
    ├── core/                  # Core infrastructure
    │   ├── __init__.py
    │   ├── logging.py         # Logging initialization
    │   └── loader.py          # Auto-load feature extensions
    └── features/              # Feature modules (develop inside your folder)
        ├── smart_qa/
        │   ├── __init__.py
        │   └── cog.py         # Smart Q&A placeholder
        ├── auto_pr_review/
        │   ├── __init__.py
        │   └── cog.py         # Auto PR Review Assistant placeholder
        ├── meeting_notes/
        │   ├── __init__.py
        │   └── cog.py         # Meeting Notes Generator placeholder
        ├── random_idea/
        │   ├── __init__.py
        │   └── cog.py         # Random Idea Generator placeholder
        └── daily_challenge/
            ├── __init__.py
            └── cog.py         # Daily Challenge placeholder
```

## Development Guidelines

- Each feature module should implement a `discord.ext.commands.Cog` in `bot/features/<module>/cog.py`, and expose `async def setup(bot)` for extension loading.
- `bot/main.py` automatically scans and loads all `cog.py` extensions under `features`, no manual registration needed in the entry.
- Teams should only develop inside their own module directory to avoid cross-module edits.
- If you need shared utilities or infrastructure, add them under `bot/core/` and update this README accordingly.

## How to Run

1. Install dependencies:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure environment variables (copy `.env.example` to `.env` and fill your token):
   ```env
   DISCORD_TOKEN=YourDiscordBotToken
   ```

3. Start the bot:
   ```bash
   python -m bot.main
   ```

## Modules and Responsibilities

- `smart_qa/`: Smart Q&A.
- `auto_pr_review/`: Auto PR Review Assistant.
- `meeting_notes/`: Meeting Notes Generator.
- `random_idea/`: Random Idea Generator.
- `daily_challenge/`: Daily Challenge.

## Branching and Collaboration

- Each team should create and work on their feature branch, for example:
  - `feature/smart-qa`
  - `feature/auto-pr-review`
  - `feature/meeting-notes`
  - `feature/random-idea`
  - `feature/daily-challenge`
- When raising a PR, ensure changes are limited to your module directory. If shared code (`bot/core` or entry) is involved, discuss with the team and update this README.