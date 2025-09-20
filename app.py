import os
import logging
import requests
import shutil
from flask import Flask, request
from urllib.parse import urljoin, urlparse

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

# --- Environment Variables ---
QB_HOST = os.environ.get('QB_HOST', 'localhost')
QB_PORT = os.environ.get('QB_PORT', '8080')
QB_USER = os.environ.get('QB_USER')
QB_PASS = os.environ.get('QB_PASS')
QB_CATEGORY_WATCH = os.environ.get('QB_CATEGORY_WATCH', 'race')
QB_CATEGORY_PROMOTE = os.environ.get('QB_CATEGORY_PROMOTE', 'longterm')
HDD_WATCHED_PATH = os.environ.get('HDD_WATCHED_PATH') # e.g., /data/downloads/tracker
HDD_CROSS_SEED_PATH = os.environ.get('HDD_CROSS_SEED_PATH') # e.g., /data/downloads/cross-seed

# Ensure required environment variables are set
if not all([QB_USER, QB_PASS, HDD_WATCHED_PATH, HDD_CROSS_SEED_PATH]):
    raise ValueError("Missing required environment variables: QB_USER, QB_PASS, HDD_WATCHED_PATH, and HDD_CROSS_SEED_PATH")

def get_tracker_name(tracker_url):
    """Extracts a clean folder name from the tracker's URL."""
    try:
        # Extracts the domain name (e.g., tracker.example.com)
        return urlparse(tracker_url).netloc
    except Exception:
        # Fallback for any parsing error
        return "unknown-tracker"

