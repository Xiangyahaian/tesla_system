# Integration & stress tests

Runnable suites against a live model endpoint (local vLLM or remote). Unit tests live in `tests/`.

## Layout

```text
test/
├── README.md
├── test_cases*.json          # scenario fixtures
├── run_profile_compact_test.py
├── run_stress_*.py
├── diagnose_extract.py
├── results/                  # local run outputs (gitignored)
└── eval_results/             # local eval dumps (gitignored)
```

## Profile / compact suite

```bash
conda activate tesla
python test/run_profile_compact_test.py
```

Requires a configured model in `.env` (`VLLM_*` or Bailian) and `AGENT_ENABLE_AUTO_MEMORY=1`.

## Stress suites

```bash
python test/run_stress_100.py
python test/run_stress_suite.py
```

Fixtures: `test/test_cases_stress_*.json`. Generated reports stay local and are not committed.
