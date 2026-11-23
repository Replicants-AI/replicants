import { invoke } from '@tauri-apps/api/core';
import { metabolismReadout } from './metabolism-view.ts';

export async function inspector(panel: HTMLElement) {
  const options = await invoke<{ verify_hidden: boolean; development: boolean }>('runtime_options');
  panel.hidden = false;
  panel.innerHTML = '<h1>Replicant inspector</h1><p id="identity">Waiting for a connected brain…</p><p id="clocks"></p><div id="clock-controls"></div><p id="connection"></p><div id="details"></div>';
  for (const scale of options.development ? [1, 60, 360] : []) {
    const button = document.createElement('button'); button.textContent = `${scale}×`;
    button.onclick = () => void invoke('request_control', { value: { name: 'time_scale', scale } });
    panel.querySelector('#clock-controls')!.append(button);
  }
  const permission = document.createElement('button'); permission.disabled = true;
  permission.textContent = 'Allow active-app names for this session';
  permission.onclick = () => void invoke('request_control', { value: { name: 'active_app' } });
  const explanation = document.createElement('p');
  explanation.textContent = 'Optional: share the foreground application basename during this session. No window titles or contents. Ambient sensing must also be enabled in Settings. This permission resets when the life closes.';
  panel.querySelector('#details')!.before(permission, explanation);
  const sections = [
    ['body', 'Body'], ['fragments', 'Inner fragments'], ['pending_desires', 'Pending desires'],
    ['unlived_wants', 'Unlived wants'], ['markers', 'Gut reactions toward people'], ['memories', 'Recent memories'],
    ['appearance', 'Appearance'], ['substrate', 'Measured compute and hardware'],
    ['metabolism_measured', 'Metabolism · measured'], ['metabolism_calibration', 'Metabolism · calibration'],
    ['metabolism_model', 'Metabolism · model (shadow mode)'],
    ['life_loop', 'Life loop · model state'], ['decisions', 'Model decision counts'],
    ['wake_limits', 'Current host wake allowance'], ['learning', 'Learning availability'],
    ['last_appraisal', 'Latest pressure interpretation'],
    ['acceptance', 'Measured validation acceptance (current brain process)'],
    ['lineage', 'Lineage (latest 100)'], ['actions', 'Recent action receipts'], ['realized_relief', 'Realized relief'],
  ];
  const outputs = new Map<string, HTMLElement>();
  for (const [key, title] of sections) {
    const section = document.createElement('details'); section.open = ['body', 'fragments', 'pending_desires', 'unlived_wants', 'metabolism_measured', 'metabolism_model'].includes(key);
    const heading = document.createElement('summary'); heading.textContent = title;
    const output = document.createElement('pre'); outputs.set(key, output); section.append(heading, output);
    panel.querySelector('#details')!.append(section);
  }
  const refresh = async () => {
    const data = await invoke<Record<string, any> | null>('inspector_state');
    if (!data) return;
    permission.disabled = !data.connected;
    permission.textContent = data.sense_permissions?.active_app ? 'Stop sharing active-app names' : 'Allow active-app names for this session';
    panel.querySelector('#identity')!.textContent = `${data.name || 'Unnamed'} · ${data.phase || ''}\n${data.id || ''}\n${data.file || 'Development body'}`;
    if (data.clock) panel.querySelector('#clocks')!.textContent = `Body time: ${new Date(data.clock.sim * 1000).toLocaleString()} (${data.clock.scale}×)\nWall time: ${new Date(data.clock.wall * 1000).toLocaleString()}`;
    const vigilance = data.state?.vigilance || (data.state?.asleep ? 'asleep' : 'awake');
    panel.querySelector('#connection')!.textContent = data.error || `${data.connected ? 'Connected' : 'Disconnected'} · ${vigilance} · ${data.model_calls_last_minute ?? 0} model calls in the last real minute`;
    const body = { bars: data.state?.bars, baselines: data.baselines, affects: data.affects, dreaming: data.dreaming, vigilance, sleep_pressure: data.state?.sleep_pressure, senses: data.senses, real_time_wake_limits: data.wake_limits };
    const metabolism = metabolismReadout(data.metabolism);
    for (const [key, output] of outputs) {
      if (key.startsWith('metabolism_')) {
        output.textContent = metabolism[key.slice('metabolism_'.length) as keyof typeof metabolism];
        continue;
      }
      const value = key === 'body' ? body : data[key];
      output.textContent = value == null || (Array.isArray(value) && !value.length) ? 'None yet.' : JSON.stringify(value, null, 2);
    }
    if (options.verify_hidden) await invoke('report_inspector_render', { text: panel.textContent });
  };
  await refresh(); setInterval(() => void refresh(), 2000);
}
