import {it,expect,vi,afterEach} from 'vitest';
import {RelayClient} from './connection';
class Socket {
  static CONNECTING=0;static OPEN=1;static instances:Socket[]=[];
  readyState=0;bufferedAmount=0;binaryType='';sent:any[]=[];
  onopen?:()=>void;onclose?:()=>void;onmessage?:(e:{data:string})=>void;
  constructor(public url:string){Socket.instances.push(this);}
  send(data:any){this.sent.push(data);}close(){this.readyState=3;this.onclose?.();}
  open(){this.readyState=1;this.onopen?.();}message(data:object){this.onmessage?.({data:JSON.stringify(data)});}
}
function setup(start=true){vi.useFakeTimers();Socket.instances=[];vi.stubGlobal('WebSocket',Socket);vi.stubGlobal('location',{protocol:'http:',host:'localhost:8765'});vi.stubGlobal('crypto',{randomUUID:()=> 'class'});const receive=vi.fn(),status=vi.fn();const client=new RelayClient(receive,status);if(start)client.start('auto',true);return{client,receive,status,get ws(){return Socket.instances[0];}};}
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
it('application heartbeat expires at 30 seconds',()=>{
  const {client,ws}=setup();ws.open();vi.advanceTimersByTime(30000);expect(ws.readyState).toBe(3);expect(ws.sent.some(x=>typeof x==='string'&&JSON.parse(x).type==='heartbeat')).toBe(true);client.dispose();
});
it('pause cancels reconnect and refuses subsequent audio',()=>{
  const {client,ws}=setup();ws.open();ws.close();client.end(true);vi.advanceTimersByTime(15000);expect(Socket.instances).toHaveLength(1);client.audio(new ArrayBuffer(2560));expect(ws.sent.every(x=>typeof x==='string')).toBe(true);client.dispose();
});
it('reconnect preserves class and increases from known epoch',()=>{
  const {client,ws}=setup();ws.open();ws.message({type:'status',state:'running',classId:'class',sessionEpoch:3});ws.close();vi.advanceTimersByTime(600);const fresh=Socket.instances[1];fresh.open();expect(JSON.parse(fresh.sent[1]).sessionEpoch).toBe(3);expect(JSON.parse(fresh.sent[1]).classId).toBe('class');client.dispose();
});
it('bounded browser buffer recreates connection instead of replay',()=>{
  const {client,ws,status}=setup();ws.open();ws.bufferedAmount=15000;client.audio(new ArrayBuffer(2560));expect(ws.readyState).toBe(3);expect(status.mock.calls.some(c=>c[0].gap)).toBe(true);client.dispose();
});
it('stop before socket open does not start a billed session',()=>{
  const {client,ws}=setup();client.end(false);ws.open();expect(ws.sent).toHaveLength(0);client.dispose();
});
it('fatal errors cancel retries',()=>{
  const {client,ws}=setup();ws.open();ws.message({type:'error',retryable:false});ws.close();vi.advanceTimersByTime(30000);expect(Socket.instances).toHaveLength(1);client.dispose();
});
it('starting a fresh class after a paused socket uses start instead of resume',()=>{
  const {client,ws}=setup();ws.open();ws.message({type:'status',state:'paused',classId:'class',sessionEpoch:1});client.start('auto',true);expect(JSON.parse(ws.sent.at(-1)).type).toBe('start');client.dispose();
});
it('reports whether a PCM packet was handed to the local websocket',()=>{
  const {client,ws}=setup(),packet=new ArrayBuffer(2560);
  expect(client.audio(packet)).toBe(false);
  ws.open();expect(client.audio(packet)).toBe(true);expect(ws.sent.at(-1)).toBe(packet);
  ws.bufferedAmount=15000;expect(client.audio(packet)).toBe(false);
  client.end(true);expect(client.audio(packet)).toBe(false);client.dispose();
});
it('prepares only localhost transport and refuses audio before the device is ready',()=>{
  const {client,status}=setup(false);client.prepare();client.prepare();
  expect(Socket.instances).toHaveLength(1);const ws=Socket.instances[0];ws.open();
  expect(ws.sent.map(x=>JSON.parse(x).type)).toEqual(['heartbeat']);
  expect(client.audio(new ArrayBuffer(2560))).toBe(false);expect(client.wanted).toBe(false);
  status.mockClear();ws.message({type:'status',state:'idle',classId:'server-id',sessionEpoch:0});
  expect(status).not.toHaveBeenCalled();client.dispose();
});
it('starts immediately on the prepared socket after the device becomes ready',()=>{
  const {client}=setup(false);client.prepare();const ws=Socket.instances[0];ws.open();
  vi.advanceTimersByTime(12000);
  expect(ws.sent.every(x=>JSON.parse(x).type==='heartbeat')).toBe(true);
  client.start('en-zh',true);
  expect(Socket.instances).toHaveLength(1);
  expect(JSON.parse(ws.sent.at(-1))).toMatchObject({type:'start',mode:'en-zh',classId:'class'});
  client.dispose();expect(vi.getTimerCount()).toBe(0);
});
it('reuses a connecting socket when the device is ready before the network',()=>{
  const {client}=setup(false);client.prepare();client.start('zh-en',true);
  expect(Socket.instances).toHaveLength(1);const ws=Socket.instances[0];ws.open();
  expect(ws.sent.map(x=>JSON.parse(x).type)).toEqual(['heartbeat','start']);
  expect(JSON.parse(ws.sent.at(-1)).mode).toBe('zh-en');client.dispose();
});
it('cancels preparation on failed initialization and ignores a late socket open',()=>{
  const {client}=setup(false);client.prepare();const stale=Socket.instances[0];
  client.cancelPrepare();stale.open();
  expect(stale.sent).toHaveLength(0);expect(vi.getTimerCount()).toBe(0);
  client.prepare();const next=Socket.instances[1];next.open();client.start('auto',true);
  expect(JSON.parse(next.sent.at(-1)).type).toBe('start');client.dispose();
});
it('does not keep retrying an unused prepared connection',()=>{
  const {client}=setup(false);client.prepare();const ws=Socket.instances[0];ws.open();ws.close();
  vi.advanceTimersByTime(20000);expect(Socket.instances).toHaveLength(1);
  client.start('auto',true);expect(Socket.instances).toHaveLength(2);client.dispose();
});
it('requests a cloud transport warmup only when the backend advertises support',()=>{
  const {client}=setup(false);client.prepare(true);const ws=Socket.instances[0];ws.open();
  expect(ws.sent.map(x=>JSON.parse(x).type)).toEqual(['heartbeat','prepare']);
  expect(ws.sent.some(x=>JSON.parse(x).type==='start')).toBe(false);
  client.start('auto',true);expect(JSON.parse(ws.sent.at(-1)).type).toBe('start');client.dispose();
});
it('does not create duplicate warmups on a paused open socket',()=>{
  const {client,ws}=setup();ws.open();client.end(true);
  client.prepare(true);client.prepare(true);
  expect(ws.sent.filter(x=>JSON.parse(x).type==='prepare')).toHaveLength(1);
  client.cancelPrepare();expect(ws.readyState).toBe(3);
});
