import type { ReactNode } from 'react';
import { MessageCircle, ChevronRight } from 'lucide-react';
import { statusName, type Job } from './api';

export function Field({label,hint,children}:{label:string;hint?:string;children:ReactNode}){
  return <label className="field"><span>{label}</span>{children}{hint&&<small>{hint}</small>}</label>;
}
export function Empty({go}:{go:()=>void}){return <div className="empty"><MessageCircle size={44}/><h3>還沒有分析紀錄</h3><p>到本機試聊送出第一個問題。</p><button className="primary" onClick={go}>開始試聊</button></div>}
export function Jobs({jobs,go}:{jobs:Job[];go:()=>void}){
  if(!jobs.length)return <Empty go={go}/>;
  return <div className="job-list">{jobs.map(j=><details className="job" key={j.id}><summary><span className="job-platform">{j.platform==='local'?'本機':j.platform==='line'?'LINE':'Telegram'}</span><span className="job-question">{j.text}</span><time>{new Date(j.created*1000).toLocaleString('zh-TW')}</time><span className={`badge ${j.status==='failed'||j.status==='uncertain'?'warn':''}`}>{statusName[j.status]||j.status}</span><ChevronRight size={16}/></summary><div className="job-detail">{j.error&&<p className="error">{j.error}</p>}<p className="prewrap">{j.result||'尚無結果。'}</p>{j.status==='uncertain'&&<p>請先查看平台聊天紀錄，再決定是否重新提問。</p>}</div></details>)}</div>;
}
export function Toggle({checked,onChange,children}:{checked:boolean;onChange:(v:boolean)=>void;children:ReactNode}){return <label className="toggle"><input type="checkbox" checked={checked} onChange={e=>onChange(e.target.checked)}/><span>{children}</span></label>}
