# Uma Club Helper Bot

A Discord bot for parsing veteran Umamusume screenshots and automatically running simulations with pre-filled data.

## Youtube Preview

https://www.youtube.com/watch?v=dNzNqTIrdrQ

[![](docs/thumbnail.png)](https://www.youtube.com/watch?v=dNzNqTIrdrQ)

## Features

- **Veteran Screenshot Parsing**: Upload screenshots of veteran Umamusume characters to automatically extract character data (name, stats, skills, aptitudes) using OpenCV and PaddleOCR
- **Simulator Integration**: Automatically fills extracted data into the simulator (alpha123 and kachi-dev) and returns pre-configured simulator URLs
- **Compare Mode**: Compare two characters side-by-side when uploading two screenshots

## Setup

### Prerequisites

- Python 3.10+
- Discord bot token
- PaddleOCR models (auto-downloaded on first run)

### Option 1: Docker Compose (Recommended)

1. Copy `example.env` to `production.env` and configure:
   - Discord bot credentials

2. Run with Docker Compose:
   ```bash
   docker-compose up --build -d
   ```

### Option 2: Manual Python Setup

1. Copy `example.env` to `.env` and configure:
   - Discord bot credentials

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install Playwright browsers:
   ```bash
   playwright install --force --with-deps
   ```

5. Run the bot:
   ```bash
   python main.py
   ```

## Commands

### Basic

- `/ping` - Check if the bot is responsive

### Veteran Screenshot Processing

- `/setup-channel-veteran-uma` - Toggle current channel for processing veteran uma screenshots (requires administrator)

### Preset Management

- `/create-preset <name>` - Create a new simulator preset with track, length, ground, weather, and season settings
- `/list-presets` - List all custom presets
- `/delete-preset` - Delete an existing preset

### Development

- `/nuke-db` - [DEV] Drop and recreate all database tables (requires administrator, DEV environment only)

## Usage

### Veteran Screenshot Processing

1. Use `/setup-channel-veteran-uma` in a channel to enable screenshot processing
2. Upload one or two screenshots of veteran Umamusume characters to the configured channel
3. The bot will:
   - Parse the screenshot(s) to extract character name, stats (Speed/Stamina/Power/Guts/Wit), skills, and aptitudes
   - Create a thread for the analysis
   - Prompt you to select a running style (Front/Pace/Late/End) and simulator preset
   - Automatically fill the data into the simulator
   - Run the simulation and return pre-configured simulator URLs (alpha123 and kachi-dev) with a screenshot

The bot supports comparing two characters side-by-side when two screenshots are uploaded.

## Supported Simulators

- [alpha123](https://github.com/alpha123/uma-tools) - https://alpha123.github.io/uma-tools/umalator-global/
- [kachi-dev](https://github.com/kachi-dev/uma-tools) - https://kachi-dev.github.io/uma-tools/umalator-global/

## Tech Stack

- **Discord.py** - Discord API wrapper
- **Playwright** - Browser automation for simulator interaction
- **PaddleOCR** - OCR for screenshot parsing
- **SQLite** - Local database for presets and configurations
