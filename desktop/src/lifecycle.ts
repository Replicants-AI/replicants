/** Never exit or replace a live brain without its completed checkpoint receipt. */
interface LifecycleIO {
    connected: () => boolean;
    sendQuit: () => boolean;
    running: () => Promise<boolean>;
    finish: (kind: string, file?: string) => Promise<void>;
}
export class Lifecycle {
  busy = false;
  private pending: { resolve: () => void; reject: (error: Error) => void } | null = null;
  private io: LifecycleIO;
  constructor(io: LifecycleIO) { this.io = io; }

  stopped(checkpointed: boolean) {
    if (checkpointed) this.pending?.resolve();
    else this.pending?.reject(new Error('The brain did not confirm its checkpoint.'));
    this.pending = null;
  }

  failed(reason: string) { this.pending?.reject(new Error(reason)); this.pending = null; }

  async run(kind: string, file?: string) {
    if (this.busy) throw new Error('A life is already being saved or opened.');
    if (kind === 'connect' && this.io.connected()) return;
    this.busy = true;
    try {
      if (this.io.connected()) {
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => this.failed('Saving has not finished. The body remains open; check the inspector.'), 30000);
          this.pending = { resolve: () => { clearTimeout(timeout); resolve(); }, reject: error => { clearTimeout(timeout); reject(error); } };
          if (!this.io.sendQuit()) this.failed('The brain disconnected before saving.');
        });
      } else if (await this.io.running()) {
        throw new Error('The brain is still running but disconnected. Wait for it to reconnect before saving or opening a life.');
      }
      await this.io.finish(kind, file);
    } finally { this.busy = false; }
  }
}
