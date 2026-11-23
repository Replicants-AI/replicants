export interface Rect { x: number; y: number; width: number; height: number }
export interface DesktopWindow extends Rect { id: string }
export interface Desktop { monitor: Rect; work: Rect; windows: DesktopWindow[]; idle_seconds: number; fullscreen?: boolean }
export interface BodyState {
  bars: { social: number; curiosity: number; creative: number; tension: number; comfort: number };
  asleep: boolean; salience: number; affects: string[]; mood_tags: string[];
  vigilance?: 'awake' | 'drowsy' | 'asleep'; sleep_pressure?: number;
  substrate?: { inference: { in_flight: { kind: string; model: string; elapsed_seconds: number }[] }; [key: string]: unknown };
  sim_hour: number; temperament: 'curious' | 'shy' | 'social' | 'calm';
  gestating?: boolean; naming?: boolean; name?: string;
}
export type Behavior = 'wander' | 'idle' | 'fidget' | 'sit' | 'look_cursor' | 'approach_cursor' | 'inspect_window' | 'yawn' | 'doze' | 'sleep';
export interface InbornDesign { name: string; rows: string[]; pal: Record<string, string> }
export interface Appearance { preset?: string; palette?: string; layers: string[]; design?: InbornDesign }
export interface Act { id: string; name: string; args: Record<string, unknown> }
export const newbornState = (): BodyState => ({ bars: { social: .45, curiosity: .65, creative: .35, tension: .1, comfort: .6 }, asleep: false, salience: .3, affects: [], mood_tags: [], sim_hour: 12, temperament: 'curious' });
export const contains = (r: Rect, x: number, y: number) => x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height;
