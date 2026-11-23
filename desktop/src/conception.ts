import { designEditor } from './design-editor.ts';
import './design-editor.css';
import type { InbornDesign } from './types.ts';

export interface BirthChoices { temperament: string; gestation_seconds: number; design: InbornDesign }
export function renderConception(panel: HTMLElement, send: (value: BirthChoices) => Promise<void>, cancel: () => void) {
  panel.classList.add('conception-panel');
  panel.innerHTML = `<header class="birth-heading"><span class="eyebrow">A new life</span><h1>A shape of their own.</h1><p>Start with a character, then draw the details yourself.</p></header><form id="conception"><div id="design-editor"></div><div class="birth-settings"><label>Temperament<select name="temperament"><option>curious</option><option>shy</option><option>social</option><option>calm</option><option>roll</option></select></label><label>Gestation, in seconds<input name="gestation" type="number" value="90" min="5" max="86400" required></label></div><p class="quiet">The body must become curious enough to take its first breath.</p><div class="birth-footer"><button type="button" class="link-button" id="cancel-birth">Cancel this birth</button><button class="primary" type="submit" id="conceive">Conceive</button></div><p id="birth-status" role="status" aria-live="polite"></p></form>`;
  const editor = designEditor(panel.querySelector<HTMLElement>('#design-editor')!);
  const form = panel.querySelector<HTMLFormElement>('form')!;
  const button = panel.querySelector<HTMLButtonElement>('#conceive')!;
  const temperament = form.querySelector<HTMLSelectElement>('[name=temperament]')!;
  const gestation = form.querySelector<HTMLInputElement>('[name=gestation]')!;
  let pending = false;
  const busy = (value: boolean) => { pending = value; button.disabled = value; temperament.disabled = value; gestation.disabled = value; editor.disabled(value); };
  const showError = (error: unknown) => {
    busy(false); panel.querySelector('#birth-status')!.textContent = String(error instanceof Error ? error.message : error);
  };
  form.onsubmit = async event => {
    event.preventDefault(); if (pending) return;
    const value = { temperament: temperament.value, gestation_seconds: Number(gestation.value), design: editor.design() };
    busy(true); panel.querySelector('#birth-status')!.textContent = 'A first stir…';
    try { await send(value); } catch (error) { showError(error); }
  };
  panel.querySelector<HTMLButtonElement>('#cancel-birth')!.onclick = cancel;
  return { showError, destroy: editor.destroy };
}
