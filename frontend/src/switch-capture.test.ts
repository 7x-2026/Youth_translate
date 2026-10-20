import { afterEach, expect, it, vi } from 'vitest';
import { replaceCapture, type SwitchableCapture } from './switch-capture';

const source={kind:'system' as const,deviceId:'headphones'};
function device():SwitchableCapture {
  return {open:vi.fn(async()=>({label:'Headphones',warning:''})),close:vi.fn(async()=>{}),isLive:vi.fn(()=>true)};
}
function deferred<T>(){
  let resolve!:(value:T)=>void;
  const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};
}
function setup(){
  vi.useFakeTimers();
  const controller=new AbortController(),previous=device(),next=device(),silence=vi.fn(),ready=vi.fn();
  return {controller,previous,next,silence,ready,options:{previous,next,source,packetMs:40,roomMode:false,signal:controller.signal,silence,ready}};
}
afterEach(()=>vi.useRealTimers());

it('waits for the old native endpoint to release before opening the next',async()=>{
  const {previous,next,ready,options}=setup(),release=deferred<void>();
  vi.mocked(previous.close).mockReturnValue(release.promise);
  const task=replaceCapture(options);
  expect(next.open).not.toHaveBeenCalled();
  release.resolve();await task;
  expect(next.open).toHaveBeenCalledWith(source,40,false);
  expect(ready).toHaveBeenCalledWith({label:'Headphones',warning:''});
  expect(next.close).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it('keeps sending PCM silence throughout a permission wait longer than the cloud timeout',async()=>{
  const {next,silence,ready,options}=setup(),opened=deferred<{label:string;warning:string}>();
  vi.mocked(next.open).mockReturnValue(opened.promise);
  const task=replaceCapture(options);await vi.advanceTimersByTimeAsync(12000);
  expect(ready).not.toHaveBeenCalled();expect(silence).toHaveBeenCalledTimes(151);
  for(const [packet] of silence.mock.calls){expect(packet.byteLength).toBe(2560);expect(new Uint8Array(packet).every(x=>x===0)).toBe(true);}
  opened.resolve({label:'New output',warning:''});await task;
  const count=silence.mock.calls.length;await vi.advanceTimersByTimeAsync(1000);
  expect(silence).toHaveBeenCalledTimes(count);expect(vi.getTimerCount()).toBe(0);
});

it('closes a failed replacement and stops silence instead of claiming success',async()=>{
  const {next,ready,options}=setup();vi.mocked(next.open).mockRejectedValue(Error('permission denied'));
  await expect(replaceCapture(options)).rejects.toThrow('permission denied');
  expect(next.close).toHaveBeenCalledOnce();expect(ready).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it('does not accept a disconnected replacement',async()=>{
  const {next,ready,options}=setup();vi.mocked(next.isLive).mockReturnValue(false);
  await expect(replaceCapture(options)).rejects.toThrow('新音频输入已中断');
  expect(next.close).toHaveBeenCalledOnce();expect(ready).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it('stops uploading immediately on cancellation and closes a microphone that opens late',async()=>{
  const {next,controller,silence,ready,options}=setup(),opened=deferred<{label:string;warning:string}>();
  vi.mocked(next.open).mockReturnValue(opened.promise);
  const task=replaceCapture(options);const rejected=expect(task).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(160);controller.abort();const count=silence.mock.calls.length;
  await vi.advanceTimersByTimeAsync(12000);expect(silence).toHaveBeenCalledTimes(count);
  opened.resolve({label:'Late microphone',warning:''});await rejected;
  expect(next.close).toHaveBeenCalledTimes(2);expect(ready).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});

it('cancels while releasing the old device without opening a new one',async()=>{
  const {previous,next,controller,options}=setup(),released=deferred<void>();
  vi.mocked(previous.close).mockReturnValue(released.promise);
  const task=replaceCapture(options);const rejected=expect(task).rejects.toThrow();
  controller.abort();released.resolve();await rejected;
  expect(next.open).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});
