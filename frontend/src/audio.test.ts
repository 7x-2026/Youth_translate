import { describe, it, expect } from 'vitest';
import { Resampler, pcm16, Packetizer, mixMono, InputLevel, displayLevel } from './audio';
const signal=(rate:number,frequency:number,seconds=1)=>Float32Array.from({length:rate*seconds},(_,i)=>.7*Math.sin(2*Math.PI*frequency*i/rate));
const rms=(samples:number[])=>Math.sqrt(samples.reduce((s,x)=>s+x*x,0)/samples.length);
describe('continuous audio',()=>{
  for(const rate of [44100,48000]){
    it(`${rate}Hz sample count and block invariance`,()=>{
      const audio=signal(rate,1000),whole=new Resampler(rate).push(audio),converter=new Resampler(rate),parts:number[]=[];
      for(let i=0;i<audio.length;i+=173)parts.push(...converter.push(audio.subarray(i,i+173)));
      expect(whole).toHaveLength(16000);expect(parts).toEqual(whole);
      expect(rms(whole.slice(200))).toBeGreaterThan(.45);
      expect(rms(whole.slice(200))).toBeLessThan(.51);
    });
    it(`${rate}Hz suppresses out-of-band alias`,()=>{
      const high=new Resampler(rate).push(signal(rate,12000));
      expect(rms(high.slice(200))).toBeLessThan(.005);
    });
    it(`${rate}Hz many boundaries maintain duration`,()=>{
      const converter=new Resampler(rate);let count=0;
      const audio=signal(rate,500,3);
      for(let i=0;i<audio.length;i+=127)count+=converter.push(audio.subarray(i,i+127)).length;
      expect(count).toBe(48000);
    });
  }
  it('PCM16 signed little endian, clipping and non-finite handling',()=>{
    const v=new DataView(pcm16([-2,-1,-.5,0,.5,1,2,NaN]));
    expect(Array.from({length:8},(_,i)=>v.getInt16(i*2,true))).toEqual([-32768,-32768,-16384,0,16384,32767,32767,0]);
    expect(v.getUint8(10)).toBe(255);expect(v.getUint8(11)).toBe(127);
  });
  for(const size of [640,1280])it(`packet length ${size} and short tail`,()=>{
    const p=new Packetizer(size);const packets=p.push(Array(size*3+27).fill(.2));
    expect(packets.map(x=>x.byteLength)).toEqual([size*2,size*2,size*2]);expect(p.flush()?.byteLength).toBe(54);expect(p.flush()).toBe(null);
  });
  it('mixes actual channel lengths',()=>expect(Array.from(mixMono([new Float32Array([1,-1,.5]),new Float32Array([-1,1,.5])]))).toEqual([0,0,.5]));
  it('meters the whole time window even when its last block is silent',()=>{
    const level=new InputLevel(4);
    expect(level.push(new Float32Array([.4,.4]))).toBe(null);
    expect(level.push(new Float32Array([0,0]))).toBeCloseTo(Math.sqrt(.08));
    expect(level.push(new Float32Array(4))).toBe(0);
    expect(displayLevel(.01)).toBeCloseTo(.4);
    expect(displayLevel(0)).toBe(0);
  });
});
