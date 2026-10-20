import { describe, expect, it } from 'vitest';
import { audioSources, resolveAudioSource, preferredComputerInput } from './input';
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
describe('unified audio inputs',()=>{
  it('lists physical and virtual inputs plus internal audio, without presenting speakers as inputs',()=>{
    expect(audioSources([mic('mac','MacBook Microphone'),mic('usb','USB Microphone'),mic('loop','Virtual Audio'),mic('usb','USB Microphone'),mic('default','Default'),{kind:'audiooutput',deviceId:'speaker',label:'Speakers'}],[{id:'speaker',label:'MacBook Pro Speakers'},{id:'headset',label:'EDIFIER W830NB'}])).toEqual([
      {value:'auto',label:'电脑麦克风 · 自动',group:'input'},
      {value:'device:mac',label:'MacBook Microphone',group:'input'},
      {value:'device:usb',label:'USB Microphone',group:'input'},
      {value:'device:loop',label:'Virtual Audio',group:'input'},
      {value:'system:speaker',label:'MacBook Pro Speakers',group:'output'},
      {value:'system:headset',label:'EDIFIER W830NB',group:'output'},
    ]);
  });
  it('resolves device IDs without colliding with the internal-audio choice',()=>{
    expect(resolveAudioSource('auto')).toEqual({kind:'microphone',deviceId:''});
    expect(resolveAudioSource('device:system')).toEqual({kind:'microphone',deviceId:'system'});
    expect(resolveAudioSource('system')).toEqual({kind:'system'});
    expect(resolveAudioSource('system:08:00:00')).toEqual({kind:'system',deviceId:'08:00:00'});
    expect(()=>resolveAudioSource('device:')).toThrow();
  });
});
