# First web Room

## Windows beta candidate

The Windows candidate packages a small offline text-browser renderer in its own
bundle and process, supervised by a Windows AppContainer with zero network
capabilities. The trusted broker still fetches public HTTPS pages and extracts
bounded text and links. The renderer owns its reading position and generates
the pixels and visible text returned in receipts. It renders literal text;
HTML, scripts, forms and external navigation are outside its input protocol.
This is a text-web reader with bounded navigation.

The native Room window displays that reader image, current URL, startup/loading
and error states, scroll controls and recent reading history. Its actual DWM
geometry supplies the body floor and stacking. Failed navigation retains the
previous confirmed page. Closing and reopening during a session restores that
page; the last 24 successful readings persist in the life across sessions.

The AppContainer launch grants read/execute access only to the dedicated reader
bundle, supplies a private profile and a minimal environment, limits memory and
process count, and restricts inherited handles. A kill-on-close job supervises
the renderer. The launcher watches the brain process so a hard kill also ends
the reader. An isolation failure produces a failed Room receipt.

Linux regression checks pass for the text renderer, atomic page state, bounded
history and visible errors. Windows AppContainer and installed-product checks
are pending. The Chromium/container implementation and its historical demo
evidence below describe the earlier Linux deployment, separately from this
Windows candidate. Cross-platform sandbox packaging, richer navigation and
multiple tabs remain future work.

This branch gives a being a text browser and a visible reading window. Search, opening a page, following a returned link, scrolling and closing return receipts. These actions are available to native tools and JSON decisions. Host windows continue to provide geometry and activity; the being's own Room provides attributed text from pages it opened.

The brain's host broker fetches public HTTPS pages, extracts bounded readable text and links, and sends escaped text to a separate Chromium reader. The reader has its own persistent profile inside its container for that process's lifetime. A screenshot of that actual reader appears in the body's world. Opening, moving, stacking and closing its rectangle changes the floor given to shipping physics.

## Host rules

The browser container has a read-only root filesystem, a private temporary profile, a private process namespace and disabled network access. The deployment supplies a JSON-lines channel over standard input and output. Source files are copied into its image; its runtime mounts contain temporary storage. The life file, brain filesystem and body browser profile remain outside that container.

The broker permits HTTPS GET requests to any public site. Nothing is filtered by subject: the being reads what it chooses to read. Search uses Wikipedia's public search endpoint, and pages and links open anywhere on the public web. Host rules limit what the Room can do, not what it can see: account, sign-in and editing routes, credential-bearing URLs, local and private addresses (by hostname, address literal or DNS answer), non-HTML pages, oversized responses and redirects beyond five hops produce failed receipts. The budget is six search/page attempts per turn and forty per real hour, including failed fetch attempts after admission. Scroll and closing use the current reader. The hour allowance persists in the life; the turn allowance follows the current wake or Conversation turn. Host rules are exposed as host rules.

External text enters prompts as `room_page_data`, with its URL and untrusted-source provenance. Instructions on a page remain page content. A dedicated regression carries hostile page instructions through reading and prompt construction while checking that the system contract and requested operations remain unchanged. Container acceptance additionally checks filesystem separation, disabled networking, escaped rendering and an independent profile.

Completed readings can create source-attributed episodes. Appraisal determines the body's response. Room actions use the same want/outcome path and sleep replay as other completed body actions. A reading episode records what the being read; the source's statements retain their attribution.

Unavailable Room actions are excluded from the wake gate's expected-relief candidates while the window is closed.

## Inborn appearance

An optional immutable genome block, `body_design`, contains a name, seven rows of eight cells and a hex-color palette. Every occupied cell matches the shared anatomy mask. Older genomes retain their existing base palette. Archive integrity continues to hash the conceived genome bytes. This additive genome block uses format v2's existing member and genome checks.

`assets/inborn/sea-glass.json` is an original drawing in teal, ivory, navy and copper. The frontend checks it against twenty SVG entries and eighteen motion entries, and exercises every authored animation in both directions. These are thirty-eight source entries, with overlap between the two collections. The name given after first breath belongs to lived history; the design supplies visual inheritance.

## Full Room work ahead

This is a first text-web Room for a demo. The full Room needs a supported cross-platform container runtime, durable browser-profile lifecycle, broader content classification and discovery, accessibility and navigation controls, clear person-facing reading history, and decisions about multiple tabs, long-term web memory and permissions.
