type AudioInput = Pick<MediaDeviceInfo, 'deviceId' | 'kind' | 'label'>;

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
