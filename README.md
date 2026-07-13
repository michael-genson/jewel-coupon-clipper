# Jewel Coupon Clipper

Automated coupon clipper for Jewel-Osco. Logs in to jewelosco.com, fetches all available
digital offers for one or more stores, and clips everything that isn't already clipped.
Supports multiple accounts in a single run.

## Configuration

Configuration is split into two files, both loaded from the project root by default:

- **`.env`** — app-level settings (not per-user)
- **`users.yaml`** — one entry per Jewel account to run the clipper for

### `.env`

Copy `.env.example` to `.env` and adjust as needed:

```env
LOG_LEVEL=INFO
USERS_FILE=
```

| Variable     | Description                                                               | Default        |
| ------------ | ------------------------------------------------------------------------- | -------------- |
| `LOG_LEVEL`  | Standard Python logging level (`DEBUG`, `INFO`, `WARNING`, ...)           | `INFO`         |
| `USERS_FILE` | Path to the users YAML file                                               | `users.yaml`   |

### `users.yaml`

```yaml
users:
  - id: "" # phone number or email used to sign in to jewelosco.com
    password: ""
    device_token: "" # see "Device token" below
    store_ids: [""] # one or more store IDs to clip offers for
```
#### ID

Jewel accepts both your phone number and your email as your login id.
If you're having trouble getting authentication to work, try using your other id (e.g. if email isn't working, try phone number).

#### Device token

Logging in with a brand-new device token will most likely trigger an MFA challenge, which
this tool does not handle. To avoid that, use a device token from a device/browser that has
already completed MFA for the account (e.g. capture it from a browser session that's already
past MFA), so subsequent logins are treated as trusted.

To find your device token:

1. Go to https://www.jewelosco.com
2. Open your browser's dev tools and go to the "Network" tab
3. Log out (if logged in) and clear the network log (the "clear" icon: ⊘ in Chrome, 🗑 in Firefox)
4. Log in, then find the `authn` request and check its request body for `context.deviceToken`

Note that if you're adding configs to multiple accounts, and you log-in with them on the same device,
you will find that the device token is the same (since it's generated per-device). This is fine, Jewel's API doesn't care.

## Running locally

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14+.

```sh
uv sync
uv run playwright install chromium
uv run python handler.py
```

## Running with Docker

```sh
docker compose run --rm jewel-clipper
```

This builds the image locally (if needed), runs the clipper once to completion, and
removes the container afterward - nothing is left running between invocations.

### Using the published image

A pre-built image is also available, if you'd rather not build locally:

```yaml
services:
  jewel-clipper:
    image: ghcr.io/michael-genson/jewel-coupon-clipper:latest
    restart: "no"
    shm_size: "1gb"
    environment:
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    volumes:
      - ./users.yaml:/config/users.yaml:ro
```

```sh
docker compose pull
docker compose run --rm jewel-clipper
```
