# Free Crypto Futures Research Scan
Public Binance USDⓈ-M Futures data only. No API keys, no live orders.

## Setup from Android
1. Create a **public** GitHub repository named `crypto-trigger-checker`.
2. Upload `scanner.py`, `README.md`, and `.github/workflows/scan.yml`, preserving the folder path `.github/workflows/scan.yml`.
3. Open the repository's **Actions** tab and enable workflows if asked.
4. Choose **Crypto Futures Research Scan** → **Run workflow** to test.
5. Results are committed under `data/` after a successful run. The workflow is scheduled every four hours at minute 7.

## Important
This is a research prototype, not a proven profitable system. Scores are heuristics. Funding holding costs, exact exchange filters, FX conversion, portfolio correlation and simultaneous risk are not fully modeled. The output must not be treated as verified live orders. GitHub schedules can be delayed/skipped and this is not a real-time WebSocket listener. Do not store secrets in this public repository.
