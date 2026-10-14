import {it,expect,vi,afterEach} from 'vitest';
import {RelayClient} from './connection';
class Socket {
  static OPEN=1;static instances:Socket[]=[];
  readyState=0;bufferedAmount=0;binaryType='';sent:any[]=[];
  onopen?:()=>void;onclose?:()=>void;onmessage?:(e:{data:string})=>void;
  constructor(public url:string){Socket.instances.push(this);}
  send(data:any){this.sent.push(data);}close(){this.readyState=3;this.onclose?.();}
  open(){this.readyState=1;this.onopen?.();}message(data:object){this.onmessage?.({data:JSON.stringify(data)});}
}
function setup(){vi.useFakeTimers();Socket.instances=[];vi.stubGlobal('WebSocket',Socket);vi.stubGlobal('location',{protocol:'http:',host:'localhost:8765'});vi.stubGlobal('crypto',{randomUUID:()=> 'class'});const receive=vi.fn(),status=vi.fn();const client=new RelayClient(receive,status);client.start('auto',true);return{client,receive,status,ws:Socket.instances[0]};}
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
