// Activity is evidence of sound, not a speech detector. Never restart a cloud
// session just because music/noise has energy but produces no subtitles.
export class AudioProgress {
  private since=0;
  private lastInput?:number;
  private lastSent?:number;
  private lastSound?:number;
  private soundMs=0;
  reset(now=performance.now()){
    this.since=now;this.lastInput=undefined;this.lastSent=undefined;
    this.lastSound=undefined;this.soundMs=0;
  }
  packet(buffer:ArrayBuffer,sent:boolean,now=performance.now()){
    this.lastInput=now;
    if(!sent)return;
    this.lastSent=now;
    const samples=new DataView(buffer);let power=0;
    for(let i=0;i+1<buffer.byteLength;i+=2){const sample=samples.getInt16(i,true);power+=sample*sample;}
    if(buffer.byteLength&&power/(buffer.byteLength/2)>10000){
      this.lastSound=now;this.soundMs+=buffer.byteLength/32;
    }
  }
  subtitle(now=performance.now()){this.since=now;this.soundMs=0;}
  hint(now=performance.now()){
    if(now-this.since<5000)return '';
    if(this.lastInput===undefined||now-this.lastInput>5000)return '暂未收到采集音频，请检查设备连接。';
    if(this.lastSent===undefined||now-this.lastSent>5000)return '已收到采集音频，暂未能上传至本机翻译服务。';
    if(now-this.since>=30000&&this.soundMs>=3000&&this.lastSound!==undefined&&now-this.lastSound<5000)
      return '音频持续发送至本机服务，云端暂未返回字幕；尚不能确定是识别延迟还是服务异常。';
    return '';
  }
}
