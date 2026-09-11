# Optional JSearch research script

jsearch.py is a small manual provider-validation script, not the MVP backend. It reads OPENWEBNINJA_API_KEY through python-dotenv and makes a real network request that consumes provider quota. It prints provider listing data to the terminal. Do not run it as an automated test or commit its raw output without data-use permission.

Local prerequisite: install python-dotenv in an isolated environment and configure the key privately. No credentials are committed. Do not paste keys into chat. The submission’s local MVP uses synthetic/prepared catalogue JSON and needs no provider API key.

This script was inspected for literal credentials but was not executed during handoff preparation. It has no timeout/retry production contract and is not an import pipeline. Keep it out of the assessed runnable application path unless deliberately improved and documented.