# --- qBittorrent Logic ---
def process_cross_seed_event(original_hash, new_hashes, trackers, torrent_name):
    """
    Physically moves the original torrent's content, creates hardlinks for new torrents,
    and updates qBittorrent with the new locations.
    """
    api_url = f"http://{QB_HOST}:{QB_PORT}/"
    
    with requests.Session() as s:
        try:
            # 1. Login to qBittorrent
            login_payload = {'username': QB_USER, 'password': QB_PASS}
            login_response = s.post(urljoin(api_url, "api/v2/auth/login"), data=login_payload)
            login_response.raise_for_status()
            if "Ok." not in login_response.text:
                logging.error("Failed to log in to qBittorrent.")
                return False
            logging.info("Successfully logged in to qBittorrent.")

            # 2. Get properties of the original torrent
            props_res = s.get(urljoin(api_url, f"/api/v2/torrents/properties?hash={original_hash}"))
            props_res.raise_for_status()
            original_props = props_res.json()
            original_content_path = os.path.join(original_props['save_path'], original_props['name'])
            is_directory = os.path.isdir(original_content_path)

            # 3. Physically move the original content
            final_content_path = os.path.join(HDD_WATCHED_PATH, original_props['name'])
            logging.info(f"Physically moving original content to '{final_content_path}'")
            os.makedirs(os.path.dirname(final_content_path), exist_ok=True) # Ensure parent directory exists
            os.rename(original_content_path, final_content_path)

            # 4. Update qBittorrent for the original torrent
            s.post(urljoin(api_url, "api/v2/torrents/setLocation"), data={'hashes': original_hash, 'location': HDD_WATCHED_PATH}).raise_for_status()
            logging.info(f"Updated location for original torrent '{torrent_name}' in qBittorrent.")

            # 5. Process all new cross-seed torrents
            for new_hash, new_tracker_url in zip(new_hashes, trackers):
                new_props_res = s.get(urljoin(api_url, f"/api/v2/torrents/properties?hash={new_hash}"))
                new_props_res.raise_for_status()
                new_props = new_props_res.json()
                
                # Path to the content created by cross-seed (to be removed)
                source_content_to_remove = os.path.join(new_props['save_path'], new_props['name'])
                
                # Create destination folder for hardlinks
                tracker_name = get_tracker_name(new_tracker_url)
                new_torrent_folder = os.path.join(HDD_CROSS_SEED_PATH, tracker_name)
                os.makedirs(new_torrent_folder, exist_ok=True)
                
                # The destination path for the hardlink will be inside the tracker-specific folder
                hardlink_destination_path = os.path.join(new_torrent_folder, new_props['name'])

                logging.info(f"Processing {'directory' if is_directory else 'file'}: '{new_props['name']}'")

                if is_directory:
                    # Create the directory structure and hardlink each file
                    os.makedirs(hardlink_destination_path, exist_ok=True)
                    for dirpath, _, filenames in os.walk(final_content_path):
                        relative_dir = os.path.relpath(dirpath, final_content_path)
                        destination_dir = os.path.join(hardlink_destination_path, relative_dir)
                        os.makedirs(destination_dir, exist_ok=True)
                        
                        for filename in filenames:
                            source_file = os.path.join(dirpath, filename)
                            destination_file = os.path.join(destination_dir, filename)
                            logging.info(f"Creating hardlink for '{filename}' at '{destination_file}'")
                            os.link(source_file, destination_file)
                    
                    # Remove the original cross-seed directory
                    logging.info(f"Removing original cross-seed directory '{source_content_to_remove}'")
                    if os.path.exists(source_content_to_remove):
                        shutil.rmtree(source_content_to_remove)
                else:
                    # It's a single file, create a hardlink
                    logging.info(f"Creating hardlink for '{new_props['name']}' at '{hardlink_destination_path}'")
                    os.link(final_content_path, hardlink_destination_path)

                    # Remove the original cross-seed file
                    logging.info(f"Removing original cross-seed file '{source_content_to_remove}'")
                    if os.path.exists(source_content_to_remove):
                        os.remove(source_content_to_remove)

                # Update qBittorrent with the new location
                s.post(urljoin(api_url, "api/v2/torrents/setLocation"), data={'hashes': new_hash, 'location': new_torrent_folder}).raise_for_status()
                logging.info(f"Updated location for new torrent '{new_props['name']}' in qBittorrent.")

            # 6. Change the category of the original torrent
            category_payload = {'hashes': original_hash, 'category': QB_CATEGORY_PROMOTE}
            s.post(urljoin(api_url, "api/v2/torrents/setCategory"), data=category_payload).raise_for_status()
            logging.info(f"Category for original torrent changed to '{QB_CATEGORY_PROMOTE}'.")
            
            return True

        except requests.exceptions.RequestException as e:
            logging.error(f"Error communicating with the qBittorrent API: {e}")
            return False
        except (OSError, IOError) as e:
            logging.error(f"File system error: {e}")
            return False

# --- Webhook Endpoint ---
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not request.is_json:
        return "Error: Content-Type must be application/json", 415

    data = request.get_json()
    logging.info("Webhook received.")

    try:
        result = data['extra'].get('result')
        searchee = data['extra']['searchee']
        
        original_hash = searchee.get('infoHash')
        current_category = searchee.get('category')
        torrent_name = searchee.get('name', 'Unknown Name')
        
        new_hashes = data['extra'].get('infoHashes')
        trackers = data['extra'].get('trackers')
        
        if not (new_hashes and trackers):
            return "Ignored: Missing 'infoHashes' or 'trackers'.", 200
            
    except (KeyError, TypeError, IndexError):
        logging.warning("Webhook received with invalid or incomplete JSON structure.")
        return "Error: Invalid JSON structure", 400

    if result == "INJECTED" and current_category == QB_CATEGORY_WATCH:
        logging.info(f"Torrent '{torrent_name}' was cross-seeded with {len(new_hashes)} matches and is in the watched category '{current_category}'. Initiating move.")
        success = process_cross_seed_event(original_hash, new_hashes, trackers, torrent_name)
        
        if success:
            return "Move and promote action for all torrents successful.", 200
        else:
            return "Move and promote action failed.", 500
    else:
        logging.info(f"Torrent '{torrent_name}' ignored (Result: {result}, Category: {current_category}).")
        return "Torrent not in a watched category or action not INJECTED, ignoring.", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9092)