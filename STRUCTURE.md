# Project Structure

The `New-Structure` branch organizes the bot into clear layers:

- `main.py` — application entry point and event wiring.
- `bot/core/` — bot construction and startup primitives.
- `bot/config/` — shared settings, intents, prefixes, and constants.
- `bot/cogs/` — Discord commands and event-facing feature modules.
- `bot/services/` — reusable business logic such as leveling, music, search, and health checks.
- `bot/models/` — persistence and data-access logic for XP and distro data.
- `tests/` — automated tests for cogs, services, and storage.
- `distro/` — distro images and guessing-game metadata.

Keep Discord command handling in `bot/cogs/`, reusable logic in `bot/services/`, and persistence code in `bot/models/` so each layer remains easier to test and maintain.
