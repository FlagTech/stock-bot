import type { AnalysisOptions } from './AnalysisSettings';
export type Settings = {model:string;line_enabled:boolean;telegram_enabled:boolean;ngrok_enabled:boolean;analysis:AnalysisOptions;timeout_seconds:number;retention_days:number;reply_chars:number;configured:Record<string,boolean>};
export type Status = {line:string;telegram:string;line_last_event:number|null;telegram_last_event:number|null;line_notice_error:string|null;tunnel:{state:string;url:string};applying:boolean};
export type Job = {id:string;platform:string;text:string;status:string;result:string;error:string;created:number;sent:number;progress?:string};
export type Message = {role:string;content:string};
let token = '';
export async function api<T>(path:string, method='GET', body?:unknown):Promise<T>{
  const response = await fetch(`/api${path}`, { method, headers: {'Content-Type':'application/json','X-Stock-Bot-Token':token}, body:body===undefined?undefined:JSON.stringify(body) });
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'資料格式不符，請檢查輸入欄位。');
  return data;
}
export async function bootstrap(){const data=await api<{token:string;settings:Settings;status:Status}>('/bootstrap');token=data.token;return data;}
export const statusName:Record<string,string>={queued:'排隊中',running:'分析中',sending:'傳送中',done:'已完成',failed:'失敗',interrupted:'已中斷',uncertain:'待確認'};
