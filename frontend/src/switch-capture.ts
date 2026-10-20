import type { ActiveInput } from './capture';
import type { AudioSource } from './input';

export interface SwitchableCapture {
  open(source:AudioSource,packetMs:number,roomMode:boolean):Promise<ActiveInput>;
  close(flush?:boolean):Promise<void>;
  isLive():boolean;
}

// Only the capture changes: the caller retains its cloud session and subtitles.
export async function replaceCapture(options:{
  previous?:SwitchableCapture;next:SwitchableCapture;source:AudioSource;
  packetMs:number;roomMode:boolean;signal:AbortSignal;
  silence:(packet:ArrayBuffer)=>void;ready:(input:ActiveInput)=>void;
}){
  const {previous,next,signal}=options;
  const silence=()=>{if(!signal.aborted)options.silence(new ArrayBuffer(2560));};
  let timer:ReturnType<typeof setInterval>|undefined;
  const cancel=()=>{clearInterval(timer);void next.close();};
  signal.addEventListener('abort',cancel,{once:true});
  try{
    signal.throwIfAborted();
    silence();timer=setInterval(silence,80);
    // Release the native tap before opening another output endpoint.
    await previous?.close();signal.throwIfAborted();
    const input=await next.open(options.source,options.packetMs,options.roomMode);
    signal.throwIfAborted();
    if(!next.isLive())throw Error('新音频输入已中断，请检查设备后点击继续。');
    options.ready(input);
  }catch(error){await next.close();throw error;}
  finally{clearInterval(timer);signal.removeEventListener('abort',cancel);}
}
