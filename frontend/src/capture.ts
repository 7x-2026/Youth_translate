import workletUrl from './worklet.ts?worker&url';
import { isPhoneInput, preferredComputerInput } from './input';
export type ActiveInput = {label:string; warning:string};
export class Capture {
  stream?: MediaStream;
  context?: AudioContext;
  node?: AudioWorkletNode;
  private gate = false;
  private closing?: Promise<void>;
  private flushResolve?: ()=>void;
  constructor(private packet:(buffer:ArrayBuffer)=>void, private meter:(rms:number)=>void, private problem:(message:string)=>void) {}
  async open(deviceId:string, packetMs:number, roomMode=false):Promise<ActiveInput> {
    try {
      const constraints=(id:string):MediaStreamConstraints=>({audio:{deviceId:id?{exact:id}:undefined, channelCount:1, echoCancellation:!roomMode, noiseSuppression:!roomMode, autoGainControl:true},video:false});
      const list=await navigator.mediaDevices.enumerateDevices().catch(()=>[] as MediaDeviceInfo[]);
      let automatic:ReturnType<typeof preferredComputerInput>=deviceId?null:preferredComputerInput(list);
      this.stream=await navigator.mediaDevices.getUserMedia(constraints(deviceId||automatic?.device.deviceId||''));
      if(!deviceId && !automatic?.recognizedBuiltIn) {
        // Before the first permission grant device labels may be hidden. Resolve again
        // after opening a temporary stream, before connecting it to the cloud.
        const visible=await navigator.mediaDevices.enumerateDevices().catch(()=>[] as MediaDeviceInfo[]);
        const preferred=preferredComputerInput(visible);
        if(preferred){
          automatic=preferred;
          if(this.stream.getAudioTracks()[0]?.getSettings().deviceId!==preferred.device.deviceId){
            this.stream.getTracks().forEach(track=>track.stop());
            this.stream=undefined;
            this.stream=await navigator.mediaDevices.getUserMedia(constraints(preferred.device.deviceId));
          }
        }
      }
      const label=this.stream.getAudioTracks()[0]?.label||automatic?.device.label||'未命名麦克风';
      const warning=deviceId?'':automatic?.recognizedBuiltIn?'':isPhoneInput(label)?'未找到电脑麦克风，当前回退到手机输入；请在上方手动选择。':'未能识别电脑内置麦克风，已自动选择可用输入；请核对设备名称。';
      this.context=new AudioContext();
      await this.context.resume();
      await this.context.audioWorklet.addModule(workletUrl);
      this.node=new AudioWorkletNode(this.context,'classroom-capture',{processorOptions:{packetMs},outputChannelCount:[1]});
      this.node.port.onmessage=({data})=>{
        if(data.type==='audio') this.packet(data.buffer);
        if(data.type==='meter') this.meter(data.value);
        if(data.type==='flushed') this.flushResolve?.();
      };
      this.stream.getAudioTracks().forEach(track=>{
        track.onended=()=>this.problem('麦克风已断开，请重新选择设备并点击继续。');
        track.onmute=()=>this.problem('麦克风被系统中断，请检查设备并点击继续。');
      });
      this.context.onstatechange=()=>{
        if(this.context?.state==='suspended' && this.gate) this.context.resume().catch(()=>this.problem('音频采集已暂停，请点击继续。'));
      };
      this.context.createMediaStreamSource(this.stream).connect(this.node).connect(this.context.destination);
      return {label,warning};
    } catch(error) { await this.close(); throw error; }
  }
  enable(value:boolean) {
    if(value===this.gate) return;
    this.gate=value; this.node?.port.postMessage({type:'gate',enabled:value});
  }
  async close(flush=false) {
    if(this.closing)return this.closing;
    this.closing=this.teardown(flush);
    try{await this.closing;}finally{this.closing=undefined;}
  }
  private async teardown(flush:boolean) {
    if(flush && this.node && this.context?.state==='running') {
      await new Promise<void>(resolve=>{
        const timer=setTimeout(resolve,500);
        this.flushResolve=()=>{clearTimeout(timer);resolve();};
        this.node!.port.postMessage({type:'flush'});
      });
    }
    this.gate=false;
    this.stream?.getTracks().forEach(track=>{track.onended=null;track.onmute=null;track.stop();});
    this.node?.disconnect(); this.node?.port.close();
    if(this.context) { this.context.onstatechange=null; try{await this.context.close();}catch{/* Already closed by an interruption. */} }
    this.node=undefined;this.stream=undefined;this.context=undefined;
  }
}
