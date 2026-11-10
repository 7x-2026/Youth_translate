import type {Entry} from './subtitles';

export type TranslationView={current?:Entry;previous?:Entry};
const MIN_READ_MS=1200,FINAL_GRACE_MS=400,MAX_EXTRA_DELAY_MS=1000;
const identity=(entry:Entry)=>`${entry.classId}/${entry.sessionEpoch}/${entry.segmentId}`;

// Presentation only. Raw subtitles, persistence and export stay immediate.
// Keep one latest pending sentence, so a burst cannot create a reading backlog.
export class ReadableTranslation {
  private session='';
  private view:TranslationView={};
  private pending?:Entry;
  private pendingAt=0;
  private shownAt=0;
  private finalizedAt?:number;
  private retired:string[]=[];
  private timer?:ReturnType<typeof setTimeout>;
  private disposed=false;
  constructor(private changed:(view:TranslationView)=>void,
    private clock:()=>number=()=>performance.now()){}
  setSession(classId:string,epoch:number){
    const session=`${classId}/${epoch}`;
    if(this.disposed||session===this.session)return;
    clearTimeout(this.timer);this.timer=undefined;
    this.session=session;this.view={};this.pending=undefined;this.retired=[];
    this.finalizedAt=undefined;this.changed(this.view);
  }
  push(entry:Entry){
    if(this.disposed||entry.channel!=='translation'||!entry.text.trim()
      ||`${entry.classId}/${entry.sessionEpoch}`!==this.session)return;
    const key=identity(entry),current=this.view.current,previous=this.view.previous;
    if(previous&&identity(previous)===key){
      if(!previous.isFinal&&entry.revision>previous.revision){
        this.view={...this.view,previous:{...entry,unfinished:!entry.isFinal}};this.changed(this.view);
      }
      return;
    }
    if(this.retired.includes(key))return;
    const now=this.clock();
    if(!current){this.show(entry,now);return;}
    if(identity(current)===key){
      if(current.isFinal||entry.revision<=current.revision)return;
      this.view={...this.view,current:entry};
      if(entry.isFinal&&this.finalizedAt===undefined)this.finalizedAt=now;
      this.changed(this.view);this.schedule();return;
    }
    if(this.pending&&identity(this.pending)===key){
      if(this.pending.isFinal||entry.revision<=this.pending.revision)return;
      this.pending=entry;
    }else{
      if(this.pending)this.retire(identity(this.pending));
      else this.pendingAt=now;
      this.pending=entry;
    }
    this.schedule();
  }
  flush(){
    clearTimeout(this.timer);this.timer=undefined;
    if(!this.disposed&&this.pending)this.show(this.pending,this.clock());
    const current=this.view.current;
    if(!this.disposed&&current&&!current.isFinal&&!current.unfinished){
      this.view={...this.view,current:{...current,unfinished:true}};this.changed(this.view);
    }
  }
  dispose(){
    this.disposed=true;clearTimeout(this.timer);this.timer=undefined;
    this.pending=undefined;this.view={};this.retired=[];
  }
  private retire(key:string){this.retired.push(key);if(this.retired.length>32)this.retired.shift();}
  private show(entry:Entry,now:number){
    clearTimeout(this.timer);this.timer=undefined;
    const old=this.view.current;
    if(old)this.retire(identity(old));
    this.view={current:entry,previous:old?(old.isFinal?old:{...old,unfinished:true}):undefined};
    this.pending=undefined;this.shownAt=now;this.finalizedAt=entry.isFinal?now:undefined;
    this.changed(this.view);
  }
  private schedule(){
    clearTimeout(this.timer);this.timer=undefined;
    if(!this.pending||this.disposed)return;
    const readableAt=Math.max(this.shownAt+MIN_READ_MS,
      this.finalizedAt===undefined?0:this.finalizedAt+FINAL_GRACE_MS);
    const due=Math.min(readableAt,this.pendingAt+MAX_EXTRA_DELAY_MS);
    const now=this.clock();
    if(now>=due){this.show(this.pending,now);return;}
    this.timer=setTimeout(()=>{this.timer=undefined;this.schedule();},due-now);
  }
}
