**Measured substrate, October 31, 2026.** The body reads the actual compute conditions under which it thinks. The previous circadian `energy` value and inspection-count glasses reward have been removed. Tokens and elapsed time are measurements; a percentage of invented fuel is not substituted for them.

`replicants/desktop/substrate.py` provides a persistent compute ledger, a provider wrapper, and independent hardware sensors. The runtime sends its snapshot in `state.substrate`, exposes it in the inspector, and supplies it to deliberate cognition and GEN. The ordinary animation selector can use an actual in-flight chat request to select the authored thinking pose. Pose pixels, sequence timing, throwing and window physics remain the authored implementations.

| Signal | Measurement and scope |
| --- | --- |
| Reported input/output tokens | Per-provider response counts, accumulated separately for prompt and completion tokens. Each counter has a coverage count. Missing usage is unknown. |
| Request latency | Monotonic elapsed seconds around each chat/embedding request, including queueing, transport, retry waiting and inference. Overlapping requests may contribute overlapping durations. |
| Provider timing | Native non-thinking Ollama responses retain total, load, prompt-evaluation and generation durations, converted from nanoseconds to seconds. Other paths may not supply them. |
| In-flight inference | Request kind, model and current real elapsed time. No prompt text is stored in the ledger. |
| Time since thought | Real elapsed time since the last successfully completed chat inference, including auxiliary appraisals/GEN. Embeddings do not reset this clock. |
| RAM | Host total and available bytes, used percentage, and this Python process's resident memory. It does not include the separate Ollama or WebView process trees. |
| GPU | Driver-reported whole-device utilization and VRAM used/total, per device. Shared with other programs; no attribution to this being is inferred. |

Ollama documents response token counts and nanosecond duration fields in its [chat API](https://docs.ollama.com/api/chat). The NVIDIA sensor uses the installed driver's read-only selective CSV query, with no package dependency. Unsupported driver fields remain null; absent/failed sensors remain unavailable. NVIDIA documents both selective queries and unavailable values in [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html). Non-NVIDIA GPU sensing is not implemented.

Hardware is sampled on a separate task every ten real seconds, independent of simulation speed and inference. Each sensor result includes status, source/scope when available, and age. GPU queries have a three-second timeout and clean up their child process on timeout/cancellation. Sampling does not call a language model.

All desktop components holding inference-provider references are bound to the metered client, including inherited knowledge/procedural/router/deliberate components. The native Ollama adapter retains actual `think:false` control on auxiliary calls. Deliberate thinking/streaming keeps its existing transport. Embedding vectors and text-only streams do not expose token counts through the inherited API and are recorded without counts.

The ledger counts started, completed, failed and cancelled requests and elapsed time. It persists in `desktop-state.json` and portable checkpoints. Counters begin when instrumentation is introduced; old lives do not get invented historical usage. Retries and failed requests may consume unreported tokens, so reported totals are lower-bound accounting. They are not joules, GPU-seconds, or a bill. Hardware readings and in-flight state are not restored as current measurements after a restart or move to another host.

Regulation is a separate layer from measurement. Existing circadian sleep and real-time host limits still apply. Cognition can observe compute conditions and choose to rest; deterministic metabolic regulation requires a separately specified and calibrated policy. A busy GPU is not by itself proof that this being is exhausted.

`LivingReplicant` no longer counts inspections or grants glasses. Existing inspection observations remain ordinary receipts/memories. On loading an older life, the specific former reward is removed and a one-time `host_revision` records the correction; prior lineage and unrelated appearance are preserved. SVG assets and mock appearance studies remain visual source material, without a live reward mechanic.

The old appearance probe has become `scripts/probe_substrate.py`: a fresh verification birth, unforced behavior, compute observation, and accounting persistence. `probe_desktop_life.py` no longer waits for glasses or raises curiosity to pursue them. These probes still require the documented isolated native build/verification setup; they have not been rerun as live-model acceptance for this change.

