import { useState } from 'react';
import { api, type Settings, type Status } from './api';
import { Field, Toggle } from './components';
type Platform='telegram'|'line';
const SECRETS:Record<Platform,string[]>={telegram:['telegram_token'],line:['line_secret','line_token','ngrok_token']};
const pick=(p:Platform,s:Settings)=>p==='telegram'?{telegram_enabled:s.telegram_enabled}:{line_enabled:s.line_enabled,ngrok_enabled:s.ngrok_enabled};
export default function PlatformsPage({settings,status,updated,notify}:{settings:Settings;status:Status;updated:(s:Settings)=>void;notify:(s:string)=>void}){
 const [draft,setDraft]=useState(settings),[secrets,setSecrets]=useState<Record<string,string>>({}),[busy,setBusy]=useState(false);
 const locked=busy||status.applying;
 async function action(fn:()=>Promise<void>){setBusy(true);try{await fn()}catch(e){notify((e as Error).message)}finally{setBusy(false)}}
 // 只送出這張卡片的欄位與金鑰，另一個平台尚未儲存的輸入仍保留在畫面上。
 async function save(platform:Platform){
  const {configured,...current}=await api<Settings>('/settings');
  const s=await api<Settings>('/settings','PUT',{values:{...current,...pick(platform,draft)},secrets:Object.fromEntries(SECRETS[platform].map(k=>[k,secrets[k]||''])),scope:platform});
  updated(s);
  setDraft(previous=>({...previous,configured:s.configured,...pick(platform,s)}));
  setSecrets(previous=>Object.fromEntries(Object.entries(previous).filter(([k])=>!SECRETS[platform].includes(k))));
  notify(`${platform==='telegram'?'Telegram':'LINE'} 設定已儲存，正在套用連線。`);
 }
 const reconnect=(platform:Platform)=>void action(async()=>notify((await api<{message:string}>(`/platforms/apply?platform=${platform}`,'POST')).message));
 const lastEvent=(time:number|null)=>time?new Date(time*1000).toLocaleString('zh-TW'):'尚未收到';
 const secretField=(key:string,label:string)=><Field label={label} hint={settings.configured[key]?'已設定，留空保留。':'尚未設定。'}><input type="password" autoComplete="off" value={secrets[key]||''} onChange={e=>setSecrets({...secrets,[key]:e.target.value})} placeholder={`輸入 ${label}`}/></Field>;
 return <><p className="intro">選擇一個平台開始，也可以同時啟用 Telegram 與 LINE。第一版支援私人文字聊天。啟用後請保持電腦連線與程式運作。</p>
 <div className="platform-forms"><form className="form-panel" onSubmit={e=>{e.preventDefault();void action(()=>save('telegram'))}}><div className="section-heading"><h2>Telegram</h2><span className="badge">{status.telegram}</span></div><p>使用長輪詢直接接收訊息，不需要公開網址或 ngrok。</p><ol className="steps-list"><li>開啟 <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">BotFather</a>，輸入 /newbot 建立機器人。</li><li>將取得的 Bot token 填在下方。</li><li>儲存並啟用後，開啟機器人並傳送 /start。</li></ol>{secretField('telegram_token','Bot token')}<Toggle checked={draft.telegram_enabled} onChange={v=>setDraft({...draft,telegram_enabled:v})}>啟用 Telegram</Toggle>
 <div className="actions"><button className="primary" disabled={locked}>{locked?'正在處理…':'儲存並套用 Telegram'}</button><button type="button" disabled={locked} onClick={()=>void action(async()=>notify((await api<{message:string}>('/test/telegram','POST')).message))}>測試已儲存的 Bot</button></div>
 <div className="status-row"><p className="note">最近收到訊息：{lastEvent(status.telegram_last_event)}</p><button type="button" disabled={locked} onClick={()=>reconnect('telegram')}>重新連線</button></div><details className="advanced"><summary>已有其他程式在使用此 Bot？</summary><p>請先停止原來的機器人程式。若曾設定 Webhook，可解除後改用本機長輪詢；不會丟棄待接收訊息。</p><button type="button" disabled={locked} onClick={()=>{if(confirm('解除此 Bot 原有 Webhook？原本的服務將不再接收訊息。'))void action(async()=>notify((await api<{message:string}>('/telegram/delete-webhook','POST')).message))}}>解除舊 Webhook</button></details></form>
 <form className="form-panel" onSubmit={e=>{e.preventDefault();void action(()=>save('line'))}}><div className="section-heading"><h2>LINE</h2><span className="badge">{status.line}</span></div><p>使用 Messaging API 接收訊息，由 ngrok 將 Webhook 轉送到本機。</p><ol className="steps-list"><li><a href="https://developers.line.biz/zh-hant/docs/messaging-api/getting-started/" target="_blank" rel="noreferrer">建立官方帳號並啟用 Messaging API</a></li><li>從 LINE Developers 取得以下兩項金鑰。</li></ol>{secretField('line_secret','Channel secret')}{secretField('line_token','Channel access token')}
 <Toggle checked={draft.line_enabled} onChange={v=>setDraft({...draft,line_enabled:v})}>啟用 LINE</Toggle><hr/><h3>ngrok 公開通道</h3><p><a href="https://dashboard.ngrok.com/get-started/your-authtoken" target="_blank" rel="noreferrer">註冊 ngrok 並取得 authtoken</a>。首次啟動會下載通道工具。</p>{secretField('ngrok_token','ngrok authtoken')}<Toggle checked={draft.ngrok_enabled} onChange={v=>setDraft({...draft,ngrok_enabled:v})}>隨 LINE 啟動 ngrok 通道</Toggle>
 <div className="actions"><button className="primary" disabled={locked}>{locked?'正在處理…':'儲存並套用 LINE'}</button><button type="button" disabled={locked} onClick={()=>void action(async()=>notify((await api<{message:string}>('/test/line','POST')).message))}>測試已儲存的 LINE 權杖</button></div>
 <div className="connection"><strong>{status.tunnel.state}</strong>{status.tunnel.url?<><code>{status.tunnel.url}</code><button type="button" onClick={()=>void navigator.clipboard.writeText(status.tunnel.url).then(()=>notify('已複製 Webhook 網址。')).catch(()=>notify('請選取網址並手動複製。'))}>複製 Webhook 網址</button></>:<p>儲存並啟動後，這裡會顯示完整 Webhook 網址。</p>}<div className="actions"><button type="button" disabled={locked} onClick={()=>reconnect('line')}>重新連線</button></div></div><ol className="steps-list" start={3}><li>貼入 LINE Developers 的 Webhook URL，按 Verify。</li><li>開啟 Use webhook，關閉官方帳號預設的自動回應。</li><li>加入好友並傳送問題，確認下方接收紀錄。</li></ol><p className="note">Webhook 簽章須以真實事件驗證。最終報告以推播傳送，會使用 LINE 訊息額度。</p><p className="note">最近收到訊息：{lastEvent(status.line_last_event)}</p></form></div></>;
}
