#!/usr/bin/env python3
from web3 import Web3
import os
from decimal import Decimal
import json
import requests
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Try to load environment variables from .env file
load_dotenv()

# ABIs - unchanged from original
MARKET_ABI = [
    {"inputs": [], "name": "borrowController", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "oracle", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "collateral", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "collateralFactorBps", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "liquidationIncentiveBps", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "liquidationFeeBps", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType":"address","name":"","type":"address"}],"name":"debts","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"user","type":"address"}],"name":"getCollateralValue","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"user","type":"address"}],"name":"getCreditLimit","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "account",
                "type": "address"
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256"
            }
        ],
        "name": "Borrow",
        "type": "event"
    },
]

ORACLE_ABI = [
    {"inputs": [{"internalType": "address", "name": "token", "type": "address"}, {"internalType": "uint256", "name": "collateralFactorBps", "type": "uint256"}], "name": "getPrice", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

BORROW_CONTROLLER_ABI = [
    {"inputs":[{"internalType":"address","name":"","type":"address"}],"name":"dailyLimits","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"","type":"address"}],"name":"minDebts","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]

ERC20_ABI = [
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name", "outputs": [{"internalType": "uint8", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "uint8", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"}
]

DBR_ABI = [
    {"inputs": [{"internalType": "address", "name": "", "type": "address"}], "name": "markets", "outputs": [{"internalType": "bool", "name": "", "type": "bool"}], "stateMutability": "view", "type": "function"}
]

# Contract addresses
newest_borrow_controller = Web3.to_checksum_address("0x01ECA33e20a4c379Bd8A5361f896A7dd2bAE4ce8")
newest_oracle = Web3.to_checksum_address("0xaBe146CF570FD27ddD985895ce9B138a7110cce8")
dbr_address = Web3.to_checksum_address("0xAD038Eb671c44b853887A7E32528FaB35dC5D710")
governor_mills = Web3.to_checksum_address("0xBeCCB6bb0aa4ab551966A7E4B97cec74bb359Bf6")

class MarketComparator:
    def __init__(self, market_address, vnet_id):
        self.market_address = market_address
        # Read API keys from environment variables
        alchemy_api_key = os.environ.get("ALCHEMY_API_KEY")
        if not alchemy_api_key:
            raise ValueError("ALCHEMY_API_KEY environment variable is not set. Please add it to your .env file.")
            
        self.w3 = Web3(Web3.HTTPProvider(os.environ.get("RPC_MAINNET", f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_api_key}")))
        self.w3_fork = Web3(Web3.HTTPProvider(os.environ.get("RPC_TENDERLY", f"https://virtual.mainnet.rpc.tenderly.co/{vnet_id}")))
        self.market = self.w3.eth.contract(address=market_address, abi=MARKET_ABI)
        self.market_fork = self.w3_fork.eth.contract(address=market_address, abi=MARKET_ABI)
        self.collateral_address = self.market.functions.collateral().call()
        self.collateral = self.w3.eth.contract(address=self.collateral_address, abi=ERC20_ABI)
        self.results = {
            "market": {},
            "oracle": {},
            "liquidation": {},
            "borrow_controller": {},
            "active_positions": {
                "borrowers": []
            },
            "summary": {
                "errors": [],
                "warnings": [],
                "info": []
            }
        }

    def analyze_market(self):
        """Main function to analyze a market and return JSON results"""
        self.check_market()
        self.check_oracle()
        self.check_liquidations()
        self.check_borrow_controller()
        self.check_active_position_changes()
        return self.results

    def add_error(self, message, category):
        """Add an error to the summary and to the specific category"""
        self.results["summary"]["errors"].append({"message": message, "category": category})

    def add_warning(self, message, category):
        """Add a warning to the summary and to the specific category"""
        self.results["summary"]["warnings"].append({"message": message, "category": category})

    def add_info(self, message, category):
        """Add an informational message to the summary and to the specific category"""
        self.results["summary"]["info"].append({"message": message, "category": category})

    def check_market(self):
        """Check basic market information"""
        market_data = {
            "address": self.market_address,
            "collateral": {
                "address": self.collateral_address
            }
        }

        try:
            market_data["collateral"]["symbol"] = self.collateral.functions.symbol().call()
            market_data["collateral"]["name"] = self.collateral.functions.name().call()
            market_data["collateral"]["decimals"] = self.collateral.functions.decimals().call()
        except Exception as e:
            market_data["collateral"]["error"] = str(e)
            self.add_error(f"Failed to get collateral token details: {str(e)}", "market")

        # Check if market is allowed in DBR
        try:
            dbr = self.w3.eth.contract(address=dbr_address, abi=DBR_ABI)
            market_data["dbr_allowed"] = dbr.functions.markets(self.market_address).call()
            if not market_data["dbr_allowed"]:
                self.add_error("Market is NOT allowed in DBR contract", "market")
        except Exception as e:
            market_data["dbr_error"] = str(e)
            self.add_error(f"Failed to check DBR allowance: {str(e)}", "market")

        self.results["market"] = market_data

    def check_borrow_controller(self):
        """Check borrow controller configuration"""
        try:
            borrow_controller_address = self.market.functions.borrowController().call()
            borrow_controller_address_fork = self.market_fork.functions.borrowController().call()
            borrow_controller = self.w3.eth.contract(address=borrow_controller_address, abi=BORROW_CONTROLLER_ABI)
            borrow_controller_fork = self.w3_fork.eth.contract(address=borrow_controller_address_fork, abi=BORROW_CONTROLLER_ABI)

            borrow_data = {
                "address": {
                    "before": borrow_controller_address,
                    "after": borrow_controller_address_fork
                },
                "is_newest": borrow_controller_address_fork == newest_borrow_controller
            }

            if not borrow_data["is_newest"]:
                self.add_warning("BorrowController isn't newest implementation", "borrow_controller")
                
            if borrow_controller_address != borrow_controller_address_fork:
                self.add_info(f"Borrow controller address changed from {borrow_controller_address} to {borrow_controller_address_fork}", "borrow_controller")

            min_debt = borrow_controller.functions.minDebts(self.market_address).call()
            min_debt_fork = borrow_controller_fork.functions.minDebts(self.market_address).call()
            borrow_data["min_debt"] = {
                "before": min_debt / 10**18,
                "after": min_debt_fork / 10**18
            }
            
            if min_debt != min_debt_fork:
                self.add_info(f"Min debt changed from ${min_debt / 10**18} to ${min_debt_fork / 10**18}", "borrow_controller")

            daily_limit = borrow_controller.functions.dailyLimits(self.market_address).call()
            daily_limit_fork = borrow_controller_fork.functions.dailyLimits(self.market_address).call()
            borrow_data["daily_limit"] = {
                "before": daily_limit / 10**18,
                "after": daily_limit_fork / 10**18
            }
            
            if daily_limit != daily_limit_fork:
                self.add_info(f"Daily limit changed from ${daily_limit / 10**18} to ${daily_limit_fork / 10**18}", "borrow_controller")

            self.results["borrow_controller"] = borrow_data
        except Exception as e:
            self.results["borrow_controller"]["error"] = str(e)
            self.add_error(f"Failed to check borrow controller: {str(e)}", "borrow_controller")

    def check_oracle(self):
        """Check oracle configuration and price data"""
        try:
            oracle_address = self.market.functions.oracle().call()
            oracle_address_fork = self.market_fork.functions.oracle().call()
            oracle = self.w3.eth.contract(address=oracle_address, abi=ORACLE_ABI)
            oracle_fork = self.w3_fork.eth.contract(address=oracle_address_fork, abi=ORACLE_ABI)

            oracle_data = {
                "address": {
                    "before": oracle_address,
                    "after": oracle_address_fork
                },
                "is_newest": oracle_address_fork == newest_oracle
            }

            if not oracle_data["is_newest"]:
                self.add_warning("Oracle isn't newest implementation", "oracle")
                
            if oracle_address != oracle_address_fork:
                self.add_info(f"Oracle address changed from {oracle_address} to {oracle_address_fork}", "oracle")

            # Get collateral factor and decimals
            cf_fork = self.market_fork.functions.collateralFactorBps().call()
            decimals = self.collateral.functions.decimals().call()
            
            # Calculate unit size and price
            unit_size = 10 ** decimals
            price = oracle_fork.functions.getPrice(self.collateral_address, cf_fork).call()
            ether = 10 ** 18
            unit_price = unit_size * price // ether
            
            oracle_data["price"] = {
                "raw": price,
                "unit_price_usd": unit_price / 10**18
            }
            
            # Validate price
            if unit_price == 0:
                self.add_error("Oracle price is 0", "oracle")
            elif unit_price < 10**16:
                self.add_warning("Unit price is less than $0.01", "oracle")
            elif unit_price > 10_000 * (10**18):
                self.add_warning("Unit price is above $10,000", "oracle")
            
            # Compare with Coingecko price
            coingecko_price = self.get_coingecko_price()
            if coingecko_price:
                oracle_deviation = unit_price / 10**18 / coingecko_price
                oracle_data["coingecko_comparison"] = {
                    "coingecko_price": coingecko_price,
                    "deviation_percent": (oracle_deviation - 1) * 100
                }
                
                # Add warning if deviation is significant
                if abs(oracle_deviation - 1) > 0.1:  # 10% deviation
                    self.add_warning(f"Oracle price deviates by {(oracle_deviation - 1) * 100:.2f}% from Coingecko", "oracle")

            self.results["oracle"] = oracle_data
        except Exception as e:
            self.results["oracle"]["error"] = str(e)
            self.add_error(f"Failed to check oracle: {str(e)}", "oracle")

    def check_liquidations(self):
        """Check liquidation parameters and safety"""
        try:
            cf = self.market.functions.collateralFactorBps().call()
            li = self.market.functions.liquidationIncentiveBps().call()
            lf = self.market.functions.liquidationFeeBps().call()
            cf_fork = self.market_fork.functions.collateralFactorBps().call()
            li_fork = self.market_fork.functions.liquidationIncentiveBps().call()
            lf_fork = self.market_fork.functions.liquidationFeeBps().call()
            
            liquidation_data = {
                "collateral_factor": {
                    "before": cf / 100,  # Convert to percentage
                    "after": cf_fork / 100
                },
                "liquidation_incentive": {
                    "before": li / 100,
                    "after": li_fork / 100
                },
                "liquidation_fee": {
                    "before": lf / 100,
                    "after": lf_fork / 100
                }
            }
            
            if cf != cf_fork:
                self.add_info(f"Collateral factor changed from {cf / 100}% to {cf_fork / 100}%", "liquidation")
                
            if li != li_fork:
                self.add_info(f"Liquidation incentive changed from {li / 100}% to {li_fork / 100}%", "liquidation")
                
            if lf != lf_fork:
                self.add_info(f"Liquidation fee changed from {lf / 100}% to {lf_fork / 100}%", "liquidation")
            
            # Check for unsafe parameters
            if cf_fork == 0:
                self.add_error("Collateral Factor is 0%", "liquidation")
            elif cf_fork == 10000:
                self.add_error("Collateral Factor is 100%", "liquidation")
            elif cf_fork > 9000:
                self.add_warning("Collateral Factor is above 90%", "liquidation")
            
            if li_fork == 0:
                self.add_error("Liquidation incentive is 0%", "liquidation")
            elif li_fork < 500:
                self.add_warning("Liquidation incentive is below 5%", "liquidation")
            elif li_fork > 2000:
                self.add_warning("Liquidation incentive is above 20%", "liquidation")
            
            # Check for self-liquidation vulnerability
            max_safe_li = (10000 - cf_fork) * 10000 // cf_fork
            liquidation_data["max_safe_liquidation_incentive"] = max_safe_li / 100
            liquidation_data["profitable_self_liquidation_possible"] = li_fork > max_safe_li
            
            if liquidation_data["profitable_self_liquidation_possible"]:
                self.add_error("Profitable Self-Liquidations are possible", "liquidation")
            
            self.results["liquidation"] = liquidation_data
        except Exception as e:
            self.results["liquidation"]["error"] = str(e)
            self.add_error(f"Failed to check liquidation parameters: {str(e)}", "liquidation")

    def get_coingecko_price(self, retry_counter=0):
        """Get the current price of a token from Coingecko API"""
        try:
            # Get API key from environment
            api_key = os.environ.get("COINGECKO_API_KEY")
            if not api_key:
                self.add_warning("COINGECKO_API_KEY environment variable is not set. Price comparison will be skipped.", "oracle")
                return None
                
            url = f"https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum?contract_addresses={self.collateral_address.lower()}&vs_currencies=usd"
            response = requests.get(url, headers={"x-cg-pro-api-key": api_key})
            
            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()
                if self.collateral_address.lower() in data:
                    return data[self.collateral_address.lower()]["usd"]
                else:
                    return None
            elif response.status_code == 429 and retry_counter <= 3:
                import time
                time.sleep(60)  # Wait and try again
                return self.get_coingecko_price(retry_counter=retry_counter+1)
            else:
                return None
        except Exception as e:
            self.add_warning(f"Error fetching Coingecko price: {str(e)}", "oracle")
            return None

    def get_active_borrowers(self):
        """Get all active borrowers with non-zero debt"""
        try:
            event_filter = self.market.events.Borrow.create_filter(
                from_block=0,
                to_block='latest'
            )
            borrow_events = event_filter.get_all_entries()
            historical_borrowers = {}
            for event in borrow_events:
                account = event.args.account
                if account not in historical_borrowers:
                    debt = self.market.functions.debts(account).call()
                    historical_borrowers[account] = debt
            active_borrowers = {k: v for k, v in historical_borrowers.items() if v != 0}
            return active_borrowers
        except Exception as e:
            self.add_error(f"Failed to get active borrowers: {str(e)}", "active_positions")
            return {}

    def check_active_position_changes(self):
        """Check how active positions are affected by the governance change"""
        active_borrowers = self.get_active_borrowers()
        borrowers_data = []
        
        if not active_borrowers:
            self.results["active_positions"]["borrowers"] = []
            return
            
        cf_fork = self.market_fork.functions.collateralFactorBps().call()
        
        for borrower, debt in active_borrowers.items():
            try:
                # Get state before proposal activation
                collateral_value = self.market.functions.getCollateralValue(borrower).call()
                credit_limit = self.market.functions.getCreditLimit(borrower).call()
                
                # Calculate LTV - handle division by zero
                if collateral_value == 0:
                    ltv = float('inf')  # Represent as infinity
                    ltv_percent = float('inf')
                else:
                    ltv = debt / collateral_value
                    ltv_percent = ltv * 100
                
                # Get state after proposal activation
                collateral_value_after = self.market_fork.functions.getCollateralValue(borrower).call()
                credit_limit_after = self.market_fork.functions.getCreditLimit(borrower).call()
                
                # Calculate LTV after - handle division by zero
                if collateral_value_after == 0:
                    ltv_after = float('inf')  # Represent as infinity
                    ltv_after_percent = float('inf')
                else:
                    ltv_after = debt / collateral_value_after
                    ltv_after_percent = ltv_after * 100
                
                # Only include accounts with changes
                if collateral_value != collateral_value_after or credit_limit != credit_limit_after:
                    borrower_data = {
                        "address": borrower,
                        "debt": debt / 10**18,
                        "collateral_value": {
                            "before": collateral_value / 10**18,
                            "after": collateral_value_after / 10**18,
                        },
                        "credit_limit": {
                            "before": credit_limit / 10**18,
                            "after": credit_limit_after / 10**18,
                        },
                        "loan_to_value": {
                            "before": ltv_percent,
                            "after": ltv_after_percent,
                        },
                        "liquidateable": (ltv_after == float('inf')) or (ltv_after > cf_fork / 10000)
                    }
                    
                    if borrower_data["liquidateable"]:
                        if ltv_after == float('inf'):
                            self.add_error(f"Account {borrower} has zero collateral value but positive debt", "active_positions")
                        else:
                            self.add_warning(f"Account {borrower} will be liquidateable after the change", "active_positions")
                    
                    borrowers_data.append(borrower_data)
            except Exception as e:
                self.add_error(f"Failed to check borrower {borrower}: {str(e)}", "active_positions")
        
        self.results["active_positions"]["borrowers"] = borrowers_data

# Create Flask app for API
app = Flask(__name__)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.json
    
    if not data or 'market_address' not in data or 'vnet_id' not in data:
        return jsonify({'error': 'Missing required parameters: market_address and vnet_id'}), 400
    
    try:
        market_address = Web3.to_checksum_address(data['market_address'])
        vnet_id = data['vnet_id']
        
        comparator = MarketComparator(market_address, vnet_id)
        results = comparator.analyze_market()
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# CLI interface for testing
if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='FiRM Market Comparator Tool')
    parser.add_argument('--serve', action='store_true', help='Run as API server')
    parser.add_argument('--dev', action='store_true', help='Run in development mode (Flask server)')
    parser.add_argument('--market', '-m', help='Market address to analyze')
    parser.add_argument('--vnet', '-v', help='Tenderly vnet ID')
    parser.add_argument('--port', '-p', type=int, default=int(os.environ.get("PORT", 5000)), 
                        help='Port to run the API server (default: 5000 or PORT env var)')
    
    args = parser.parse_args()
    
    # Check if we have the required dependencies
    try:
        from dotenv import load_dotenv
        # Already loaded at the top, but make sure it's available
    except ImportError:
        print("python-dotenv package is not installed. Install it with 'pip install python-dotenv'")
        print("This is required for loading the .env file with API keys.")
        sys.exit(1)
    
    if args.serve:
        # Run as API server
        port = args.port
        
        if args.dev:
            # Development mode using Flask's built-in server
            print(f"Starting development server on port {port}...")
            app.run(host='0.0.0.0', port=port)
        else:
            # Production mode using Waitress
            try:
                from waitress import serve
                print(f"Starting production server on port {port}...")
                serve(app, host='0.0.0.0', port=port)
            except ImportError:
                print("Waitress is not installed. Install it with 'pip install waitress' or run with --dev flag.")
                print("Falling back to development server...")
                app.run(host='0.0.0.0', port=port)
    else:
        # Run as CLI tool
        market_address = args.market or os.environ.get("MARKET_ADDRESS")
        vnet_id = args.vnet or os.environ.get("VNET_ID")
        
        if not market_address:
            print("Error: Market address is required. Provide it with --market or set MARKET_ADDRESS environment variable.")
            sys.exit(1)
        
        if not vnet_id:
            print("Error: Tenderly vnet ID is required. Provide it with --vnet or set VNET_ID environment variable.")
            sys.exit(1)
        
        try:
            market_address = Web3.to_checksum_address(market_address)
        except Exception as e:
            print(f"Error: Invalid Ethereum address format: {e}")
            sys.exit(1)
        
        # Check for required API keys
        if not os.environ.get("ALCHEMY_API_KEY"):
            print("Error: ALCHEMY_API_KEY is not set in environment or .env file.")
            print("Create a .env file or copy .env.example to .env and add your API keys.")
            sys.exit(1)
        
        print(f"Analyzing market {market_address} with Tenderly vnet {vnet_id}...")
        
        try:
            comparator = MarketComparator(market_address, vnet_id)
            results = comparator.analyze_market()
            print(json.dumps(results, indent=2))
        except ValueError as e:
            print(f"Error: {str(e)}")
            sys.exit(1)
