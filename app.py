import os
import logging
import requests
from flask import Flask, request

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

# --- Environment Variables ---
# Fetch credentials from environment variables
QB_HOST = os.environ.get('QB_HOST', 'localhost')
QB_PORT = os.environ.get('QB_PORT', '8080')
QB_USER = os.environ.get('QB_USER')
QB_PASS = os.environ.get('QB_PASS')

# Fetch categories from environment variables, with default values
QB_CATEGORY_WATCH = os.environ.get('QB_CATEGORY_WATCH', 'race')
QB_CATEGORY_PROMOTE = os.environ.get('QB_CATEGORY_PROMOTE', 'longterm')


# Ensure required credentials are set
if not QB_USER or not QB_PASS:
    raise ValueError("Missing required environment variables: QB_USER and QB_PASS")

# --- qBittorrent Logic ---
def promote_torrent(info_hash):
    """
    Connects to the qBittorrent API to change a torrent's category.
    
    Args:
        info_hash (str): The info hash of the torrent to modify.
        
    Returns:
        bool: True if the category was changed successfully, False otherwise.
    """
    api_url = f"http://{QB_HOST}:{QB_PORT}"
    
    with requests.Session() as s:
        try:
            # Login to qBittorrent
            login_payload = {'username': QB_USER, 'password': QB_PASS}
            login_response = s.post(f"{api_url}/api/v2/auth/login", data=login_payload)
            login_response.raise_for_status()
            
            if "Ok." not in login_response.text:
                logging.error("Failed to log in to qBittorrent, unexpected response.")
                return False

            logging.info("Successfully logged in to qBittorrent.")
            
            # Set the new category for the torrent
            set_category_payload = {'hashes': info_hash, 'category': QB_CATEGORY_PROMOTE}
            set_cat_response = s.post(f"{api_url}/api/v2/torrents/setCategory", data=set_category_payload)
            set_cat_response.raise_for_status()
            
            logging.info(f"Category change to '{QB_CATEGORY_PROMOTE}' requested for torrent {info_hash}")
            return True

        except requests.exceptions.RequestException as e:
            logging.error(f"Error communicating with the qBittorrent API: {e}")
            return False

# --- Webhook Endpoint ---
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """
    Handles incoming webhooks from cross-seed.
    """
    if not request.is_json:
        logging.warning("Received a non-JSON request.")
        return "Error: Content-Type must be application/json", 415

    data = request.get_json()
    logging.info("Webhook received.")

    try:
        # Extract torrent info from the webhook payload
        searchee = data['extra']['searchee']
        info_hash = searchee.get('infoHash')
        current_category = searchee.get('category')
        torrent_name = searchee.get('name', 'Unknown') # Récupère le nom, avec une valeur par défaut
    except (KeyError, TypeError):
        logging.warning("Webhook received with invalid or incomplete JSON structure.")
        return "Error: Invalid JSON structure", 400

    if not info_hash:
        logging.warning("Missing 'infoHash' in webhook payload.")
        return "Error: 'infoHash' is required", 400

    # --- Filtering Logic ---
    # Check if the torrent's category matches the one to watch
    if current_category == QB_CATEGORY_WATCH:
        logging.info(f"Torrent '{torrent_name}' ({info_hash}) is in the watched category ('{current_category}'). Attempting to promote.")
        success = promote_torrent(info_hash)
        
        if success:
            return "Promotion action successful.", 200
        else:
            return "Promotion action failed.", 500
    else:
        logging.info(f"Torrent '{torrent_name}' ({info_hash}) in category '{current_category}' is not watched. Action ignored.")
        return "Torrent not in a watched category, action ignored.", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9092)