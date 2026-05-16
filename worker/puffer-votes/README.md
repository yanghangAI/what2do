# puffer-votes

Tiny Cloudflare Worker that stores satisfied / unsatisfied vote counts for the
Puffer's Pond water-quality card in `index.html`.

## Deploy (one-time, ~5 min)

```sh
# 1. Install Wrangler if you don't have it
npm install -g wrangler

# 2. Log in
wrangler login

# 3. Create the KV namespace
wrangler kv:namespace create VOTES
# Copy the id it prints and paste into wrangler.toml (replace the placeholder)

# 4. Deploy
cd worker/puffer-votes
wrangler deploy
# Prints the production URL, e.g. https://puffer-votes.YOURNAME.workers.dev
```

Then add the URL to `assets/app.js`:

```js
var PUFFER_VOTES_URL = "https://puffer-votes.YOURNAME.workers.dev";
```

## Routes

- `GET /` — returns `{ "satisfied": N, "unsatisfied": M }`
- `POST /` body `{"vote": "satisfied"}` (or `"unsatisfied"`) — increments and returns updated counts
- All routes are CORS-open so the static site can call them directly

## Inspecting / resetting

```sh
# View current counts
wrangler kv:key get --binding=VOTES "puffer-pond"

# Reset
wrangler kv:key put --binding=VOTES "puffer-pond" '{"satisfied":0,"unsatisfied":0}'
```
