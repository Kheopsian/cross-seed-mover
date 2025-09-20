import os
import logging
import requests
import shutil
from flask import Flask, request
from urllib.parse import urljoin

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

# --- qBittorrent Logic ---
def process_cross_seed_event(original_hash, new_hashes):
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

            # 2. Get properties of the original torrent to get its real name and path
            props_res = s.get(urljoin(api_url, f"/api/v2/torrents/properties?hash={original_hash}"))
            props_res.raise_for_status()
            original_props = props_res.json()
            torrent_name = original_props.get('name', 'Unknown Name') # More reliable way to get the name
            original_content_path = os.path.join(original_props['save_path'], original_props['name'])
            
            logging.info(f"Processing torrent: '{torrent_name}'")

            # 3. Physically move the original content
            final_content_path = os.path.join(HDD_WATCHED_PATH, original_props['name'])
            logging.info(f"Physically moving original content from '{original_content_path}' to '{final_content_path}'")
            os.makedirs(os.path.dirname(final_content_path), exist_ok=True)
            shutil.move(original_content_path, final_content_path)
            
            # Check if the moved content is a directory or a single file
            is_content_directory = os.path.isdir(final_content_path)
            logging.info(f"Content is a {'directory' if is_content_directory else 'file'}.")

            # 4. Update qBittorrent for the original torrent
            s.post(urljoin(api_url, "api/v2/torrents/setLocation"), data={'hashes': original_hash, 'location': HDD_WATCHED_PATH}).raise_for_status()
            logging.info(f"Updated location for original torrent '{torrent_name}' in qBittorrent.")

            # 5. Process all new cross-seed torrents
            for new_hash in new_hashes:
                new_props_res = s.get(urljoin(api_url, f"/api/v2/torrents/properties?hash={new_hash}"))
                new_props_res.raise_for_status()
                new_props = new_props_res.json()
                
                # Path to the temporary content created by cross-seed (to be removed)
                source_content_to_remove = os.path.join(new_props['save_path'], new_props['name'])
                
                # FIX: Derive tracker name from the source save_path for 1:1 structure
                tracker_folder_name = os.path.basename(new_props['save_path'])
                new_torrent_folder = os.path.join(HDD_CROSS_SEED_PATH, tracker_folder_name)
                os.makedirs(new_torrent_folder, exist_ok=True)
                
                hardlink_destination_path = os.path.join(new_torrent_folder, new_props['name'])

                # FIX: Linking logic based on whether the final content is a file or directory
                if is_content_directory:
                    logging.info(f"Creating hardlink directory for '{new_props['name']}' at '{hardlink_destination_path}'")
                    os.makedirs(hardlink_destination_path, exist_ok=True)
                    for dirpath, _, filenames in os.walk(final_content_path):
                        relative_dir = os.path.relpath(dirpath, final_content_path)
                        destination_dir = os.path.join(hardlink_destination_path, relative_dir)
                        os.makedirs(destination_dir, exist_ok=True)
                        
                        for filename in filenames:
                            source_file = os.path.join(dirpath, filename)
                            destination_file = os.path.join(destination_dir, filename)
                            if not os.path.exists(destination_file):
                                os.link(source_file, destination_file)
                else:
                    logging.info(f"Creating hardlink file for '{new_props['name']}' at '{hardlink_destination_path}'")
                    if not os.path.exists(hardlink_destination_path):
                        os.link(final_content_path, hardlink_destination_path)

                # FIX: Robustly remove the source content, checking if it's a file or directory
                if os.path.isdir(source_content_to_remove):
                    logging.info(f"Removing original cross-seed directory '{source_content_to_remove}'")
                    shutil.rmtree(source_content_to_remove)
                elif os.path.isfile(source_content_to_remove):
                    logging.info(f"Removing original cross-seed file '{source_content_to_remove}'")
                    os.remove(source_content_to_remove)
                else:
                    logging.warning(f"Could not find source content to remove at '{source_content_to_remove}'")


                # Update qBittorrent with the new location for the cross-seeded torrent
                s.post(urljoin(api_url, "api/v2/torrents/setLocation"), data={'hashes': new_hash, 'location': new_torrent_folder}).raise_for_status()
                logging.info(f"Updated location for new torrent '{new_props['name']}' in qBittorrent.")

            # 6. Change the category of the original torrent
            category_payload = {'hashes': original_hash, 'category': QB_CATEGORY_PROMOTE}
            s.post(urljoin(api_url, "api/v2/torrents/setCategory"), data=category_payload).raise_for_status()
            logging.info(f"Category for original torrent '{torrent_name}' changed to '{QB_CATEGORY_PROMOTE}'.")
            
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
        torrent_name = searchee.get('name', 'Unknown Name') # Used only for initial log
        
        new_hashes = data['extra'].get('infoHashes')
        
        if not new_hashes:
            return "Ignored: Missing 'infoHashes'.", 200
            
    except (KeyError, TypeError, IndexError):
        logging.warning("Webhook received with invalid or incomplete JSON structure.")
        return "Error: Invalid JSON structure", 400

    if result == "INJECTED" and current_category == QB_CATEGORY_WATCH:
        logging.info(f"Torrent '{torrent_name}' was cross-seeded with {len(new_hashes)} matches and is in the watched category '{current_category}'. Initiating move.")
        success = process_cross_seed_event(original_hash, new_hashes)
        
        if success:
            return "Move and promote action for all torrents successful.", 200
        else:
            return "Move and promote action failed.", 500
    else:
        logging.info(f"Torrent '{torrent_name}' ignored (Result: {result}, Category: {current_category}).")
        return "Torrent not in a watched category or action not INJECTED, ignoring.", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9092)

