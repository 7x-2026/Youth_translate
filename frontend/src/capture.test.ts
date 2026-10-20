import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { Capture } from './capture';
vi.mock('./worklet.ts?worker&url',()=>({default:'/worklet.js'}));
let context:any, node:any, fail=false;
let track:any, getUserMedia:any;
beforeEach(()=>{
  fail=false;
  track={readyState:'live',label:'USB Microphone',getSettings:()=>({deviceId:'usb'}),stop:vi.fn(),onended:null,onmute:null};
  class Stream {constructor(public tracks:any[]){} getTracks(){return this.tracks;}getAudioTracks(){return this.tracks;}}
  getUserMedia=vi.fn(async()=>new Stream([track]));
  vi.stubGlobal('navigator',{mediaDevices:{getUserMedia,enumerateDevices:vi.fn(async()=>[])}});
  vi.stubGlobal('MediaStream',Stream);
  vi.stubGlobal('AudioContext',class {
    state='running';destination={};onstatechange=null;
    audioWorklet={addModule:vi.fn(async()=>{if(fail)throw Error('worklet failed');})};
    resume=vi.fn(async()=>{});close=vi.fn(async()=>{});
    createMediaStreamSource=vi.fn(()=>({connect:(n:any)=>n}));
    constructor(){context=this;}
  });
  vi.stubGlobal('AudioWorkletNode',class {
    port={postMessage:vi.fn(),close:vi.fn(),onmessage:null};disconnect=vi.fn();connect=vi.fn();
    constructor(){node=this;}
  });
});
afterEach(()=>vi.unstubAllGlobals());
it('preserves explicit microphone device and room constraints',async()=>{
  const capture=new Capture(vi.fn(),vi.fn(),vi.fn());await capture.open({kind:'microphone',deviceId:'usb'},80,true);
  expect(getUserMedia).toHaveBeenCalledWith({audio:{deviceId:{exact:'usb'},channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:true},video:false});
  expect(capture.isLive()).toBe(true);expect(node.port.postMessage).not.toHaveBeenCalled();
  capture.enable(true);expect(node.port.postMessage).toHaveBeenCalledWith({type:'gate',enabled:true});
  await capture.close();expect(track.stop).toHaveBeenCalledOnce();expect(context.close).toHaveBeenCalledOnce();
});
it('reports an interrupted microphone once',async()=>{
  const problem=vi.fn(),capture=new Capture(vi.fn(),vi.fn(),problem);
  await capture.open({kind:'microphone',deviceId:'usb'},80);track.onmute();track.onended();
  expect(problem).toHaveBeenCalledOnce();await capture.close();expect(track.onended).toBeNull();
});
it('cleans up the microphone if initialization fails',async()=>{
  fail=true;await expect(new Capture(vi.fn(),vi.fn(),vi.fn()).open({kind:'microphone',deviceId:'usb'},80)).rejects.toThrow('worklet failed');
  expect(track.stop).toHaveBeenCalledOnce();expect(context.close).toHaveBeenCalledOnce();
});
