import { Resampler, Packetizer, mixMono, InputLevel } from './audio';
declare const sampleRate: number;
declare function registerProcessor(name:string, processor: typeof AudioWorkletProcessor): void;
declare class AudioWorkletProcessor { port: MessagePort; constructor(); }
class CaptureProcessor extends AudioWorkletProcessor {
  private converter = new Resampler(sampleRate);
  private packets: Packetizer;
  private enabled = false;
  private level = new InputLevel(sampleRate / 10);
  constructor(options: {processorOptions?: {packetMs?:number}} = {}) {
    super(); this.packets = new Packetizer(options.processorOptions?.packetMs===40?640:1280);
    this.port.onmessage = ({data})=>{
      if(data.type==='gate') {
        this.enabled=data.enabled;
        this.converter=new Resampler(sampleRate);
        this.packets=new Packetizer(options.processorOptions?.packetMs===40?640:1280);
        this.level.reset();
      }
      if(data.type==='flush') {
        const tail=this.packets.flush();
        if(tail) this.port.postMessage({type:'audio',buffer:tail},[tail]);
        this.enabled=false; this.port.postMessage({type:'flushed'});
      }
    };
  }
  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    // Connected to a zero-filled output solely to keep the graph running. Never monitor microphone audio.
    for(const output of outputs) for(const channel of output) channel.fill(0);
    if(!this.enabled || !inputs[0]?.length) return true;
    const mono=mixMono(inputs[0]);
    for(const buffer of this.packets.push(this.converter.push(mono))) this.port.postMessage({type:'audio',buffer},[buffer]);
    const rms=this.level.push(mono);
    if(rms!==null) this.port.postMessage({type:'meter',value:rms});
    return true;
  }
}
registerProcessor('classroom-capture', CaptureProcessor);
