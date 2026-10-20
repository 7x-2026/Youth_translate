export type Status = {type:'status';state:string;detail?:string;classId?:string;sessionEpoch?:number;gap?:boolean};
export class RelayClient {
  socket?: WebSocket;
  wanted=false;
  classId=''; epoch=0;
  private retryTimer?: ReturnType<typeof setTimeout>;
  private heartbeatTimer?: ReturnType<typeof setInterval>;
  private attempt=0;
  private ack=0;
  private mode='auto';
  private generation=0;
  private remotePaused=false;
  private preparing=false;
  private prepareCloud=false;
  constructor(private receive:(message:any)=>void, private status:(status:Status)=>void) {}
  // Open transport while the device initializes. A supporting backend may also
  // warm the cloud socket; neither StartSession nor audio is sent until start().
  prepare(cloud=false){
    if(this.wanted)return;
    if(this.preparing)return;
    this.preparing=true;this.prepareCloud=cloud;
    if(this.socket?.readyState===WebSocket.OPEN){if(cloud)this.send({type:'prepare'});return;}
    if(this.socket?.readyState===WebSocket.CONNECTING)return;
    this.connect();
  }
  cancelPrepare(){if(!this.wanted)this.dispose();}
  start(mode:string, fresh:boolean) {
    this.wanted=true;this.preparing=false;this.mode=mode;
    if(fresh){this.classId=crypto.randomUUID();this.epoch=0;this.attempt=0;}
    clearTimeout(this.retryTimer);
    if(this.socket?.readyState===WebSocket.OPEN) {
      this.send({type:!fresh&&this.remotePaused?'resume':'start',mode,classId:this.classId,sessionEpoch:this.epoch});
      this.remotePaused=false;
    } else if(this.socket?.readyState!==WebSocket.CONNECTING)this.connect();
  }
  private connect() {
    const generation=++this.generation;
    this.status({type:'status',state:this.attempt?'recovering':'connecting',detail:'正在连接本机服务…'});
    const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/translate`);
    this.socket=ws;
    ws.binaryType='arraybuffer';
    ws.onopen=()=>{
      if(generation!==this.generation||(!this.wanted&&!this.preparing)){ws.close();return;}
      this.ack=Date.now();this.remotePaused=false;
      this.send({type:'heartbeat'});
      if(this.wanted)this.send({type:'start',mode:this.mode,classId:this.classId,sessionEpoch:this.epoch});
      else if(this.prepareCloud)this.send({type:'prepare'});
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer=setInterval(()=>{
        if(Date.now()-this.ack>=30000) ws.close(4000,'heartbeat timeout');
        else this.send({type:'heartbeat'});
      },10000);
    };
    ws.onmessage=({data})=>{
      if(generation!==this.generation || typeof data!=='string')return;
      let msg;try{msg=JSON.parse(data);}catch{return;}
      if(msg.type==='heartbeat_ack'){this.ack=Date.now();return;}
      if(msg.type==='status') {
        if(this.preparing&&!this.wanted)return;
        if(msg.classId && msg.classId!==this.classId)return;
        if(msg.sessionEpoch!==undefined && msg.sessionEpoch<this.epoch)return;
        this.epoch=Math.max(this.epoch,msg.sessionEpoch??0);
        if(msg.state==='running')this.attempt=0;
        this.remotePaused=msg.state==='paused';
        this.status(msg);
      } else {
        if(msg.type==='error' && !msg.retryable) {this.wanted=false;clearTimeout(this.retryTimer);}
        this.receive(msg);
      }
    };
    ws.onclose=()=>{
      if(generation!==this.generation)return;
      clearInterval(this.heartbeatTimer);
      if(this.socket===ws)this.socket=undefined;
      if(this.wanted) {
        this.status({type:'status',state:'recovering',detail:'本机连接中断，正在恢复；期间内容可能缺失。',gap:true});
        const delay=Math.min(10000,500*2**Math.min(this.attempt++,5))*(.85+Math.random()*.3);
        this.retryTimer=setTimeout(()=>{if(this.wanted)this.connect();},Math.min(delay,10000));
      }
    };
  }
  send(message:object) {if(this.socket?.readyState===WebSocket.OPEN)this.socket.send(JSON.stringify(message));}
  audio(buffer:ArrayBuffer) {
    const ws=this.socket;
    if(!this.wanted||ws?.readyState!==WebSocket.OPEN)return false;
    if(ws.bufferedAmount+buffer.byteLength>16000) {
      this.status({type:'status',state:'recovering',detail:'音频积压超过上限，重建连接并跳过积压内容。',gap:true});
      ws.close(4001,'audio backlog');return false;
    }
    ws.send(buffer);
    return true;
  }
  end(pause:boolean) {
    this.wanted=false;this.preparing=false;clearTimeout(this.retryTimer);
    if(this.socket?.readyState===WebSocket.OPEN) this.send({type:pause?'pause':'stop'});
    else this.status({type:'status',state:pause?'paused':'stopped',detail:pause?'已暂停':'已结束'});
  }
  dispose() {
    this.wanted=false;this.preparing=false;this.generation++;
    clearTimeout(this.retryTimer);clearInterval(this.heartbeatTimer);this.socket?.close();
    this.socket=undefined;
  }
}
