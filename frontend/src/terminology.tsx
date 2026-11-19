import React,{useEffect,useMemo,useRef,useState} from 'react';

type Term={zh:string;en:string;direction:'zh-en'|'en-zh'};
type Summary={added:number;duplicate:number;conflict:number;invalid:number};
type Vocabulary={entries:Term[];entryCount:number;hotWordCount:number;maxEntries:number;importSummary?:Summary};
type ImportItem={zh:string;en:string;direction:string;location:string;status:string;detail:string};
type ImportPreview={items:ImportItem[];hotWords:string[];summary:Summary};
const directions={'zh-en':'中文 → 英文','en-zh':'英文 → 中文'};
const importStates:Record<string,string>={added:'可新增',duplicate:'已存在',conflict:'冲突',invalid:'无效'};

async function vocabulary<T=Vocabulary>(options?:RequestInit,url='/api/terminology'):Promise<T>{
  const response=await fetch(url,{cache:'no-store',...options});
  if(!response.ok){
    let detail='';
    try{const data=await response.json();if(typeof data.detail==='string')detail=data.detail;}catch{}
    throw Error(response.status===404?'请更新并重启后台，以使用专业词汇功能。':detail||'无法连接本机词表，请检查后台服务后重试。');
  }
  return response.json();
}

export function ProfessionalVocabulary(){
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const [open,setOpen]=useState(false),[loading,setLoading]=useState(false),[saving,setSaving]=useState(false);
  const [data,setData]=useState<Vocabulary>(),[error,setError]=useState(''),[success,setSuccess]=useState('');
  const [zh,setZh]=useState(''),[en,setEn]=useState(''),[direction,setDirection]=useState('both'),[search,setSearch]=useState('');
  const fileInput=useRef<HTMLInputElement>(null);
  const [parsing,setParsing]=useState(false),[preview,setPreview]=useState<ImportPreview>(),[filename,setFilename]=useState('');
  const revision=useRef(0);
  async function refresh(){
    const request=++revision.current;
    setLoading(true);setError('');
    try{const result=await vocabulary();if(request===revision.current)setData(result);}
    catch(error){if(request===revision.current)setError(error instanceof Error?error.message:'无法读取词表。');}
    finally{if(request===revision.current)setLoading(false);}
  }
  useEffect(()=>{
    if(!open)return;
    dialog.current?.showModal();void refresh();
    return()=>{++revision.current;dialog.current?.close();};
  },[open]);
  function close(){if(saving||parsing)return;setOpen(false);trigger.current?.focus();}
  async function add(event:React.FormEvent){
    event.preventDefault();if(saving||loading||!data)return;
    setSaving(true);setError('');setSuccess('');
    try{
      const result=await vocabulary({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zh:zh.trim(),en:en.trim(),direction})});
      setData(result);setSuccess(`已保存“${zh.trim()} / ${en.trim()}”。下次开始或暂停后继续课程时生效。`);
      setSearch(zh.trim());setZh('');setEn('');setPreview(undefined);
    }catch(error){setError(error instanceof Error?error.message:'词汇未保存，请重试。');}
    finally{setSaving(false);}
  }
  async function parseFile(file:File){
    setPreview(undefined);setError('');setSuccess('');setFilename(file.name);
    if(file.size>2*1024*1024){setError('词表文件最大 2 MiB。');return;}
    setParsing(true);
    try{
      const result=await vocabulary<ImportPreview>({method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file},`/api/terminology/import/preview?filename=${encodeURIComponent(file.name)}`);
      setPreview(result);
    }catch(error){setError(error instanceof Error?error.message:'无法解析词表。');}
    finally{setParsing(false);if(fileInput.current)fileInput.current.value='';}
  }
  async function importFile(){
    if(!preview||saving)return;setSaving(true);setError('');setSuccess('');
    try{
      const result=await vocabulary({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:preview.items,hotWords:preview.hotWords})},'/api/terminology/import');
      setData(result);setSearch('');setPreview(undefined);
      const summary=result.importSummary!;
      setSuccess(`导入完成：新增 ${summary.added} 行，跳过 ${summary.duplicate} 行重复、${summary.conflict} 行冲突和 ${summary.invalid} 行无效词条。下次开始或继续课程时生效。`);
    }catch(error){setError(error instanceof Error?error.message:'导入未保存。');}
    finally{setSaving(false);}
  }
  const entries=useMemo(()=>{
    const query=search.trim().toLocaleLowerCase();
    return (data?.entries??[]).filter(entry=>!query||entry.zh.toLocaleLowerCase().includes(query)||entry.en.toLocaleLowerCase().includes(query));
  },[data,search]);
  return <>
    <button type="button" className="vocabulary-trigger" ref={trigger} onClick={()=>{setSuccess('');setOpen(true);}}>新增专业词汇</button>
    <dialog className="vocabulary-dialog" ref={dialog} aria-labelledby="vocabulary-title" onCancel={event=>{event.preventDefault();close();}}>
      <div className="vocabulary-heading"><h2 id="vocabulary-title">专业词汇表</h2><button type="button" className="quiet" disabled={saving||parsing} aria-label="关闭专业词汇表" onClick={close}>关闭</button></div>
      <form className="vocabulary-form" onSubmit={event=>void add(event)}>
        <label>中文词汇<input autoFocus required maxLength={200} value={zh} disabled={saving} onChange={event=>setZh(event.target.value)} placeholder="例如：现象学观察法"/></label>
        <label>英文译法<input required maxLength={200} value={en} disabled={saving} onChange={event=>setEn(event.target.value)} placeholder="填写希望使用的英文译法"/></label>
        <label>应用方向<select value={direction} disabled={saving} onChange={event=>setDirection(event.target.value)}><option value="both">双向中英互译</option><option value="zh-en">中文 → 英文</option><option value="en-zh">英文 → 中文</option></select></label>
        <button type="submit" className="primary" disabled={saving||parsing||loading||!data||!zh.trim()||!en.trim()}>{saving?'保存中…':'保存词汇'}</button>
      </form>
      <p className="vocabulary-note">仅用于豆包同传，作为识别和翻译提示，实际采用情况取决于模型。已有不同译法的词条不会被覆盖。</p>
      {error&&<p className="record-error" role="alert">{error}</p>}
      {success&&<p className="vocabulary-success" role="status">{success}</p>}
      <section className="vocabulary-import" aria-label="导入词表">
        <div className="vocabulary-import-actions"><button type="button" disabled={saving||parsing||loading||!data} onClick={()=>fileInput.current?.click()}>{parsing?'解析中…':'导入词表'}</button><span>Excel / CSV / JSON · 中文、英文两列，方向可选</span></div>
        <input hidden type="file" ref={fileInput} accept=".xlsx,.csv,.tsv,.txt,.json" aria-label="选择词表文件" onChange={event=>{const file=event.target.files?.[0];if(file)void parseFile(file);}}/>
        {preview&&<div className="vocabulary-import-preview">
          <p className="vocabulary-import-summary">{filename} · 可新增 {preview.summary.added} 行 · 已存在 {preview.summary.duplicate} 行 · 冲突 {preview.summary.conflict} 行 · 无效 {preview.summary.invalid} 行</p>
          <div className="vocabulary-table" tabIndex={0} aria-label="导入预览"><table><thead><tr><th>中文</th><th>英文</th><th>解析结果</th></tr></thead><tbody>{preview.items.map((item,index)=><tr key={index}><td>{item.zh||'—'}</td><td>{item.en||'—'}</td><td><strong>{importStates[item.status]}</strong><small>{item.location} · {item.detail}</small></td></tr>)}</tbody></table></div>
          <div className="vocabulary-import-actions"><button type="button" className="primary" disabled={saving||(!preview.summary.added&&!preview.hotWords.length)} onClick={()=>void importFile()}>{saving?'导入中…':'确认导入'}</button><button type="button" className="quiet" disabled={saving} onClick={()=>setPreview(undefined)}>取消</button></div>
        </div>}
      </section>
      <div className="vocabulary-list-heading"><h3>已有词汇{data&&` · ${data.entries.length} 个方向词条`}</h3><button type="button" className="quiet" disabled={loading||saving} onClick={()=>void refresh()}>{loading?'读取中…':'刷新词表'}</button></div>
      <label className="vocabulary-search">搜索已有词汇<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="搜索中文或英文"/></label>
      <div className="vocabulary-table" tabIndex={0} aria-label="已有专业词汇">
        <table><thead><tr><th>中文</th><th>英文</th><th>方向</th></tr></thead><tbody>{entries.map(entry=><tr key={`${entry.direction}/${entry.zh}/${entry.en}`}><td>{entry.zh}</td><td>{entry.en}</td><td>{directions[entry.direction]}</td></tr>)}</tbody></table>
        {!loading&&data&&!entries.length&&<p className="saved-empty">没有匹配的词汇。</p>}
      </div>
    </dialog>
  </>;
}
