import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { SystemCapture } from './system-capture';
import { pcm16 } from './audio';
class Socket {
  static OPEN=1;static CLOSED=3;static instances:Socket[]=[];
  readyState=1;binaryType='';onopen:any;onmessage:any;onerror:any;onclose:any;
  listeners:(()=>void)[]=[];send=vi.fn((data:string)=>{if(data==='stop')this.close();});
  close=vi.fn(()=>{this.readyState=3;this.onclose?.();this.listeners.forEach(fn=>fn());});
  addEventListener(_type:string,fn:()=>void){this.listeners.push(fn);}
  constructor(public url:string){Socket.instances.push(this);}
  message(data:any){this.onmessage?.({data});}
}
beforeEach(()=>{Socket.instances=[];vi.useFakeTimers();vi.stubGlobal('WebSocket',Socket);vi.stubGlobal('location',{protocol:'http:',host:'localhost:8765'});});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
async function open(packet=vi.fn(),meter=vi.fn(),problem=vi.fn(),packetMs=80){
  const capture=new SystemCapture(packet,meter,problem),opening=capture.open({kind:'system'},packetMs);
  const socket=Socket.instances.at(-1)!;socket.onopen();socket.message(JSON.stringify({type:'ready',sampleRate:16000,label:'native audio'}));
  expect((await opening).label).toBe('native audio');return {capture,socket};
}
it('uses only the local native service and sends heartbeat while waiting for permission',async()=>{
  const {capture,socket}=await open();expect(socket.url).toBe('ws://localhost:8765/ws/system-audio');
  await vi.advanceTimersByTimeAsync(10000);expect(socket.send).toHaveBeenCalledWith('heartbeat');
  expect(capture.isLive()).toBe(true);await capture.close();expect(capture.isLive()).toBe(false);expect(socket.close).toHaveBeenCalledOnce();
});
it('captures the selected output endpoint using its opaque hardware ID',async()=>{
  const capture=new SystemCapture(vi.fn(),vi.fn(),vi.fn());
  const opening=capture.open({kind:'system',deviceId:'device:08/00'},80),socket=Socket.instances[0];
  expect(socket.url).toBe('ws://localhost:8765/ws/system-audio?device=device%3A08%2F00');
  socket.message(JSON.stringify({type:'ready',sampleRate:16000,label:'EDIFIER W830NB'}));
  expect((await opening).label).toBe('EDIFIER W830NB');await capture.close();
});
it('gates upload, preserves PCM across odd chunk boundaries, meters, and flushes the short tail',async()=>{
  const packet=vi.fn(),meter=vi.fn(),{capture,socket}=await open(packet,meter);
  const bytes=pcm16(Array(1900).fill(.25));socket.message(bytes);expect(packet).not.toHaveBeenCalled();
  capture.enable(true);socket.message(bytes.slice(0,3));socket.message(bytes.slice(3));
  expect(packet).toHaveBeenCalledOnce();expect(packet.mock.calls[0][0].byteLength).toBe(2560);
  socket.message(pcm16(Array(1280).fill(.25)));expect(meter).toHaveBeenCalledWith(expect.closeTo(.25,4));
  await capture.close(true);
  expect(packet.mock.calls.map(([buffer])=>buffer.byteLength)).toEqual([2560,2560,1240]);
  expect(packet.mock.calls.reduce((sum,[buffer])=>sum+buffer.byteLength,0)).toBe((1900+1280)*2);
});
it('drops pending audio when disabled and uses 40 ms packets',async()=>{
  const packet=vi.fn(),{capture,socket}=await open(packet,vi.fn(),vi.fn(),40);
  capture.enable(true);socket.message(pcm16(Array(500).fill(.1)));capture.enable(false);capture.enable(true);
  socket.message(pcm16(Array(640).fill(.2)));expect(packet).toHaveBeenCalledOnce();expect(packet.mock.calls[0][0].byteLength).toBe(1280);await capture.close();
});
it('uploads two minutes of silence without treating it as a pause, then resumes sound',async()=>{
  const packet=vi.fn(),meter=vi.fn(),problem=vi.fn(),{capture,socket}=await open(packet,meter,problem);
  capture.enable(true);
  const silence=new ArrayBuffer(2560);
  for(let i=0;i<1500;i++){
    socket.message(silence);await vi.advanceTimersByTimeAsync(80);
  }
  expect(packet).toHaveBeenCalledTimes(1500);expect(meter).toHaveBeenLastCalledWith(0);
  expect(problem).not.toHaveBeenCalled();expect(capture.isLive()).toBe(true);
  const voice=pcm16(Array(1280).fill(.25));socket.message(voice);
  expect(packet).toHaveBeenLastCalledWith(voice);await capture.close();
});
it('reports a capture backlog without interrupting the active session',async()=>{
  const problem=vi.fn(),{capture,socket}=await open(vi.fn(),vi.fn(),problem),gap=vi.fn();
  capture.onGap=gap;capture.enable(true);
  socket.message(JSON.stringify({type:'gap',message:'old audio skipped'}));
  expect(gap).toHaveBeenCalledWith('old audio skipped');expect(problem).not.toHaveBeenCalled();expect(capture.isLive()).toBe(true);
  await capture.close();
});
it('rejects permission failures and closes without switching to a microphone',async()=>{
  const capture=new SystemCapture(vi.fn(),vi.fn(),vi.fn());
  const opening=capture.open({kind:'system'},80);const rejected=expect(opening).rejects.toThrow('permission');
  Socket.instances[0].message(JSON.stringify({type:'error',message:'permission'}));await rejected;
  expect(Socket.instances[0].close).toHaveBeenCalledOnce();
});
it('reports a lost native connection and stops upload',async()=>{
  const packet=vi.fn(),problem=vi.fn(),{capture,socket}=await open(packet,vi.fn(),problem);
  capture.enable(true);socket.close();socket.message(pcm16(Array(1280).fill(.1)));
  expect(problem).toHaveBeenCalledOnce();expect(packet).not.toHaveBeenCalled();await capture.close();
});
it('times out native initialization and cleans up the connection',async()=>{
  const capture=new SystemCapture(vi.fn(),vi.fn(),vi.fn()),opening=capture.open({kind:'system'},80);
  const rejected=expect(opening).rejects.toThrow('超时');await vi.advanceTimersByTimeAsync(180000);await rejected;
  expect(Socket.instances[0].close).toHaveBeenCalledOnce();
});
