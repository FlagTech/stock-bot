import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Send, MessageCircle } from 'lucide-react';
import { api, type Job, statusName } from './api';
export default function ChatPage({jobs,notify}:{jobs:Job[];notify:(s:string)=>void}){
 const [text,setText]=useState(''),[busy,setBusy]=useState(false);
 const local=jobs.filter(j=>j.platform==='local');
 const reset=local.find(j=>j.text==='/reset'&&j.status==='done');
 const visible=local.filter(j=>!reset||j.created>=reset.created).reverse();
 async function send(){if(!text.trim())return;setBusy(true);try{await api('/chat','POST',{text});setText('');notify('問題已送出，可在下方查看進度。')}catch(e){notify((e as Error).message)}finally{setBusy(false)}}
 return <><div className="section-heading"><div><p className="intro">先在電腦上與 AI 對話，確認資料查詢與模型設定。</p></div><button onClick={()=>{if(confirm('清除本機對話脈絡？工作紀錄仍會保留。'))void api('/chat/reset','POST').then(()=>notify('已排入清除對話工作。')).catch(e=>notify(e.message))}}>清除對話</button></div><div className="chat-panel"><div className="messages" aria-live="polite">{!visible.length?<div className="chat-empty"><MessageCircle size={40}/><h2>從一個股票問題開始</h2><p>可用股票名稱或代號，也能接續上一個問題。</p><div className="suggestions">{['台積電近 30 天股價表現','比較鴻海和台積電','分析大盤近期趨勢'].map(q=><button key={q} onClick={()=>setText(q)}>{q}</button>)}</div></div>:visible.map(j=><div key={j.id}><article className="message user"><small>你</small><p>{j.text}</p></article>{j.result&&<article className="message assistant"><small>Stock Bot</small><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a:({children,...props})=><a {...props} target="_blank" rel="noreferrer">{children}</a>}}>{j.result}</ReactMarkdown></article>}{j.error&&<p className="error">{j.error}</p>}{['queued','running','sending'].includes(j.status)&&<div className="pending">{j.status==='running'&&j.progress||statusName[j.status]}…</div>}</div>)}</div><form className="composer" onSubmit={e=>{e.preventDefault();void send()}}><textarea aria-label="股票問題" value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>{// Enter 送出、Shift+Enter 換行；中文輸入法選字中（isComposing / 229）的 Enter 不送出。
  if(e.key!=='Enter'||e.shiftKey||e.nativeEvent.isComposing||e.keyCode===229)return;e.preventDefault();if(!busy)void send()}} placeholder="例如：台積電最近的基本面如何？（Enter 送出，Shift+Enter 換行）" maxLength={4000} rows={3}/><div><small>資料僅供研究，不構成投資建議。{text.length}/4000</small><button className="primary" disabled={busy||!text.trim()}><Send size={16}/>送出問題</button></div></form></div></>;
}
