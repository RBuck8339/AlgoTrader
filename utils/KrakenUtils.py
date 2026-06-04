import requests
import hashlib
import base64
import hmac
import time

class KrakenUtils:
    @staticmethod
    def get_kraken_signature(url_path, data, secret):
        # For actually interacting with Kraken API, this is necessary
        postdata = requests.compat.urlencode(data)  # Standardized to web-link text format
        encoded = (str(data['nonce']) + postdata).encode()  # Add timestamp to front
        message_hash = hashlib.sha256(encoded).digest()  # SHA256 hash of the above
        message = url_path.encode() + message_hash
        mac_key = base64.b64decode(secret)
        mac = hmac.new(mac_key, message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()
    