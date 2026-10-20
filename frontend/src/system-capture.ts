import { InputLevel } from './audio';
import type { ActiveInput } from './capture';
import type { AudioSource } from './input';

// Native OS audio arrives as PCM16 over localhost. No browser media permissions,
// AudioContext, playback, screen capture, or changes to the meeting's devices.
export class SystemCapture {
  socket?:WebSocket;
  onGap?:(message:string)=>void;
  private ready=false;
  private gate=false;
  private closing?:Promise<void>;
  private heartbeat?:ReturnType<typeof setInterval>;
  private pending:Uint8Array<ArrayBuffer>=new Uint8Array();
  private packetBytes=2560;
  private level=new InputLevel(1600);
  private cancelOpen?:(error:Error)=>void;
  constructor(private packet:(buffer:ArrayBuffer)=>void,private meter:(rms:number)=>void,private problem:(message:string)=>void){}
  async open(source:AudioSource,packetMs:number,_roomMode=false):Promise<ActiveInput>{
    if(source.kind!=='system')throw Error('请选择电脑内部音频。');
    this.packetBytes=packetMs===40?1280:2560;
    const query=source.deviceId?`?device=${encodeURIComponent(source.deviceId)}`:'';
    const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/system-audio${query}`);
    ws.binaryType='arraybuffer';this.socket=ws;
    try{
      return await new Promise<ActiveInput>((resolve,reject)=>{
        const timeout=setTimeout(()=>fail('系统音频启动超时，请检查权限并重试。'),180000);
        this.cancelOpen=error=>{clearTimeout(timeout);reject(error);};
        const fail=(message:string)=>{
          const wasReady=this.ready;this.ready=false;this.enable(false);
          clearTimeout(timeout);reject(Error(message));
          if(wasReady)this.problem(message);
        };
        ws.onopen=()=>{this.heartbeat=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send('heartbeat');},10000);};
        ws.onmessage=({data})=>{
          if(this.socket!==ws)return;
          if(typeof data==='string'){
            let event;try{event=JSON.parse(data);}catch{fail('本机音频消息格式错误。');return;}
            if(event.type==='gap'){
              this.pending=new Uint8Array();this.level.reset();
              this.onGap?.(event.message||'本机音频积压，字幕可能存在缺口。');return;
            }
            if(event.type==='error'){fail(event.message||'本机音频采集失败。');return;}
            if(event.type==='ready'&&event.sampleRate===16000){
              this.ready=true;clearTimeout(timeout);this.cancelOpen=undefined;
              resolve({label:event.label||'电脑内部音频',warning:''});
            }
          }else if(data instanceof ArrayBuffer&&this.ready&&this.gate){
            const joined=new Uint8Array(this.pending.length+data.byteLength);
            joined.set(this.pending);joined.set(new Uint8Array(data),this.pending.length);this.pending=joined;
            while(this.pending.length>=this.packetBytes){
              const packet=this.pending.slice(0,this.packetBytes);this.pending=this.pending.slice(this.packetBytes);
              const view=new DataView(packet.buffer),samples=new Float32Array(packet.length/2);
              for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(i*2,true)/32768;
              const rms=this.level.push(samples);if(rms!==null)this.meter(rms);
              this.packet(packet.buffer);
            }
          }
        };
        ws.onerror=()=>fail('无法连接本机音频采集服务，请检查后台是否运行。');
        ws.onclose=()=>{clearInterval(this.heartbeat);fail('内部音频采集已停止，请检查权限或输出设备后点击继续。');};
      });
    }catch(error){await this.close();throw error;}
  }
  isLive(){return this.ready&&this.socket?.readyState===WebSocket.OPEN;}
  enable(value:boolean){if(value!==this.gate){this.gate=value;this.pending=new Uint8Array();this.level.reset();}}
  async close(flush=false){
    if(this.closing)return this.closing;
    if(flush&&this.gate&&this.pending.length>=2){
      this.packet(this.pending.slice(0,this.pending.length-this.pending.length%2).buffer);
    }
    this.ready=false;this.enable(false);clearInterval(this.heartbeat);
    this.cancelOpen?.(Error('音频采集已取消。'));this.cancelOpen=undefined;
    const ws=this.socket;this.socket=undefined;
    if(!ws)return;
    ws.onmessage=null;ws.onerror=null;ws.onopen=null;ws.onclose=null;
    this.closing=new Promise<void>(resolve=>{
      if(ws.readyState===WebSocket.CLOSED){resolve();return;}
      const timer=setTimeout(()=>{ws.close();resolve();},2500);
      ws.addEventListener('close',()=>{clearTimeout(timer);resolve();},{once:true});
      // The server releases its native tap before closing the socket. Waiting for
      // that acknowledgement prevents a quick resume racing the old capture.
      if(ws.readyState===WebSocket.OPEN)ws.send('stop');else ws.close();
    });
    try{await this.closing;}finally{this.closing=undefined;}
  }
}
