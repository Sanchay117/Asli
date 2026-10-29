# Asli: is that GPU deal real?

**Asli** (असली, Hindi for "genuine") tells Indian PC buyers whether a graphics card listing is worth acting on, before they waste a night waiting for it.

Paste a link from Flipkart, Amazon.in or an Indian PC store. In about 30 seconds Asli reads the listing, prices the same card at trusted Indian stores, checks forums for reports on the seller, looks at how often the listing has actually been buyable, and gives a verdict with sources: **good deal, fair, overpriced, suspicious, or likely bait**.

Built for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents track). It runs on **NVIDIA Nemotron 3 models served by Nebius Token Factory**, with **Tavily** for search and page reading.

## Why

I stayed up till midnight for a cheap RTX 3060 on Flipkart. It said "Notify Me", the sale opened at 12, and it was "not available" again. That is not bad luck. On the first pass of Asli's watcher, **18 of 22 Flipkart GPU listings showed "Notify Me"**, and they were the cheap ones. The RTX 3060 at ₹27,559 to ₹28,839 was never buyable, with an "MRP" of ₹86,000 to make it look like 66% off. The one you could actually buy cost ₹55,999.

The other side of the market has the opposite problem. The same Gigabyte RTX 3060 sits on Amazon.in at **₹58,249 from a third-party seller, non-returnable**. Trusted stores list RTX 3060s at ₹23,900 to ₹27,000, but Asli checked each product page and **every one of those is out of stock**. The real in-stock price is about ₹51,000 to ₹55,000.

Indian buyers piece this together by hand from Reddit, TechEnclave and five store tabs. Asli does it in one paste.

## How it works

```
Paste link
  │
  ├─ 1. Read the listing
  │     Flipkart: parse the JSON Flipkart embeds in the page (price, MRP, stock status,
  │               seller id, Flipkart Assured, GST invoice). No model needed.
  │     Others:   Tavily extract → Nemotron reads price, seller, stock, returns, warranty,
  │               then the store's own schema.org data verifies price and stock.
  │     Blocked:  Flipkart does not serve its pages to cloud servers, so the hosted app asks
  │               for a screenshot, which Nemotron 3.5 Super VL reads in about 4 seconds.
  │
  ├─ 2. Gather evidence, in parallel
  │     Trusted-store prices  Tavily search across MD Computers, PrimeABGB, Vedant,
  │                           EliteHubs, The IT Depot → Nemotron pulls matching offers
  │                           → stock verified on each product page
  │     Community reports     Tavily search on Reddit, TechEnclave, reviews → Nemotron Nano
  │     Warranty context      Tavily search on the brand's authorised sellers in India
  │     Watch history         every snapshot Asli's watcher has taken of this listing
  │
  ├─ 3. Red-flag signals (plain code): % vs market median, claimed MRP discount,
  │     not buyable, non-returnable, in-stock ratio over time
  │
  └─ 4. Verdict, Nemotron 3 Ultra
        Weighs everything, returns verdict, trust score, reasons with sources and an action.
        Every source link is checked against the evidence, and the "buy elsewhere" pick
        must be a real, in-stock, cheaper offer from the price table, so no invented links.
```

The UI streams each step as it runs, with the model, tokens, cost and time for every call.

### The watcher

Every listing anyone checks joins a watchlist, along with popular cards (RTX 3060, 4060, 5060, 5060 Ti, 5070, RX 7600, RX 9060 XT) across Flipkart and trusted stores. A pass every two hours records price and stock. Flipkart and trusted stores are read from their embedded page data, so a pass costs **no model tokens and no Tavily credits**. Over time this turns "this looks like bait" into "this listing was in stock 0 of 40 checks over 12 days". With `NTFY_TOPIC` set, Asli pushes a phone notification (via ntfy.sh) when a watched card becomes buyable from a trusted seller.

## Choosing models by measurement

The brief suggests Nano for fast everyday calls and Ultra for hard reasoning. I measured instead of assuming. `eval/run_eval.py` needs no hand labels:

- **Reading listings:** 29 real trusted-store product pages, scored on price and stock against the schema.org data the store publishes in the same page. Pages whose text does not state the price are excluded, so every case is answerable.
- **Verdict:** 12 scenarios built from real listing data where the correct call follows from clear rules (not buyable with a 66% "discount" is bait, double the market price is overpriced, and so on).

| Task | Setup | Accuracy | Cost per call | Avg time |
|---|---|---|---|---|
| Read listing | Nano | 84% | $0.00022 | 3.4s |
| Read listing | Nano + reasoning | 88% | $0.00052 | 22.3s |
| Read listing | Super | 34% | $0.00119 | 4.1s |
| **Read listing** | **Ultra, reasoning off** | **98%** | $0.00337 | 4.0s |
| Verdict | Nano + reasoning | 75% | $0.00048 | 24.5s |
| Verdict | Super + reasoning | 75% | $0.00160 | 13.2s |
| **Verdict** | **Ultra, reasoning off** | **100%** | $0.00217 | 2.8s |
| Verdict | Ultra + reasoning | 100% | $0.00471 | 4.5s |

