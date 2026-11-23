export interface Rep { name: string; rows: string[]; pal: Record<string, string> }
export interface Pose {
  eyes?: string; gx?: number; gy?: number; headDy?: number; headDx?: number;
  bodyDy?: number; hands?: string; legs?: string; kick?: boolean; rot?: number;
  lie?: string; breathe?: boolean; dx?: number; dy?: number; dxF?: number;
  flip?: boolean; clip?: boolean; reveal?: number; scan?: boolean; tint?: string;
  rowShift?: number[]; ghost?: { dx: number; col: string }[];
  fx?: { col: string; abs: boolean; cells: number[][] }[];
}
export interface Animation { id: string; name: string; cat: string; loop: number; frames: [number, Pose][] }
export const REPS: Rep[], MASK: string[], ANIMS: Animation[];
export const A: Record<string, Animation>, SEQ: Record<string, Animation>;
export const FW: number, FH: number, OX: number, OY: number;
export function compose(rep: Rep, pose: Pose): [number, number, string][];
export function poseAt(animation: Animation, time: number): Pose;
export interface LifeBody {
  i: number; x: number; y: number; flip: boolean; state: string; t: number; dur: number;
  sleepKind: string; mood: number; social: number; next: number; blink: number;
  walkTo: number; step: number; stepT: number; vx: number; vy: number; peak: number; tumbled: boolean;
  on: null | { x0: number; x1: number };
}
export function createLifeMotion(random?: () => number): {
  start(body: LifeBody, state: string): void; impact(body: LifeBody): void;
  pose(body: LifeBody): Pose; AFTER: Record<string, string>;
  configure(width: number, cursor: { x: number; y: number; inside: boolean }): void;
  register(body: LifeBody): void;
};
