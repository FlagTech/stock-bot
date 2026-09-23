import { useState } from 'react';
import { api, type Settings } from './api';
import { Field } from './components';
import AnalysisSettings, { DEFAULT_ANALYSIS } from './AnalysisSettings';
const MODELS = ['gpt-5.6-luna', 'gpt-5.6-terra', 'gpt-5.6-sol', 'gpt-6-astra'];
export default function SettingsPage({settings,updated,notify}:{settings:Settings;updated:(s:Settings)=>void;notify:(s:string)=>void}){
 const [draft,setDraft]=useState({...settings,analysis:settings.analysis??DEFAULT_ANALYSIS}),[key,setKey]=useState(''),[busy,setBusy]=useState(false);
 async function action(fn:()=>Promise<void>){setBusy(true);try{await fn()}catch(e){notify((e as Error).message)}finally{setBusy(false)}}
 async function save(section:'model'|'analysis') {
  const current = await api<Settings>('/settings');
  const {configured,...values} = current;
  const s = await api<Settings>('/settings','PUT',{
   values: {...values,...(section==='model'?{model:draft.model}:{analysis:draft.analysis})},
   secrets: section==='model'?{openai_key:key}:{},
  });
  updated(s);
  setDraft(previous=>({...previous,configured:s.configured,...(section==='model'?{model:s.model}:{analysis:s.analysis})}));
  if(section==='model') setKey('');
  notify(section==='model'?'模型設定已儲存。請測試模型連線。':'分析項目已儲存，將於下一次分析套用。');
 }
 return <><p className="intro">先完成 OpenAI 設定，再到本機試聊確認分析功能。</p>
 <form className="settings-form" onSubmit={e=>{e.preventDefault();void action(()=>save('model'))}}>
 <section className="form-panel" aria-labelledby="model-title"><h2 id="model-title">模型設定</h2><Field label="API Key" hint={settings.configured.openai_key?'已設定。留空保留原金鑰；金鑰不回傳到網頁。':'金鑰存於作業系統憑證庫，不會寫進專案。'}><input type="password" value={key} onChange={e=>setKey(e.target.value)} autoComplete="off" placeholder="輸入 OpenAI API Key"/></Field>
 <Field label="模型"><select value={MODELS.includes(draft.model)?draft.model:"custom"} onChange={e=>setDraft({...draft,model:e.target.value==="custom"?"":e.target.value})}>{MODELS.map(model=><option key={model} value={model}>{model}</option>)}<option value="custom">自訂模型 ID</option></select></Field>
 <Field label="模型 ID" hint="請填入你的 API 帳號可用、支援工具呼叫的模型。"><input value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value})} placeholder="輸入模型 ID" required maxLength={120}/></Field>
 <div className="actions"><button className="primary" disabled={busy}>儲存設定</button><button type="button" disabled={busy} onClick={()=>void action(async()=>notify((await api<{message:string}>('/test/openai','POST')).message))}>測試已儲存的模型</button></div><p className="note">連線測試會執行工具呼叫；若已儲存的分析項目開啟網路搜尋，也會執行搜尋測試並產生相關用量。</p>
 </section></form>
 <form className="settings-form" onSubmit={e=>{e.preventDefault();void action(()=>save('analysis'))}}>
 <AnalysisSettings value={draft.analysis} onChange={analysis=>setDraft({...draft,analysis})}>
 <div className="actions"><button className="primary" disabled={busy||!draft.analysis.price_fields.length||!draft.analysis.fundamental_fields.length}>儲存設定</button></div>
 </AnalysisSettings></form>
 <section className="form-panel"><h2>資料管理</h2><p>對話與分析紀錄保存在本機。清除後無法復原。</p><div className="actions"><button className="danger" onClick={()=>{if(confirm('清除所有平台的對話與已完成工作紀錄？'))void action(async()=>notify((await api<{message:string}>('/records','DELETE')).message))}}>清除所有紀錄</button><button onClick={()=>void action(async()=>{const d=await api('/diagnostics');const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='stock-bot-diagnostics.json';a.click();URL.revokeObjectURL(url)})}>匯出診斷資訊</button></div><p className="note">診斷資訊不含金鑰、對話文字或聊天帳號識別碼。</p></section></>;
}
