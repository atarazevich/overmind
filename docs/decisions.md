# Decisions

## 2026-09-17 — Substrate
Jev (TypeSafe System One) as the per-event judge instead of an LLM. Context: the April Overmind ran an LLM watcher and was too slow and expensive to run on every event; Jev returns typed probabilities in ~300 ms at ~$0.04/day. Local alternatives (GLiNER2.5, constrained-decoding on Qwen 1.5B) noted; not calibrated; to be compared later on the labels this project collects.

## 2026-09-17 — Observe first
Phases fixed as observe → label → inject. No action of any kind before the calibration curve exists.

## 2026-09-17 — Hook process shape
`os.fork` + `setsid` with stdio on `/dev/null`, not `subprocess.Popen` of a second interpreter: `import subprocess` costs 4–5 ms and a second interpreter start ~20 ms, against a 50 ms synchronous budget. `urllib.request` (23–25 ms) is imported only in the child. The wiring and the shebang name `/usr/bin/python3` (system 3.9.6, the agent-notch pattern) because the bare `python3` on PATH is a pyenv shim that adds ~110 ms. Context: measured with `-X importtime` and `perf_counter` around the hook process on 2026-09-17.
