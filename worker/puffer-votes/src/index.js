// Single-purpose Cloudflare Worker: stores a satisfied / unsatisfied vote
// counter for Puffer's Pond water quality in Workers KV.
//
// Routes:
//   GET  /            → JSON {satisfied, unsatisfied}
//   POST /  {vote}    → increment counter; returns updated JSON
//   OPTIONS /         → CORS preflight
//
// One KV binding is required: VOTES. Storage key: "puffer-pond".

const KEY = "puffer-pond";
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};
const JSON_HDR = { "Content-Type": "application/json", ...CORS };

const empty = () => ({ satisfied: 0, unsatisfied: 0 });

async function read(env) {
  return (await env.VOTES.get(KEY, "json")) || empty();
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }
    if (req.method === "GET") {
      return new Response(JSON.stringify(await read(env)), { headers: JSON_HDR });
    }
    if (req.method === "POST") {
      let body;
      try { body = await req.json(); }
      catch { return new Response("bad json", { status: 400, headers: CORS }); }
      const vote = body && body.vote;
      if (vote !== "satisfied" && vote !== "unsatisfied") {
        return new Response("invalid vote", { status: 400, headers: CORS });
      }
      const data = await read(env);
      data[vote] = (data[vote] || 0) + 1;
      await env.VOTES.put(KEY, JSON.stringify(data));
      return new Response(JSON.stringify(data), { headers: JSON_HDR });
    }
    return new Response("method not allowed", { status: 405, headers: CORS });
  },
};
