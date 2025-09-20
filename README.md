# cross-seed-mover

`cross-seed-mover` is a webhook service that seamlessly integrates with [cross-seed](https://www.cross-seed.org/) to automate advanced file management in qBittorrent. It intelligently moves torrents after a successful cross-seed, organizing both the original and newly seeded files into separate, structured locations.

## Purpose

This service is designed for users who want precise control over where their files are stored after being processed by `cross-seed`. It's especially useful for separating original downloads from files generated for cross-seeding, and for organizing cross-seeded content by tracker.

### The Problem

When `cross-seed` injects a new torrent, both the original and the new torrent often remain in the same download directory. This can lead to several challenges:
-   **Disorganized Files:** It's hard to distinguish between original files and those created specifically for cross-seeding.
-   **Manual Sorting:** You have to manually move files to their final destinations (e.g., a media library for the original, a dedicated seed folder for the new one).
-   **Filesystem Constraints:** If you download to a temporary location (like an SSD) and your final library is on a different filesystem (like an HDD array), `cross-seed` might fail to create hardlinks.

### The Solution

`cross-seed-mover` provides a fully automated, two-part solution triggered by a `cross-seed` webhook:

1.  **Listens for Success:** The service waits for a successful injection notification from `cross-seed` for any torrent in a designated "watch" category.
2.  **Moves the Original Torrent:** It relocates the original torrent's files to your primary media library or long-term storage path (`HDD_WATCHED_PATH`).
3.  **Moves the New Torrent:** It moves the newly injected cross-seed torrent to a separate location (`HDD_CROSS_SEED_PATH`), automatically creating a subfolder named after the torrent's tracker (e.g., `/data/cross-seed/private.tracker.org/`).
4.  **Promotes the Original:** Finally, it changes the category of the original torrent to a "promote" category, signaling that it has been processed and is ready for long-term seeding or archival.

## Usage

This service is intended to be run as a Docker container.

### Docker Compose

Here is an example `docker-compose.yml`:

```yaml
version: '3.8'

services:
  cross-seed-mover:
    image: ghcr.io/kheopsian/cross-seed-mover:latest
    container_name: cross-seed-mover
    restart: unless-stopped
    ports:
      - "9092:9092"
    volumes:
      # Mount your qBittorrent download path, where cross-seed also operates
      - /path/to/your/downloads:/path/to/your/downloads
      # Mount your final media library path
      - /path/to/your/library:/path/to/your/library
      # Mount the base path for cross-seed torrents
      - /path/to/your/cross-seed-storage:/path/to/your/cross-seed-storage
    environment:
      - QB_HOST=your_qbittorrent_host
      - QB_PORT=8080
      - QB_USER=your_qbittorrent_username
      - QB_PASS=your_qbittorrent_password
      - QB_CATEGORY_WATCH=race
      - QB_CATEGORY_PROMOTE=longterm
      # IMPORTANT: These paths must match the container-side paths from your volumes
      - HDD_WATCHED_PATH=/path/to/your/library
      - HDD_CROSS_SEED_PATH=/path/to/your/cross-seed-storage
```

## Configuration

The service is configured entirely through environment variables:

| Variable | Description | Default | Required |
| :--- | :--- | :--- | :--- |
| `QB_HOST` | The hostname or IP address of your qBittorrent instance. | `localhost` | No |
| `QB_PORT` | The port for the qBittorrent Web UI. | `8080` | No |
| `QB_USER` | Your qBittorrent username. | **None** | **Yes** |
| `QB_PASS` | Your qBittorrent password. | **None** | **Yes** |
| `QB_CATEGORY_WATCH` | The source category that this service will monitor. | `race` | No |
| `QB_CATEGORY_PROMOTE` | The destination category assigned to the original torrent after moving. | `longterm` | No |
| `HDD_WATCHED_PATH` | The absolute path **inside the container** to move the original torrent to. | **None** | **Yes** |
| `HDD_CROSS_SEED_PATH` | The absolute path **inside the container** where new cross-seeded torrents will be stored. | **None** | **Yes** |

### Important Note on Volumes

For the script to create hardlinks, the Docker container needs direct access to the filesystems. You **must** mount the relevant host paths as volumes.

-   The path where qBittorrent saves initial downloads.
-   The path for your final media library (`HDD_WATCHED_PATH`).
-   The path for your cross-seed storage (`HDD_CROSS_SEED_PATH`).

All these locations must reside on the **same filesystem** for hardlinks to work. The `environment` variables for paths must match the paths you define on the right side of the volume mappings (the container's perspective).

## Webhook Configuration

In your cross-seed `config.js` file, you need to configure the `notificationWebhookUrls` to point to this service.

Example cross-seed configuration:

```js
// config.js
module.exports = {
  notificationWebhookUrls: "http://localhost:9092/webhook",
};
```

When `cross-seed` successfully injects a new torrent, it will send a POST request to this service. If the original torrent's category matches `QB_CATEGORY_WATCH`, the service will perform the move operations as described above.
