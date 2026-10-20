type AudioInput = Pick<MediaDeviceInfo, 'deviceId' | 'kind' | 'label'>;

export type AudioSource = {kind:'microphone';deviceId:string} | {kind:'system';deviceId?:string};
export type AudioOutput = {id:string;label:string;isDefault?:boolean};
export function audioSources(devices:AudioInput[],outputs:AudioOutput[]=[]):{value:string;label:string;group:'input'|'output'}[] {
  const seen=new Set<string>();
  return [
    {value:'auto',label:'电脑麦克风 · 自动',group:'input'},
    ...devices.filter(d=>d.kind==='audioinput'&&d.deviceId&&!['default','communications'].includes(d.deviceId))
      .filter(d=>{if(seen.has(d.deviceId))return false;seen.add(d.deviceId);return true;})
      .map((d,i)=>({value:`device:${d.deviceId}`,label:d.label||`音频输入 ${i+1}`,group:'input' as const})),
    ...outputs.map(d=>({value:`system:${d.id}`,label:d.label,group:'output' as const})),
  ];
}
export function resolveAudioSource(value:string):AudioSource {
  if(value==='system')return {kind:'system'};
  if(value.startsWith('system:')&&value.length>7)return {kind:'system',deviceId:value.slice(7)};
  if(value==='auto')return {kind:'microphone',deviceId:''};
  if(value.startsWith('device:')&&value.length>7)return {kind:'microphone',deviceId:value.slice(7)};
  throw Error('请选择有效的音频输入。');
}

const phone = /iphone|ipad|continuity|接续互通|接续|手机麦克风|phone microphone/i;
const builtIn = /macbook|imac|mac mini|mac studio|built[ -]?in|internal|integrated|内建|内置|麦克风阵列|microphone array|array microphone|realtek/i;

export function preferredComputerInput(devices: AudioInput[]): {device: AudioInput; recognizedBuiltIn: boolean} | null {
  const physical = devices.filter(d => d.kind === 'audioinput' && d.deviceId && !['default', 'communications'].includes(d.deviceId) && d.label);
  const local = physical.filter(d => !phone.test(d.label));
  const recognized = local.find(d => builtIn.test(d.label));
  if (recognized) return {device: recognized, recognizedBuiltIn: true};
  if (local.length) return {device: local[0], recognizedBuiltIn: false};
  return null;
}

export function isPhoneInput(label: string): boolean { return phone.test(label); }
