# cross-seed-mover

`cross-seed-mover` is a simple webhook service designed to integrate with [cross-seed](https://www.cross-seed.org/). It listens for notifications and automatically changes the category of torrents in qBittorrent, allowing for better post-processing automation.

## Purpose

This service automates file management to solve a common problem for `cross-seed` users who download to an SSD but store their media library on a separate HDD array.

### The Problem

1.  You download a new torrent, and it saves to a "fast" drive (e.g., an SSD) for quick access.
2.  `cross-seed` runs, finds a match on another tracker, and attempts to inject a new torrent for cross-seeding.
3.  To avoid data duplication, `cross-seed` tries to create a **hardlink**. However, if your media library (the destination for the new torrent) is on a different filesystem (e.g., an HDD array), the hardlink creation **fails**.
4.  `cross-seed` sends a notification via webhook after finding the match.

### The Solution

`cross-seed-mover` acts as the bridge to resolve this failure:

1.  The service listens for the webhook from `cross-seed`.
2.  Upon receiving a notification for a torrent in the "watch" category (the one on your SSD), it connects to qBittorrent.
3.  It changes the torrent's category to your "promote" category.
4.  In qBittorrent, you must configure this "promote" category to save files to your HDD array. This category change triggers qBittorrent to **physically move the files** from the SSD to the array.
5.  On the next run, `cross-seed` will be able to successfully inject the torrent because the source files are now on the same filesystem as your media library, allowing the hardlink to be created.

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
    environment:
      - QB_HOST=your_qbittorrent_host
      - QB_PORT=8080
      - QB_USER=your_qbittorrent_username
      - QB_PASS=your_qbittorrent_password
      - QB_CATEGORY_WATCH=race
      - QB_CATEGORY_PROMOTE=longterm
```

## Configuration

The service is configured entirely through environment variables:

| Variable            | Description                                                                 | Default     |
| ------------------- | --------------------------------------------------------------------------- | ----------- |
| `QB_HOST`           | The hostname or IP address of your qBittorrent instance.                    | `localhost` |
| `QB_PORT`           | The port for the qBittorrent Web UI.                                        | `8080`      |
| `QB_USER`           | Your qBittorrent username.                                                  | **None**    |
| `QB_PASS`           | Your qBittorrent password.                                                  | **None**    |
| `QB_CATEGORY_WATCH` | The "source" category that this service will monitor.                       | `race`      |
| `QB_CATEGORY_PROMOTE` | The "destination" category where torrents will be moved.                    | `longterm`  |

**Note:** `QB_USER` and `QB_PASS` are required.

## Webhook Configuration

In your cross-seed `config.js` file, you need to configure the `notificationWebhookUrls` to point to this service.

Example cross-seed configuration:

```js
// config.js
module.exports = {
  notificationWebhookUrls: "http://localhost:9092/webhook",
};
```

When a torrent is snatched, cross-seed will send a POST request to the webhook endpoint. `cross-seed-mover` will then check if the torrent's category matches `QB_CATEGORY_WATCH`. If it does, it will change the torrent's category to `QB_CATEGORY_PROMOTE` in qBittorrent.
