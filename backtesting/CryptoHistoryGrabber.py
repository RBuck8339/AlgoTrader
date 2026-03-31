# Taken from: https://volatility.red/Crypto_tick_and_bar_data thanks to r/algotrading wiki

import urllib.request
import urllib.parse
import urllib.error
import json
import csv
import dotenv
import hmac
import hashlib
import base64
import time
import os
from datetime import datetime, timedelta

# USER CONFIGURATION - Modify these variables as needed
SYMBOL = "XBTUSD"  # Trading pair (e.g., XBTUSD, ETHUSD, ADAUSD)
DATA_TYPE = "trades"  # Options: "trades", "ohlc", "spread"

# Load environment variables from .env file
dotenv.load_dotenv()

# Set API keys from environment variables
API_KEY = os.getenv("DATA_API_KEY")
API_SECRET = os.getenv("DATA_API_SECRET")

#Not used for "trades" type data
INTERVAL = 1  # For OHLC data: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600 (minutes)

DAYS = 10 # Pull data from X days back until now.
SINCE = int((datetime.now() - timedelta(days=DAYS)).timestamp())  # Unix timestamp or None for all available data
SLEEP_DELAY = 0.01  # Delay between API requests in seconds
RATE_LIMIT_WAIT = 5  # Base wait time (in seconds) for rate limit errors (exponential backoff multiplier)
BATCH_SIZE = 5000  # Number of records to request per API call

OUTPUT_FILE = "backtesting/data/crypto/kraken_{}_{}_data_{}_to_{}.csv"  # Output filename


# Kraken API endpoints
BASE_URL = "https://api.kraken.com/0/public/"
PRIVATE_URL = "https://api.kraken.com/0/private/"

def get_auth_headers(uri_path, query_params):
    """Generate authentication headers for Kraken API"""
    if not API_KEY or not API_SECRET:
        return {}, ""
    
    try:
        nonce = str(int(time.time() * 1000))  # Use milliseconds for nonce
        
        # Separate query string (API params) from body (nonce only)
        query_str = urllib.parse.urlencode(query_params) if query_params else ""
        body = {"nonce": nonce}
        body_str = json.dumps(body)
        
        # Kraken's signature method: path + SHA256(nonce + query_str + body_str)
        combined_data = nonce + query_str + body_str
        sha256_hash = hashlib.sha256(combined_data.encode()).digest()
        message = uri_path.encode() + sha256_hash
        signature = hmac.new(base64.b64decode(API_SECRET), message, hashlib.sha512)
        
        headers = {
            'API-Key': API_KEY,
            'API-Sign': base64.b64encode(signature.digest()).decode(),
            'Content-Type': 'application/json'
        }
        return headers, body_str
        
    except Exception as e:
        print(f"Auth headers: Error generating signature - {e}")
        import traceback
        traceback.print_exc()
        return {}, ""

def make_request(url, params, use_auth=False, max_retries=3):
    """Make API request with optional authentication and retry logic"""
    for attempt in range(max_retries):
        try:
            # Build URL with query parameters
            query_str = urllib.parse.urlencode(params) if params else ""
            full_url = f"{url}?{query_str}" if query_str else url
            
            headers = {}
            body_data = None
            if use_auth and API_KEY and API_SECRET:
                uri_path = url.replace('https://api.kraken.com', '')
                headers, body_str = get_auth_headers(uri_path, params)
                body_data = body_str.encode() if body_str else None
                if headers and attempt == 0:
                    print(f"AUTH: Using authenticated GET request to {uri_path}")
            else:
                if attempt == 0:
                    print("AUTH: Using public GET request (no authentication)")
            
            req = urllib.request.Request(full_url, data=body_data, headers=headers)
            response = urllib.request.urlopen(req)
            
            response_text = response.read().decode()
            data = json.loads(response_text)
            
        except urllib.error.HTTPError as e:
            print(f"HTTP Error {e.code}: {e.read().decode()}")
            return {'error': [f'HTTP {e.code} error']}
        except Exception as e:
            print(f"DEBUG: Failed to parse JSON or make request: {e}")
            return {'error': ['Failed to parse response']}
        
        # Debug: Check response for auth issues
        if 'error' in data and data['error']:
            if any('invalid' in str(err).lower() or 'auth' in str(err).lower() for err in data['error']):
                print(f"AUTH ERROR: {data['error']} - Check API credentials")
        
        # Check for rate limit error
        if 'error' in data and any('too many requests' in str(err).lower() for err in data['error']):
            wait_time = (2 ** attempt) * RATE_LIMIT_WAIT  # Exponential backoff
            print(f"RATE LIMIT: Hit limit (attempt {attempt + 1}), waiting {wait_time} seconds...")
            time.sleep(wait_time)
            continue
        
        return data
    
    return data  # Return last response if all retries failed

