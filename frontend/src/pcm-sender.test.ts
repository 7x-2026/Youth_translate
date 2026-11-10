import {afterEach,expect,it,vi} from 'vitest';
import {PcmSender} from './pcm-sender';
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
it('paces a burst at real-time speed and bounds the unsent backlog',()=>{
  vi.useFakeTimers();let now=0;const times:number[]=[],gap=vi.fn();
  const sender=new PcmSender(()=>{times.push(now);return true;},gap,()=>now);
  for(let i=0;i<100;i++)sender.push(new ArrayBuffer(2560));
  expect(times).toEqual([0]);expect(gap).toHaveBeenCalledOnce();
  for(let i=0;i<10;i++){now+=80;vi.advanceTimersByTime(80);}
  expect(times).toEqual([0,80,160,240,320,400]);sender.clear();
});
it('drops stale packets after a stalled callback instead of catching up',()=>{
  vi.useFakeTimers();let now=0;const send=vi.fn(()=>true),gap=vi.fn();
  const sender=new PcmSender(send,gap,()=>now);
  sender.push(new ArrayBuffer(2560));sender.push(new ArrayBuffer(2560));
  now=2000;vi.advanceTimersByTime(80);
  expect(send).toHaveBeenCalledOnce();expect(gap).toHaveBeenCalledOnce();
  sender.push(new ArrayBuffer(2560));expect(send).toHaveBeenCalledTimes(2);sender.clear();
});
it('clears switch silence and old-device audio before enabling a new source',()=>{
  vi.useFakeTimers();let now=0;const packets:ArrayBuffer[]=[];
  const sender=new PcmSender(packet=>{packets.push(packet);return true;},vi.fn(),()=>now);
  const old=new ArrayBuffer(2560),next=new ArrayBuffer(2560);
  sender.push(old);sender.push(old);sender.clear();sender.push(next);
  now=80;vi.advanceTimersByTime(80);expect(packets).toEqual([old,next]);sender.clear();
});
it('honours short packets without turning 40ms audio into 80ms audio',()=>{
  vi.useFakeTimers();let now=0;const send=vi.fn(()=>true);
  const sender=new PcmSender(send,vi.fn(),()=>now);
  sender.push(new ArrayBuffer(1280));sender.push(new ArrayBuffer(1280));
  now=39;vi.advanceTimersByTime(39);expect(send).toHaveBeenCalledOnce();
  now=40;vi.advanceTimersByTime(1);expect(send).toHaveBeenCalledTimes(2);sender.clear();
});
it('never uploads queued audio after stop or a failed transport',()=>{
  vi.useFakeTimers();let now=0;const send=vi.fn(()=>false);
  const sender=new PcmSender(send,vi.fn(),()=>now);
  sender.push(new ArrayBuffer(2560));sender.clear(true);now=1000;vi.advanceTimersByTime(1000);
  expect(send).toHaveBeenCalledOnce();expect(vi.getTimerCount()).toBe(0);
});
it('drains a normal end-of-session tail without flushing a burst',async()=>{
  vi.useFakeTimers();let now=0;const sent:ArrayBuffer[]=[];
  const sender=new PcmSender(packet=>{sent.push(packet);return true;},vi.fn(),()=>now);
  const packet=new ArrayBuffer(2560),tail=new ArrayBuffer(160);
  sender.push(packet);sender.push(tail);
  const drained=sender.drain();now=80;await vi.advanceTimersByTimeAsync(80);await drained;
  expect(sent).toEqual([packet,tail]);sender.clear();expect(vi.getTimerCount()).toBe(0);
});
it('does not accumulate 2ms timer jitter over two virtual hours',()=>{
  vi.useFakeTimers();vi.setSystemTime(0);
  const schedule=setTimeout;
  vi.stubGlobal('setTimeout',(callback:()=>void,delay:number)=>schedule(callback,delay+2));
  const gap=vi.fn();let sent=0;
  const sender=new PcmSender(()=>{sent++;return true;},gap,()=>Date.now());
  const packet=new ArrayBuffer(2560);
  // Two packets every 160ms represent a jittered 16kHz PCM stream. Small
  // callback delays must not turn into an ever-growing queue or dropped audio.
  for(let i=0;i<45000;i++){
    sender.push(packet);sender.push(packet);vi.advanceTimersByTime(160);
  }
  expect(sent).toBe(90000);expect(gap).not.toHaveBeenCalled();sender.clear();
  expect(vi.getTimerCount()).toBe(0);
});
it('bounds correction after a delayed callback instead of sending a catch-up burst',()=>{
  vi.useFakeTimers();let now=0;const times:number[]=[];
  const sender=new PcmSender(()=>{times.push(now);return true;},vi.fn(),()=>now);
  sender.push(new ArrayBuffer(2560));sender.push(new ArrayBuffer(2560));
  now=110;vi.advanceTimersByTime(80);sender.push(new ArrayBuffer(2560));
  now=181;vi.advanceTimersByTime(71);expect(times).toEqual([0,110]);
  now=182;vi.advanceTimersByTime(1);expect(times).toEqual([0,110,182]);sender.clear();
});
