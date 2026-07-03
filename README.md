# Solecast — Sneaker Trend Intelligence

A web app for tracking and forecasting sneaker/footwear search trends using
Google Trends data. Track keyword groups over time, compare terms, compare the
same trend across regions, detect breakout micro-trends, and read auto-generated
analysis + forecasts.

## Requirements

- **Python 3.9+** ([download here](https://www.python.org/downloads/) if you don't have it)

Check if you have it:

```bash
python3 --version
```

## Setup & Run

**1. Open a terminal and go into this folder:**

```bash
cd path/to/sneaker-trends
```

**2. (Recommended) create a virtual environment so it doesn't touch your system Python:**

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows (PowerShell)
```

**3. Install the dependencies:**

```bash
pip install -r requirements.txt
```

**4. Start the app:**

```bash
python3 app.py
```

**5. Open your browser to:**

```
http://localhost:5050
```

That's it. To stop the app, press `Ctrl+C` in the terminal.

## Notes

- **Google Trends rate limits.** Google throttles automated requests by IP. If
  you scan a lot quickly, you'll get temporarily rate-limited. When that happens
  the app automatically shows clearly-labeled **sample data** so nothing breaks —
  real data returns once the limit clears (usually a few minutes). Start with
  1–2 keywords on the **3M** timeframe and don't spam the buttons.
- **Results are cached** for 10 minutes, so re-running the same search is instant.
- **Configuration** (keyword groups + breakout terms) is editable in the
  **Configure** tab and saved to `config.json`.

## Views

- **01 Dashboard** — track a group of keywords over time, with analysis + forecast.
- **02 Compare** — benchmark up to 5 custom keywords head-to-head.
- **03 Regions** — compare the same keyword across multiple markets at once.
- **04 Breakout** — rank micro-trend keywords by momentum to spot rising trends.
- **05 Related** — see breakout & top queries searched alongside a keyword.
- **06 Configure** — customize the keyword groups and micro-trend watchlist.
