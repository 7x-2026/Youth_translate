import React,{useEffect,useRef,useState} from 'react';
import type {Entry} from './subtitles';

export type CourseRecord={id:string;name:string;createdAt:number;updatedAt:number;state:string;mode:string;engine:string;incomplete:boolean;segmentCount:number};
export type RecordStatus=Partial<CourseRecord>&{saveState:'saved'|'error';detail?:string};
type RecordDetail={record:CourseRecord;entries:Entry[]};
const states:Record<string,string>={recording:'进行中',paused:'已暂停',ended:'已结束',interrupted:'已中断'};
export const recordExportUrl=(id:string)=>`/api/records/${encodeURIComponent(id)}/export`;

async function read<T>(url:string):Promise<T>{
  const response=await fetch(url,{cache:'no-store'});
  if(!response.ok)throw Error(response.status===404?'记录暂不可用，请确认后台已更新并重启。':'无法读取本地记录，请检查后台服务、磁盘空间和目录权限。');
  return response.json();
}

export function SavedCourses({revision}:{revision:number}){
  const [courses,setCourses]=useState<CourseRecord[]>([]);
  const [more,setMore]=useState(false),[loading,setLoading]=useState(false);
  const [error,setError]=useState(''),[detailError,setDetailError]=useState('');
  const [selected,setSelected]=useState<RecordDetail>(),[opening,setOpening]=useState('');
  const listRequest=useRef(0),detailRequest=useRef(0);
  async function refresh(append=false){
    const request=++listRequest.current;
    setLoading(true);setError('');
    try{
      const result=await read<{records:CourseRecord[];hasMore:boolean}>(`/api/records?limit=50&offset=${append?courses.length:0}`);
      if(request!==listRequest.current)return;
      setCourses(old=>append?[...old,...result.records]:result.records);setMore(result.hasMore);
    }catch(error){if(request===listRequest.current)setError(error instanceof Error?error.message:'无法读取历史课程。');}
    finally{if(request===listRequest.current)setLoading(false);}
  }
  useEffect(()=>{void refresh();},[revision]);
  useEffect(()=>()=>{++listRequest.current;++detailRequest.current;},[]);
  async function view(id:string){
    const request=++detailRequest.current;
    setOpening(id);setDetailError('');setSelected(undefined);
    try{
      const result=await read<RecordDetail>(`/api/records/${encodeURIComponent(id)}`);
      if(request===detailRequest.current)setSelected(result);
    }catch(error){if(request===detailRequest.current)setDetailError(error instanceof Error?error.message:'无法读取课程内容。');}
    finally{if(request===detailRequest.current)setOpening('');}
  }
  return <section className="saved-courses" aria-label="历史课程">
    <div className="section-title"><h2>历史课程 <span>自动保存到本机 · 可随时导出</span></h2><button type="button" className="quiet" disabled={loading} onClick={()=>void refresh()}>{loading?'读取中…':'刷新记录'}</button></div>
    {error&&<p className="record-error" role="alert">{error}</p>}
    {!courses.length&&!loading&&!error&&<p className="saved-empty">课程开始后会自动创建记录，关闭页面后仍可在这里查看和导出。</p>}
    <div className="saved-course-list">{courses.map(course=><article className="saved-course" key={course.id}>
      <div><strong>{course.name}</strong><p className="record-meta">{new Date(course.createdAt).toLocaleString()} · {course.segmentCount} 段 · {states[course.state]??course.state}{course.incomplete&&' · 部分记录未保存'}</p></div>
      <div className="record-actions"><button type="button" onClick={()=>void view(course.id)} disabled={opening===course.id}>{opening===course.id?'读取中…':'查看'}</button><a href={recordExportUrl(course.id)} download>导出 TXT</a></div>
    </article>)}</div>
    {more&&<button type="button" className="quiet" disabled={loading} onClick={()=>void refresh(true)}>加载更多</button>}
    {detailError&&<p className="record-error" role="alert">{detailError}</p>}
    {selected&&<section className="saved-detail" aria-label="课程详情">
      <div className="section-title"><h3>{selected.record.name}</h3><div className="record-actions"><a href={recordExportUrl(selected.record.id)} download>导出 TXT</a><button type="button" className="quiet" onClick={()=>setSelected(undefined)}>收起</button></div></div>
      {selected.record.incomplete&&<p className="record-error">本次课程曾发生保存失败，记录可能不完整。</p>}
      <div className="saved-entries">{selected.entries.length?selected.entries.map(entry=><article key={`${entry.sessionEpoch}/${entry.channel}/${entry.segmentId}`}><time>{new Date(entry.receivedAt).toLocaleTimeString()}</time><div><span className="channel">{entry.channel==='source'?'原文':'译文'}{!entry.isFinal?' · 未定稿':''}</span><p>{entry.text}</p></div></article>):<p className="saved-empty">这节课程尚未收到字幕。</p>}</div>
    </section>}
  </section>;
}
