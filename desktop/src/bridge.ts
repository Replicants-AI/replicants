import { invoke } from '@tauri-apps/api/core';

export interface Packet { protocol: 1; type: string; id: string; timestamp: number; payload: Record<string, any> }
export class Bridge {
  socket: WebSocket | null = null; connected = false;
  private stopped = false;
  onPacket: (packet: Packet) => void = () => {};
  onDisconnect: () => void = () => {};
  send(type: string, payload: Record<string, unknown>, id: string = crypto.randomUUID()) {
    if (!this.connected || this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({ protocol: 1, type, id, timestamp: Date.now() / 1000, payload }));
    return true;
  }
  async start() {
    while (!this.stopped) {
      try {
        const session = await invoke<null | { protocol: number; port: number; token: string }>('desktop_connection');
        if (session?.protocol === 1 && Number.isInteger(session.port) && session.port > 0 && session.port < 65536 && typeof session.token === 'string') {
          await new Promise<void>(resolve => {
            const ws = new WebSocket(`ws://127.0.0.1:${session.port}/ws`); this.socket = ws;
            const timeout = setTimeout(() => ws.close(), 4000);
            ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', protocol: 1, token: session.token }));
            ws.onmessage = event => {
              let data: Packet;
              try { data = JSON.parse(event.data); } catch { return; }
              if (data.protocol !== 1 || typeof data.type !== 'string' || !data.payload) return;
              if (data.type === 'ready') { this.connected = true; clearTimeout(timeout); }
              this.onPacket(data);
            };
            ws.onclose = () => { clearTimeout(timeout); this.connected = false; this.onDisconnect(); resolve(); };
            ws.onerror = () => ws.close();
          });
        }
      } catch { /* Descriptor may be between atomic replacements or brain still starting. */ }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
  stop() { this.stopped = true; this.socket?.close(); }
}
