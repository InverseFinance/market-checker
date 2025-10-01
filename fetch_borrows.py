import os, time, requests
from web3 import Web3
from dotenv import load_dotenv


load_dotenv()
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
CHAIN_ID = 1  # 1=Ethereum, 10=Optimism, 137=Polygon, 42161=Arbitrum, 8453=Base, etc.
CONTRACT_ADDRESS = "0x3Ac5CEbC7A417DB619B85660E4f284f5643DFd5e"  # example: USDC

# Set the exact Solidity event signature you want to fetch.
EVENT_SIGNATURE = "Borrow(address,uint256)"

BASE_URL = "https://api.etherscan.io/v2/api"
PAGE_SIZE = 1000          # v2 max per page
RPS_SLEEP = 0.25          # be polite to free tier (≈5 req/s)

def _get(url, params):
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def compute_topic0(sig: str) -> str:
    """
    Computes Keccak-256 hash of the event signature string.
    Tries eth_utils first, then web3. Install either 'eth-utils' or 'web3'.
    """
    try:
        from eth_utils import keccak
        return "0x" + keccak(text=sig).hex()
    except Exception:
        try:
            from web3 import Web3
            return Web3.keccak(text=sig).hex()
        except Exception as e:
            raise SystemExit(
                "Need either 'eth-utils' or 'web3' installed to compute topic0.\n"
                "pip install eth-utils  (or)  pip install web3"
            ) from e

def get_creation_block(address: str) -> int:
    params = {
        "chainid": CHAIN_ID,
        "module": "contract",
        "action": "getcontractcreation",
        "contractaddresses": address,
        "apikey": ETHERSCAN_API_KEY,
    }
    data = _get(BASE_URL, params)
    if data.get("status") != "1" or not data.get("result"):
        raise RuntimeError(f"Creation lookup failed: {data}")
    return int(data["result"][0]["blockNumber"])  # decimal string

def get_latest_block() -> int:
    params = {
        "chainid": CHAIN_ID,
        "module": "proxy",
        "action": "eth_blockNumber",
        "apikey": ETHERSCAN_API_KEY,
    }
    data = _get(BASE_URL, params)
    head_hex = data.get("result")
    if not head_hex:
        raise RuntimeError(f"eth_blockNumber failed: {data}")
    return int(head_hex, 16)

def fetch_logs_by_signature(address: str, from_block: int, to_block: int, topic0_hex: str):
    logs = []
    page = 1
    while True:
        params = {
            "chainid": CHAIN_ID,
            "module": "logs",
            "action": "getLogs",
            "address": address,
            "fromBlock": from_block,
            "toBlock": to_block,
            "topic0": topic0_hex,   # <<< limit to this event signature
            "page": page,
            "offset": PAGE_SIZE,
            "apikey": ETHERSCAN_API_KEY,
        }
        data = _get(BASE_URL, params)
        result = data.get("result", [])
        if not result:
            break
        logs.extend(result)
        print(f"Page {page}: {len(result)} logs")
        time.sleep(RPS_SLEEP)
        if len(result) < PAGE_SIZE:
            break
        page += 1
    return logs


def decode_borrow(log):
    """
    Decodes: event Borrow(address indexed borrower, uint256 amount)
    - borrower  -> topics[1] (last 20 bytes)
    - amount    -> data[0] (first 32-byte word)
    Returns (borrower_checksum, amount_int)
    """
    topics = log["topics"]
    if len(topics) < 2:
        raise ValueError("Missing indexed borrower in topics[1].")

    # Indexed address is right-aligned in a 32-byte topic → take last 20 bytes
    borrower = "0x" + topics[1][-40:]
    borrower = Web3.to_checksum_address(borrower)

    data = log.get("data") or "0x"
    if not data.startswith("0x") or len(data) < 2 + 64:
        raise ValueError("Missing non-indexed uint256 in data (need 32 bytes).")

    # First 32-byte word (amount)
    amount = int(data[2:66], 16)

    return borrower, amount

def fetch_borrows(contract: str):
    if "YOUR_ETHERSCAN_KEY" in ETHERSCAN_API_KEY:
        raise SystemExit("Set ETHERSCAN_API_KEY to your real key.")

    topic0 = compute_topic0(EVENT_SIGNATURE)
    print(f"topic0 for '{EVENT_SIGNATURE}': {topic0}")

    print(f"Resolving creation block for {CONTRACT_ADDRESS} on chainId={CHAIN_ID}...")
    creation_block = get_creation_block(contract)
    latest_block = get_latest_block()
    print(f"Creation block: {creation_block}, latest: {latest_block}")

    logs = fetch_logs_by_signature(contract, creation_block, latest_block, topic0)
    print(f"\nTotal logs fetched: {len(logs)}")
    # Peek a few results
    return [decode_borrow(l) for l in logs]

def main():
    print(fetch_borrows(CONTRACT_ADDRESS))

if __name__ == "__main__":
    main()

