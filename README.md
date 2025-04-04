# FiRM Market Comparator

A tool for comparing FiRM markets before and after governance changes to verify safety.

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create your `.env` file:
   ```bash
   cp .env.example .env
   ```
4. Edit the `.env` file to add your API keys:
   ```
   ALCHEMY_API_KEY=your_alchemy_api_key
   COINGECKO_API_KEY=your_coingecko_api_key
   ```

## Usage

### CLI Mode

Analyze a market directly from the command line:

```bash
python market-api.py --market 0x2D4788893DE7a4fB42106D9Db36b65463428FBD9 --vnet a2faaa07-ff72-4d7e-9f97-7ba16d356d88
```

Options:
- `--market`, `-m`: Ethereum address of the market to analyze
- `--vnet`, `-v`: Tenderly vnet ID of the fork to compare against

### API Server Mode

Run as a production API server:

```bash
python market-api.py --serve
```

Or for development:

```bash
python market-api.py --serve --dev
```

Options:
- `--serve`: Run as an API server
- `--dev`: Use Flask's development server (not for production)
- `--port`, `-p`: Port to run the server on (default: 5000)

### API Endpoints

#### POST /api/analyze

Example analysis of a market:

```bash
curl -X POST \
  http://localhost:5000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "market_address": "0x2D4788893DE7a4fB42106D9Db36b65463428FBD9",
    "vnet_id": "a2faaa07-ff72-4d7e-9f97-7ba16d356d88"
  }'
```

## Environment Variables

You can set the following environment variables in your `.env` file:

| Variable | Description |
|----------|-------------|
| `ALCHEMY_API_KEY` | Your Alchemy API key (required) |
| `COINGECKO_API_KEY` | Your CoinGecko Pro API key (required for price comparison) |

## Output

The tool provides a structured JSON output with the following sections:

1. **Market Information**: Basic details about the market and collateral token
2. **Oracle Information**: Price and oracle implementation details
3. **Liquidation Parameters**: Collateral factor, liquidation incentives, and self-liquidation risk
4. **Borrow Controller**: Implementation version and parameter changes
5. **Active Positions**: Analysis of active borrowers affected by the change
6. **Summary**: Errors, warnings, and informational messages
