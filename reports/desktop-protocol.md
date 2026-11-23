# Desktop bridge, protocol 1

The Python desktop platform listens on **127.0.0.1**, on an OS-assigned port.
`~/.replicants/desktop-session.json` contains `protocol`, `port`, `token`, and
`pid`. Its temporary file is protected before the token is written: Windows
ACL grants only the current account and SYSTEM access; POSIX mode is 0600.
Replacement is atomic. The native overlay reads it and connects to `/ws`.
There is no token in the URL, logs, telemetry, or browser storage.

The first WebSocket message is `{ "type": "hello", "protocol": 1,
"token": "…" }`. A missing/wrong token, version, or three-second deadline
closes the connection with 4401. Browser origins are restricted to this Tauri
application and its localhost development server. Native clients may omit
Origin. Frames are limited to 16 KiB; stimuli are bounded and rate limited.

After authentication every packet is:

```json
{
  "protocol": 1,
  "type": "act",
  "id": "unique-message-id",
  "timestamp": 1791890000.0,
  "payload": {"name": "wave", "args": {}}
}
```

`timestamp` is wall-clock Unix seconds. Action completion and wake limits use
real time. IDs are opaque strings, not sequence numbers.

| Direction | Type | Payload |
| --- | --- | --- |
| Brain → body | `ready` | Protocol version; authentication succeeded. |
| Brain → body | `state` | `bars` normalized to 0–1, measured `substrate`, `asleep`, `salience`, `affects`, `mood_tags`, `sim_hour`, `temperament`. |
| Brain → body | `act` | `name`, `args`; the envelope ID identifies this action. |
| Brain → body | `cancel_act` | `act_id` of a timed-out/cancelled action. |
| Brain → body | `say` | `text` for a non-agent status/naming bubble. Deliberate speech uses the acknowledged `say` action. |
| Brain → body | `thought` | `text`, a fresh GEN fragment for hover. |
| Brain → body | `appearance` | `layers` and optional whole-design `preset`/base `palette`. |
| Brain → body | `senses` | `ambient` on/off; `active_app` opt-in (false by default). |
| Brain → body | `error` | Machine-readable `reason`; never a fabricated creature thought. |
| Brain → body | `conception` | Available temperaments; opens the conception form before a life exists. |
| Brain → body | `inspector` | Local lived-state snapshot: clocks, body, desires, memories, markers, lineage, appearance receipts. Sent while the inspector renews its subscription. |
| Brain → body | `stopped` | `checkpointed: true` only after shutdown saved the life and released its identity lock. |
| Body → brain | `sense` | `window_count`, opaque `window_ids`, `idle`, quantized `idle_seconds`, local `hour`; optional opted-in `active_app` executable basename. Changed values only, at most every three seconds. |
| Body → brain | `event` | `kind`: `poke`, `drag_start`, `drag_end`, or `chat`; chat adds `text` (4000-character limit), release may add `velocity`. |
| Body → brain | `act_result` | `act_id`, `status`: `completed` / `failed` / `interrupted`, and observed `detail`. |
| Body → brain | `control` | `name`: `sleep`, `wake`, `ambient`, `active_app`, `quit`, `inspect`, `time_scale` (numeric `scale`, 1–360), or `conceive` (temperament/palette/gestation). |

Actions: `walk_to(target=cursor/window/corner/point, window_id?, side?, x?, y?)`,
`sit`, `sleep`, `wake_up`, `look_at(target?, x?, y?)`, `approach_cursor`,
`inspect_window(window_id?)`, `wave`, `emote(glyph)`, `say(text)`.
Coordinates are physical pixels relative to the primary monitor. A point's
optional y is its supporting edge. Walking does not levitate to higher edges;
missing/unreachable targets fail. Inspect returns geometry evidence only.
All animations are the authored HTML sequences. Acknowledgements are sent
after completion, never on receipt. Picking up, poking, loss of floor,
replacement, timeout, or disconnection interrupts actions.

The brain's WebSocket reader remains independent of its stimulus worker, so a
tool awaiting its own action result cannot deadlock the connection. Unmatched
or duplicate results have no effect. Reconnection interrupts outstanding
actions, sends fresh state/appearance/thought, and uses a new token after a
brain restart. The overlay retains its body/spine if the brain disappears.

Ambient senses are an allowlist: no window titles, pixels, attachments, or
content. They update soma/GEN context without directly enqueueing inference.
Touches apply small static effects immediately (same-kind saturation limited
to four per second), and are appraised in batches no more often than eight
seconds. The normal local-person key is `desktop:local-person`.

Outreach linked to a pending soma desire waits up to 20 real seconds for a
poke, drag, or chat reaction. The appraisal receives actual action results and
whether a reaction occurred. An ignored want and a declined action are
distinct: a decline remains `creature_choice`, while scheduler limits remain
`host_rule`. Realized relief continues to live in the soma snapshot. Reaction
window and touch interval are configurable in entity YAML `desktop` settings.

The default unnamed `desktop-demo` profile permits a wake after 60 real seconds,
requires 15 seconds of conversational silence, and caps wakes at 12/hour.
Its timer is 1–3 real minutes; the inherited extra spacing of up to 45 minutes
is disabled for this development profile and portable births. Explicit named
entities retain their own settings.
An explicitly selected existing entity keeps its configured wake limits,
memory database, soma, models, and identity. Desktop framing and body tools
replace task-oriented cognition on this surface only. The body now reads actual
compute and hardware through `substrate`: reported tokens, elapsed inference,
in-flight requests, time since a completed thought, host RAM and shared GPU
utilization/VRAM. Unknown measurements stay unknown. See [substrate.md](substrate.md)
for units, attribution, persistence and the separation of observation from policy.

Development fixtures `REPLICANTS_SESSION_PATH` and
`REPLICANTS_VERIFY_HIDDEN=1` let the verification script use a separate private
session and noninteractive native overlay while the user's visible body stays
open. They are not enabled in ordinary launches.
