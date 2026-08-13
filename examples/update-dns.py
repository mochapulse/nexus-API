import orjson
import logging
import time
import urllib.request

# Configuration
DOMAIN = ""
TOKEN = ""
INTERVAL_HOURS = 5

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def get_public_ip():
    """Fetches the current public IP address using api.myip.com, falling back to ifconfig.me."""
    
    # 1. Try Primary API: api.myip.com (JSON response)
    try:
        req = urllib.request.Request(
            "https://api.myip.com", 
            headers={'User-Agent': 'curl/7.68.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = orjson.loads(resp.read().decode('utf-8'))
            ip = data.get("ip", "").strip()
            if ip:
                logging.info(f"IP retrieved from api.myip.com: {ip}")
                return ip
    except Exception as e:
        logging.warning(f"api.myip.com failed ({e}), trying fallback...")

    # 2. Try Fallback API: ifconfig.me (Plain text response)
    try:
        req = urllib.request.Request(
            "https://ifconfig.me/ip", 
            headers={'User-Agent': 'curl/7.68.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ip = resp.read().decode('utf-8').strip()
            if ip:
                logging.info(f"IP retrieved from ifconfig.me: {ip}")
                return ip
    except Exception as e:
        logging.warning(f"ifconfig.me failed ({e})")

    logging.error("Failed to retrieve public IP from both services.")
    return None

def update_duckdns():
    """Fetches public IP and updates DuckDNS."""
    ip = get_public_ip()
    
    # Append the fetched IP explicitly; if IP fetch failed, pass empty string as fallback
    ip_param = ip if ip else ""
    url = f"https://www.duckdns.org/update?domains={DOMAIN}&token={TOKEN}&ip={ip_param}"
    
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'DuckDNS-Python-Client'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = response.read().decode('utf-8').strip()
            if result == "OK":
                logging.info(f"DuckDNS update SUCCESS. Domain updated to IP: {ip_param or 'auto-detected'}")
            else:
                logging.warning(f"DuckDNS update FAILED. Response: '{result}'")
    except Exception as e:
        logging.error(f"Error contacting DuckDNS: {e}")

if __name__ == "__main__":
    logging.info("DuckDNS IP updater service started.")
    while True:
        update_duckdns()
        # Sleep for 5 hours
        time.sleep(INTERVAL_HOURS * 3600)