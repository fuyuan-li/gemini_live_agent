# TODO

## Near-Term Product Expansions

1. Add a `maps_agent` for map-specific workflows.
- Scope: route planning, switching travel mode, finding nearby places, map-first search and pan/zoom strategies.
- Why: maps are a strong demo surface for pointer-aware voice interaction in a hackathon setting.
- Tool strategy: either reuse the existing browser tools with map-focused prompting, or give `maps_agent` its own constrained browser toolset.

2. Add a `search_agent` for general web search outside the current page.
- Scope: compare products, gather background info, search before navigating.
- Why: avoids forcing every information request through Playwright page control.
- Tool strategy: web search / grounding style tools, not page-manipulation tools.

3. Add a `utility_agent` for non-browser live queries.
- Scope: weather, time, quick factual lookups, simple travel context.
- Why: gives the concierge a clear place to route non-page tasks without polluting browser prompts.
- Tool strategy: lightweight utility APIs only.

4. Consider a `media_agent` for YouTube or media-site control.
- Scope: search videos, open media pages, basic playback control.
- Why: visually strong demo path for live voice + pointer interaction.
- Tool strategy: browser tools plus media-specific prompting.

## Architecture Follow-Ups

1. Keep `concierge` as the root coordinator if multi-domain scope expands.
- Current structure `concierge -> browser_agent` is a good base.
- If new specialists are added, make them siblings under `concierge`, not children of `browser_agent`.

2. Keep pointer as shared state, not a standalone routing agent.
- Current cursor flow already works: client tracking -> server cursor cache -> callback injects pointer into tool context.
- Prefer expanding pointer-aware tools and prompts inside domain agents instead of reintroducing a `pointer_agent`.

3. If calibration persistence is added later, store it per `(user_id, device_id)`.
- Prefer Firestore over package-local JSON.
- Do not store calibration in the realtime session cursor cache.
