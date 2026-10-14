import { describe, expect, it } from 'vitest';
import { preferredComputerInput } from './input';
const mic=(deviceId:string,label:string)=>({deviceId,label,kind:'audioinput' as const});
describe('automatic computer microphone',()=>{
  it('chooses Mac built-in instead of iPhone and default alias',()=>{
    const chosen=preferredComputerInput([mic('default','Default - iPhone Microphone'),mic('phone','iPhone Microphone'),mic('mac','MacBook Pro Microphone')]);
    expect(chosen?.device.deviceId).toBe('mac');
    expect(chosen?.recognizedBuiltIn).toBe(true);
  });
  it('chooses Windows microphone array instead of phone or headset',()=>{
    const chosen=preferredComputerInput([mic('headset','USB Headset'),mic('phone','iPhone Microphone'),mic('pc','Microphone Array (Realtek(R) Audio)')]);
    expect(chosen?.device.deviceId).toBe('pc');
  });
  it('does not silently select a phone when it is the only labeled device',()=>{
    expect(preferredComputerInput([mic('default','Default - iPhone'),mic('phone','iPhone Microphone')])).toBe(null);
  });
});
