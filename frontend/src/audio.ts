// Stateful causal low-pass FIR plus interpolation. No state is reset at packet boundaries.
export class Resampler {
  private taps: Float64Array;
  private ring: Float64Array;
  private cursor = 0;
  private index = -1;
  private outputCount = 0;
  private previous = 0;
  private ratio: number;
  constructor(public inputRate: number, public outputRate = 16000) {
    if (inputRate < outputRate || !Number.isFinite(inputRate)) throw new Error('不支持此采样率');
    this.ratio = inputRate / outputRate;
    const size = 95, cutoff = Math.min(.45, .45 / this.ratio);
    this.taps = new Float64Array(size); this.ring = new Float64Array(size);
    let sum = 0;
    for (let i=0; i<size; i++) {
      const x=i-(size-1)/2;
      const sinc=x===0 ? 2*cutoff : Math.sin(2*Math.PI*cutoff*x)/(Math.PI*x);
      const window=.42-.5*Math.cos(2*Math.PI*i/(size-1))+.08*Math.cos(4*Math.PI*i/(size-1));
      sum += this.taps[i] = sinc*window;
    }
    for (let i=0; i<size; i++) this.taps[i] /= sum;
  }
  push(input: Float32Array): number[] {
    const out: number[] = [];
    for (const sample of input) {
      this.ring[this.cursor] = Number.isFinite(sample) ? sample : 0;
      let filtered=0;
      for (let k=0; k<this.taps.length; k++) filtered += this.taps[k]*this.ring[(this.cursor-k+this.ring.length)%this.ring.length];
      this.cursor = (this.cursor+1)%this.ring.length; this.index++;
      let position = (this.outputCount+1)*this.ratio-1;
      while (position <= this.index+1e-8) {
        const fraction = Math.max(0, Math.min(1, position-(this.index-1)));
        out.push(this.previous+(filtered-this.previous)*fraction);
        this.outputCount++;
        position = (this.outputCount+1)*this.ratio-1;
      }
      this.previous = filtered;
    }
    return out;
  }
}
export function mixMono(channels: Float32Array[]): Float32Array {
  if (!channels.length) return new Float32Array();
  const out = new Float32Array(channels[0].length);
  for (const channel of channels) for (let i=0;i<out.length;i++) out[i] += (channel[i]??0)/channels.length;
  return out;
}
export class InputLevel {
  private power = 0;
  private count = 0;
  constructor(private windowSamples: number) {}
  push(samples: Float32Array): number | null {
    for (const sample of samples) { this.power += sample * sample; this.count++; }
    if (this.count < this.windowSamples) return null;
    const rms = Math.sqrt(this.power / this.count);
    this.power = 0; this.count = 0;
    return rms;
  }
  reset() { this.power = 0; this.count = 0; }
}
export function displayLevel(rms: number): number {
  if (!Number.isFinite(rms) || rms <= 0) return 0;
  return Math.max(0, Math.min(1, (20 * Math.log10(rms) + 60) / 50));
}
export function pcm16(samples: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length*2), view = new DataView(buffer);
  samples.forEach((sample,i)=>{
    const value = Number.isFinite(sample) ? Math.max(-1,Math.min(1,sample)) : 0;
    view.setInt16(i*2, Math.round(value*(value<0?32768:32767)), true);
  });
  return buffer;
}
export class Packetizer {
  private pending: number[] = [];
  constructor(public size: number) {}
  push(samples: number[]): ArrayBuffer[] {
    this.pending.push(...samples);
    const packets=[];
    while(this.pending.length>=this.size) packets.push(pcm16(this.pending.splice(0,this.size)));
    return packets;
  }
  flush(): ArrayBuffer | null {
    if (!this.pending.length) return null;
    const buffer=pcm16(this.pending); this.pending=[]; return buffer;
  }
}