Rule: the cheapest setup within 2 points of the best accuracy wins. The eval writes `data/routing.json`, which production reads.

What I learned:
- **Nano misread about 1 in 6 prices.** For a product whose whole job is prices, that is too many, so reading runs on Ultra.
- **Turning reasoning off** (`chat_template_kwargs: {"enable_thinking": false}`) cut output tokens about 7x on extraction with the same answers, and made Ultra both the most accurate and one of the fastest options.
- **Super with JSON mode and reasoning off** returned `{}` or looped on escaped JSON until the token limit. `asli/llm.py` retries without JSON mode, but Super stayed unreliable for this task.
- Forum summaries are not price-critical, so they stay on Nano.

A full check costs about **$0.04** in Nemotron tokens. Prices are Token Factory's list prices from `/v1/models?verbose=true` (Ultra $1.00 in / $3.00 out per million tokens).

## Where Nebius Token Factory and NVIDIA models are used

| Step | Model (Token Factory) | Why |
|---|---|---|
| Read screenshot | `nvidia/Nemotron-3.5-Super-VL`, reasoning off | for sites that block servers (Flipkart) |
| Read listing | `nvidia/Nemotron-3-Ultra-550b-a55b`, reasoning off | 98% on the eval |
| Price trusted stores | `nvidia/Nemotron-3-Ultra-550b-a55b`, reasoning off | same skill as reading |
| Summarise forum reports | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | low stakes, cheapest |
| Verdict | `nvidia/Nemotron-3-Ultra-550b-a55b`, reasoning off | 100% on scenarios, half the cost of reasoning on |
| Evaluation | Nano, Super and Ultra, with and without reasoning | to choose the above |

All calls go through Token Factory's OpenAI-compatible API (`https://api.tokenfactory.nebius.com/v1`). Token Factory made it practical to evaluate three model sizes with and without reasoning on real data in one afternoon, for about a dollar.

**Tavily** does search (trusted stores, forums, warranty) and page extraction (Amazon and store pages).

## Budget safety

- Every model call goes through one function that prices tokens, records them, and refuses to run past `SPEND_CAP_USD` (total) or `MONTHLY_CAP_USD`. Asli pauses itself and says so.
- Tavily calls are metered against `TAVILY_MONTHLY_CREDITS` and cached.
- Results are cached for an hour, so a listing checked twice costs nothing the second time.
- 12 checks per visitor per hour.
- The **Under the hood** tab shows live spend against the caps.

## Run it locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # add NEBIUS_API_KEY and TAVILY_API_KEY
.venv/bin/uvicorn app:app --port 8040
```

Open http://localhost:8040.

Optional:

```bash
.venv/bin/python -m asli.watcher --seed      # track popular GPU listings
.venv/bin/python -m asli.watcher --loop 2    # a watcher pass every 2 hours
.venv/bin/python -m eval.run_eval --collect  # re-run the model evaluation
```

## Deploy (Render free tier + Neon Postgres)

1. Create a free Postgres database on [Neon](https://neon.tech) and copy its connection string.
2. On [Render](https://render.com), create a Blueprint from this repo (`render.yaml`), then set `NEBIUS_API_KEY`, `TAVILY_API_KEY` and `DATABASE_URL`.
3. In the GitHub repo settings, add the secrets `ASLI_URL` (the Render URL) and `WATCH_TOKEN` (copy it from Render's environment tab). The `keepalive` workflow keeps the free instance awake and triggers watcher passes.

## Project layout

```
app.py               FastAPI app: streams checks, serves dashboard data
asli/listing.py      reads a listing (Flipkart page data, Tavily + Nemotron, schema.org check)
asli/evidence.py     trusted-store prices, forum reports, warranty, history, red flags
asli/verdict.py      Ultra verdict, grounded in the evidence
asli/pipeline.py     runs the steps in parallel and streams events
asli/watcher.py      background price and stock watcher
asli/llm.py          Token Factory client: routing, reasoning toggle, spend cap
asli/tavily.py       Tavily client: cache and credit budget
eval/run_eval.py     model evaluation that writes the routing table
static/              the web app
```

## After judging

To make sure nothing can charge the card on file: delete the Nebius API key, and turn off international online transactions on the card in the bank app.

## Limitations

- Flipkart's seller name is not in its page data, only a seller id, so Asli cannot yet name Flipkart third-party sellers.
- Fetching store pages directly is kept slow and infrequent on purpose. If a site blocks it, pasting the listing text still works.
- Asli is advice, not a guarantee. Always check the seller page yourself.

## License

MIT
