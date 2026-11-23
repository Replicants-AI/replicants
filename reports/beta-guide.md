# Replicants Windows beta

This guide describes the 0.3.0-beta.2 candidate. Download published installers from
[Releases](https://github.com/Replicants-AI/replicants/releases). Signing status and
checksums accompany each build.

The beta is one local Replicant on a Windows x64 desktop. Windows 11 is recommended;
Ollama lists Windows 10 22H2 or newer as its minimum. See its
[Windows requirements](https://docs.ollama.com/windows) for supported GPU drivers.
The installer includes
its Python backend and isolated Room reader. Home can prepare a private local
Ollama runtime and models. The installer supplies the application dependencies;
thought runs on the same computer. Its private runtime starts with Ollama cloud
features disabled.

## First launch

1. Install the beta from Releases. Compare its SHA-256 with the release
   checksums. This beta's signing status is recorded in its release notes.
2. Open Replicants and choose **Set up** on Home. It checks available hardware,
   prepares the local runtime and downloads a mind and memory. The progress display
   separates runtime and model downloads. Cancel ends the download client; another
   setup attempt can resume model layers already downloaded.
3. Home becomes **Ready for a life** when both local models respond. Automatic
   setup selects models for the measured hardware. Model weights can use several
   gigabytes of disk and memory, plus context and the desktop application.
4. Settings lets experienced users choose a separately installed Ollama, installed
   models, JSON or native tool decisions and compute limits. An existing running
   Ollama can be reused. Explicit model downloads require the download checkbox.
   Downloads use internet access; inference uses localhost. Cloud models and
   aliases reporting a remote host fail readiness. Model quality remains distinct
   from application readiness.
5. On Home, welcome a new Replicant or open an existing `.replicant` file. Choose
   a starting character and temperament. The pixel editor lets you paint each body
   pixel with its own color, sample colors with the eyedropper, undo or redo whole
   strokes, and preview the drawing in motion. Save and load drawing files to reuse
   artwork. The drawing becomes the being's inborn appearance at conception.
   Let it develop curiosity and reach first breath. Give
   it a name in Conversation. A slow model can make this take longer than the
   gestation setting. You can cancel before conception.

## Everyday use

Home shows the current name, vigilance, last completed checkpoint, and connection
state. Conversation retains the latest 400 received messages and delivered speech
inside the life record. A completed turn can be quiet. Queued, processing, failed,
and interrupted turns are labeled. A draft stays in its window until the backend
acknowledges receipt. Enter sends; Shift+Enter inserts a line break.
Conversation shows actual in-flight inference and elapsed request time, drowsiness,
sleep and pausing. A failed or interrupted message can be copied back into the
composer with **Use these words again**; sending remains an explicit action.

Double-click the desktop body or press Ctrl+Alt+R to open Conversation. If another
program owns that shortcut, the tray and Home remain available. Poke, lift, drag,
and throw the body using the existing authored motion system. The body uses the
primary monitor and follows changes to its geometry. Fullscreen hiding and body
size are configurable. Idle animation and thought-fragment display are optional.
The beta runs body time at real speed and hides development clock controls. An
older accelerated life retains its recorded history and offline gap; after opening,
it continues at real speed.

Sleep follows the life loop and can include memory work. **Pause thinking** lets
the current turn finish, then stops new inference until resumed. The physical
clock still passes. **Save and close this life** checkpoints and returns to the
library. **Save and quit** waits for a checkpoint acknowledgement before exit.
Closing a product window keeps the application in the tray. Cancelling a model
download or quitting stops the download client. Ollama is a separate shared
service when you selected an external runtime and may keep model weights cached
after Replicants closes. The private runtime started by Replicants is stopped
when the application quits.

## Its Room

Choose Room in the navigation, then **Open its Room**. The being can search,
read public HTTPS pages, follow returned links, scroll and close its page. Its
Room window is an actual floor in its desktop world; moving, minimizing, stacking
or closing that window changes the geometry it can use.

You see the current reader image, source URL, loading and failure states, and
the last 24 successful readings. Read above/below changes the visible text for
both of you. Closing and reopening during the session restores the confirmed page.
A failed page attempt preserves the previous page. History persists with the life;
opening a life starts with a closed, fresh reader.

This Room reads extracted text. Account/sign-in/editing routes, private addresses,
non-HTML responses and oversized pages fail with a receipt. The broker accepts
public HTTPS GET navigation, with six page attempts per turn and forty per real
hour. The renderer has a separate AppContainer profile, zero network capabilities
and access to its own bundle. Page instructions remain attributed source material.
Web requests contact the chosen sites and reveal the computer's public IP.

Your lives appear on Home. One click reopens them. Open life folder reveals the
default storage directory. An external life file joins the local library after
a successful wake. One being can be awake at a time. Model/sensing/compute settings
take effect on the next wake; display preferences apply immediately.

## Data, privacy, and recovery

Default host data is under `%USERPROFILE%\.replicants`. New lives are under its
`beings` directory. Each `.replicant` has a `.replicant.bak` last-good checkpoint.
The archive holds the immutable genome, hash-linked lineage, local memory, body
state, and conversation. Host settings and the local library stay outside it.
Moving a life means moving its file; copy the backup too when possible. Close
the life before copying it to preserve the latest checkpoint.

Opening verifies all archive members and lineage before using them. If the main
file is corrupt, opening can recover the verified backup and record that recovery.
Autosaves run roughly every 30 seconds, successful conversation turns checkpoint,
and clean shutdown checkpoints again. Received messages and receipt-confirmed
speech trigger archive checkpoints before optional reflection continues. Home
shows the last completed save. If a delivered reply survived a crash, its message
reopens as completed with a note about interrupted background work. A turn whose
reply was unsaved reopens as interrupted. Retry explicitly from Conversation.

If a background loop stops unexpectedly, the runtime attempts a supervised save
and shutdown. If the desktop crashes, background thinking stops while disconnected;
the beta saves and stops after a 90-second reconnection grace period. A failed
checkpoint never counts as a successful shutdown receipt. Keep the application
open if it reports a save failure and check disk space or the inspector.

Ambient senses expose window geometry and idle time. They do not expose titles,
window contents, clipboard, screenshots, or files. Active-app basename sensing is
a separate session permission in the inspector. Thought display is off by default.
Conversation and normal backend logs can contain private material; do not share
them casually. Export support details produces a small JSON status report without
prompts, messages, thoughts, logs, paths, descriptor tokens, or authentication.

## Scope and updates

Compute tokens, timing, occupancy, idle run, RAM and available GPU readings are
measurements. Unavailable readings stay unknown; shared host pressure is labeled.
The relative metabolism model remains **shadow mode** with `applied: false` and
calibration gates. The sleep life loop already uses observed occupancy.

Nerve, Arweave, permanent uploads, all web3 integrations, branching, and simultaneous
beings are deferred. New lives use archive format v2, with branch/head integrity
and an in-place, backed-up upgrade for v1 lives. The immutable genome keeps its
conceived bytes; framework defaults are recorded when older genomes lack blocks.
A local `birth_sealed`
lineage entry completes birth; it performs no network seal or upload.

Updates are manual: Settings opens the releases page. Close the current
life, install the newer beta, then reopen the life. Host data remains outside the
application directory. There is no automatic updater or signing claim in the UI.
