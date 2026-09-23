import type { ReactNode } from 'react';
import { Field } from './components';

const PRICE_FIELDS = [
 ['close','收盤價'], ['daily_return','每日報酬'], ['change','漲跌價差'], ['period_return','期間報酬'],
 ['volume','成交量'], ['ma5','5 日均線'], ['ma20','20 日均線'], ['ma60','60 日均線'],
 ['rsi14','RSI（14）'], ['macd','MACD（12、26、9）'], ['bollinger','布林通道（20、2）'],
] as const;
const FUNDAMENTAL_FIELDS = [
 ['revenue','營收'], ['eps','EPS'], ['revenue_growth','營收成長率'], ['eps_growth','EPS 成長率'],
 ['gross_margin','毛利率'], ['operating_margin','營業利益率'], ['net_margin','淨利率'], ['roe','ROE（期末權益）'],
 ['net_income','淨利'], ['assets','總資產'], ['liabilities','總負債'], ['equity','股東權益'],
 ['operating_cashflow','營業現金流'], ['free_cashflow','自由現金流'],
 ['market_cap','市值'], ['trailing_pe','本益比（TTM）'], ['forward_pe','預估本益比'], ['price_to_book','股價淨值比'],
] as const;
export type AnalysisOptions = {
 price_days:number; price_fields:string[]; fundamental_fields:string[]; news_count:number; web_search_enabled:boolean;
};
export const DEFAULT_ANALYSIS:AnalysisOptions = {
 price_days:15, price_fields:['close','daily_return','change','period_return'],
 fundamental_fields:['revenue','eps','revenue_growth','eps_growth','gross_margin','operating_margin','net_margin','roe'],
 news_count:10, web_search_enabled:false,
};

export default function AnalysisSettings({value,onChange,children}:{value:AnalysisOptions;onChange:(v:AnalysisOptions)=>void;children?:ReactNode}) {
 function toggle(key:'price_fields'|'fundamental_fields', id:string) {
  const list = value[key];
  onChange({...value,[key]:list.includes(id)?list.filter(item=>item!==id):[...list,id]});
 }
 return <section className="form-panel analysis-settings" aria-labelledby="analysis-title">
  <h2 id="analysis-title">分析項目</h2>
  <p>套用於本機試聊、LINE 與 Telegram。勾選要提供給 AI 的資料；變更後請儲存設定。</p>
  <fieldset className="analysis-group"><legend>價格面</legend>
   <Field label="分析天期（日曆天）" hint="可輸入 3～180 天，預設 15 天。對話中明確指定其他天期時，優先使用該次指定。">
    <input type="number" min={3} max={180} step={1} required value={value.price_days} onChange={e=>onChange({...value,price_days:Number(e.target.value)})}/>
   </Field>
   <p className="options-label">分析欄位（至少勾選一項）</p>
   <div className="analysis-options">{PRICE_FIELDS.map(([id,label])=><label key={id}><input type="checkbox" checked={value.price_fields.includes(id)} onChange={()=>toggle('price_fields',id)}/><span>{label}</span></label>)}</div>
   {!value.price_fields.length && <p className="error" role="alert">請至少勾選一項價格面資料。</p>}
   <p className="note">報酬與指標以原始收盤價計算。指標週期為交易日，程式會額外取得暖機資料；樣本不足時標示缺值。</p>
  </fieldset>
  <fieldset className="analysis-group"><legend>基本面</legend>
   <p>預設延續目前的財報項目；可增加資產負債、現金流與估值資料，至少勾選一項。</p>
   <div className="analysis-options">{FUNDAMENTAL_FIELDS.map(([id,label])=><label key={id}><input type="checkbox" checked={value.fundamental_fields.includes(id)} onChange={()=>toggle('fundamental_fields',id)}/><span>{label}</span></label>)}</div>
   {!value.fundamental_fields.length && <p className="error" role="alert">請至少勾選一項基本面資料。</p>}
   <p className="note">資料來自 Yahoo Finance。季報成長率為季增率、年報為年增率；ROE 使用年報。估值為目前快照，部分股票或 ETF 可能沒有資料。</p>
  </fieldset>
  <fieldset className="analysis-group"><legend>新聞面</legend>
   <Field label="新聞篇數" hint="每檔股票預設擷取 10 篇，可設定 5～20 篇；來源不足時回傳實際取得篇數。對話指定篇數時可覆寫（1～20 篇）。">
    <input type="number" min={5} max={20} step={1} required value={value.news_count} onChange={e=>onChange({...value,news_count:Number(e.target.value)})}/>
   </Field>
   <label className="toggle"><input type="checkbox" checked={value.web_search_enabled} onChange={e=>onChange({...value,web_search_enabled:e.target.checked})}/><span>開啟網路搜尋（OpenAI 內建）</span></label>
   <p className="note">開啟後 AI 可視問題需要搜尋網路，補充新聞並附來源連結；與上述新聞篇數分開計算。需使用支援內建搜尋的模型，會增加 API 與搜尋費用。儲存後的模型測試也會測試搜尋。</p>
  </fieldset>
  {children}
 </section>;
}
