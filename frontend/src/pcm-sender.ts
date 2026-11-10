// One clock for microphone, native audio and switch silence. Never catch up by
// replaying a burst after a delayed browser callback.
export class PcmSender {
  private queue:{buffer:ArrayBuffer;at:number}[]=[];
  private bytes=0;
  private timer?:ReturnType<typeof setTimeout>;
  private nextAt=0;
  private lastGap=-Infinity;
  constructor(private send:(buffer:ArrayBuffer)=>boolean,private gap:()=>void,
    private clock:()=>number=()=>performance.now()){}
  push(buffer:ArrayBuffer){
    if(!buffer.byteLength||buffer.byteLength>2560||buffer.byteLength%2)return false;
    this.queue.push({buffer,at:this.clock()});this.bytes+=buffer.byteLength;
    let dropped=false;
    while(this.bytes>12800){this.bytes-=this.queue.shift()!.buffer.byteLength;dropped=true;}
    if(dropped)this.reportGap();
    if(this.timer===undefined)this.tick();
    return true;
  }
  clear(resetClock=false){
    clearTimeout(this.timer);this.timer=undefined;this.queue=[];this.bytes=0;
    if(resetClock)this.nextAt=0;
  }
  async drain(){
    const deadline=this.clock()+600;
    while(this.queue.length&&this.clock()<deadline){
      await new Promise<void>(resolve=>setTimeout(resolve,20));
    }
    if(this.queue.length){this.clear();this.reportGap();}
  }
  private reportGap(){
    const now=this.clock();
    if(now-this.lastGap>=1000){this.lastGap=now;this.gap();}
  }
  private tick=()=>{
    this.timer=undefined;
    const now=this.clock();let dropped=false;
    while(this.queue.length&&now-this.queue[0].at>500){
      this.bytes-=this.queue.shift()!.buffer.byteLength;dropped=true;
    }
    if(dropped)this.reportGap();
    if(!this.queue.length)return;
    if(now+0.1<this.nextAt){this.timer=setTimeout(this.tick,this.nextAt-now);return;}
    const {buffer}=this.queue.shift()!;this.bytes-=buffer.byteLength;
    const duration=buffer.byteLength/32,lateness=Math.max(0,now-this.nextAt);
    // Correct small timer overshoots instead of accumulating them forever.
    // Cap compensation at 10%; a long stall starts a fresh clock, never a burst.
    const correction=this.nextAt>0&&lateness<duration/2?Math.min(lateness,duration*.1):0;
    this.nextAt=now+duration-correction;
    if(!this.send(buffer)){this.clear();return;}
    if(this.queue.length)this.timer=setTimeout(this.tick,Math.max(0,this.nextAt-this.clock()));
  };
}
