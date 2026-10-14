import {it,expect,vi,afterEach} from 'vitest';
let processor:any;
class Port {onmessage?:({data}:any)=>void;messages:any[]=[];postMessage(msg:any,transfers?:ArrayBuffer[]){this.messages.push({msg,transfers});}}
class Base {port=new Port();}
afterEach(()=>vi.unstubAllGlobals());
it('worklet accepts variable blocks, sends real silence and flushes the short tail',async()=>{
  vi.stubGlobal('sampleRate',48000);vi.stubGlobal('AudioWorkletProcessor',Base);vi.stubGlobal('registerProcessor',(_name:string,value:any)=>{processor=value;});
  await import('./worklet');
  const p=new processor({processorOptions:{packetMs:80}});
  const output=new Float32Array(77).fill(1);
  p.process([[new Float32Array(77)]],[[output]]);
  expect(output.every(x=>x===0)).toBe(true);expect(p.port.messages).toHaveLength(0);
  p.port.onmessage({data:{type:'gate',enabled:true}});
  let total=0;
  for(let i=0;i<61;i++){const size=i%2?77:91;total+=size;p.process([[new Float32Array(size)]],[[output]]);}
  p.port.onmessage({data:{type:'flush'}});
  const packets=p.port.messages.filter((e:any)=>e.msg.type==='audio');
  expect(packets.reduce((sum:number,e:any)=>sum+e.msg.buffer.byteLength,0)).toBe(Math.floor(total/3)*2);
  expect(packets[0].msg.buffer.byteLength).toBe(2560);
  expect(packets.every((e:any)=>new Uint8Array(e.msg.buffer).every(x=>x===0))).toBe(true);
  expect(packets.every((e:any)=>e.transfers[0]===e.msg.buffer)).toBe(true);
  expect(p.port.messages.at(-1).msg.type).toBe('flushed');
  const before=p.port.messages.length;p.process([[new Float32Array(91)]],[[output]]);expect(p.port.messages).toHaveLength(before);
});
