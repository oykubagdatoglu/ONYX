# Onyx – last-minute shift fill agent

Open models on Nebius Token Factory (gpt-oss-20b → gpt-oss-120b cascade) turn messy multilingual worker replies into structured availability; plain rules enforce training, overlaps and Dutch flex-law hour bands; the manager approves.

## Run locally
    pip install -r requirements.txt
    export NEBIUS_API_KEY=...
    streamlit run app.py

## Benchmark
    export NEBIUS_API_KEY=...
    export ANTHROPIC_API_KEY=...   # optional closed baseline
    python benchmark/run_benchmark.py   # writes benchmark/results.json -> commit it

## Deploy
Streamlit Community Cloud -> New app -> this repo, main file `app.py` -> Advanced settings -> Secrets:
    NEBIUS_API_KEY = "..."