def get_historical_trades(pair, filename, since=None):
    """Get all historical trade data with pagination and write directly to CSV"""
    url = f"{BASE_URL}Trades"
    current_since = since
    total_records = 0
    first_batch = True
    
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['timestamp', 'price', 'volume', 'buy_sell', 'market_limit', 'misc'])
        
        while True:
            params = {"pair": pair, "count": BATCH_SIZE}
            if current_since:
                params["since"] = current_since
            
            data = make_request(url, params, use_auth=True)
            if 'error' in data and data['error']:
                return {'error': data['error']}
            
            batch_count = 0
            for pair_key in data['result']:
                if pair_key != 'last':
                    trades = data['result'][pair_key]
                    batch_count = len(trades)
                    for trade in trades:
                        writer.writerow([
                            datetime.fromtimestamp(float(trade[2])),
                            trade[0], trade[1], trade[3], trade[4], trade[5]
                        ])
                    total_records += batch_count
            
            if 'last' in data['result'] and batch_count == BATCH_SIZE:
                print(f"Fetched {total_records} records...")
                current_since = data['result']['last']
                time.sleep(SLEEP_DELAY)
            else:
                break
    
    return {'total_records': total_records}

def get_historical_ohlc(pair, filename, interval=1, since=None):
    """Get all historical OHLC data with pagination and write directly to CSV"""
    url = f"{BASE_URL}OHLC"
    current_since = since
    total_records = 0
    
    with open(filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
        
        while True:
            params = {"pair": pair, "interval": interval}
            if current_since:
                params["since"] = current_since
            
            data = make_request(url, params, use_auth=True)
            if 'error' in data and data['error']:
                return {'error': data['error']}
            
            batch_count = 0
            for pair_key in data['result']:
                if pair_key != 'last':
                    ohlc_data = data['result'][pair_key]
                    batch_count = len(ohlc_data)
                    for candle in ohlc_data:
                        writer.writerow([
                            datetime.fromtimestamp(float(candle[0])),
                            candle[1], candle[2], candle[3], candle[4], candle[5], candle[6], candle[7]
                        ])
                    total_records += batch_count
            
            if 'last' in data['result'] and batch_count == 720:
                print(f"Fetched {total_records} records...")
                current_since = data['result']['last']
                time.sleep(SLEEP_DELAY)
            else:
                break
    
    return {'total_records': total_records}





# Dispatch table for data type handlers
DATA_HANDLERS = {
    "trades": lambda symbol, filename, since: get_historical_trades(symbol, filename, since),
    "ohlc": lambda symbol, filename, since: get_historical_ohlc(symbol, filename, INTERVAL, since)
}

def test_authentication():
    """Test if authentication is working by calling a private endpoint"""
    url = f"{PRIVATE_URL}OpenOrders"
    params = {}
    print(f"DEBUG: Testing auth with URL: {url}")
    data = make_request(url, params, use_auth=True)
    
    print(f"DEBUG: Full response: {data}")
    
    if 'error' in data and data['error']:
        # Check if it's a permission error vs auth error
        if any('permission' in str(err).lower() for err in data['error']):
            print("AUTH TEST PASSED: Authentication working but insufficient permissions")
            return True
        else:
            print(f"AUTH TEST FAILED: {data['error']}")
            return False
    else:
        print("AUTH TEST PASSED: Authentication is working")
        return True

def main():
    # Check for required authentication
    if not API_KEY or not API_SECRET:
        print("ERROR: API_KEY and API_SECRET are required for data collection.")
        print("Please set your Kraken API credentials in the script configuration.")
        print("Register a free account at https://geni.us/GoKraken to get API access.")
        exit(1)
    
    print(f"Downloading {DATA_TYPE} data for {SYMBOL}...")
    print(f"Fetching data from {datetime.fromtimestamp(SINCE)} to now...")
    print("Using authenticated requests for optimal performance")
    
    try:
        start_date = datetime.fromtimestamp(SINCE).strftime('%Y%m%d')
        end_date = datetime.now().strftime('%Y%m%d')
        filename = OUTPUT_FILE.format(SYMBOL, DATA_TYPE, start_date, end_date)
        directory = os.path.dirname(filename)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"Created directory: {directory}")

        if os.path.exists(filename):
            os.remove(filename)
            print(f"Removed existing file: {filename}")
        
        handler = DATA_HANDLERS.get(DATA_TYPE)
        if not handler:
            print(f"Invalid DATA_TYPE '{DATA_TYPE}'. Use: {', '.join(DATA_HANDLERS.keys())}")
            exit(1)
        
        result = handler(SYMBOL, filename, SINCE)
        
        if 'error' in result:
            print(f"API Error: {result['error']}")
            exit(1)
        else:
            print(f"Data saved to {filename} ({result['total_records']} records)")
            
    except Exception as e:
        print(f"Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()