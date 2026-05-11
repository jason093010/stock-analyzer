# ╔═══════════════════════════════════════════════════════════════════╗
# ║  股市小白分析系統 Pro  V2.0  ─  機構級量化重構版                      ║
# ║  Taiwan Color: RED=漲  GREEN=跌  |  AI三方辯論  |  蒙地卡羅模擬      ║
# ╚═══════════════════════════════════════════════════════════════════╝
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from google import genai
from google.genai import types as genai_types
import time, hashlib, base64, json
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ══════════════════════════════════════════════
# 1. 頁面設定
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="股市小白分析系統 Pro V2",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════
# 2. Supabase（保持原有連線邏輯不動）
# ══════════════════════════════════════════════
HAS_DB = False
_supabase = None
try:
    from supabase import create_client
    _url = st.secrets.get("SUPABASE_URL", "")
    _key = st.secrets.get("SUPABASE_KEY", "")
    if _url and _key:
        _supabase = create_client(_url, _key)
        HAS_DB = True
except Exception:
    pass

# ══════════════════════════════════════════════
# 3. CSS（台灣色系：紅漲綠跌）
# ══════════════════════════════════════════════
st.markdown("""
<style>
/* ── 響應式 ── */
@media(max-width:768px){
  h1{font-size:1rem!important} h3{font-size:0.85rem!important}
  .stButton>button{font-size:10px!important;padding:3px 5px!important}
}
/* ── 主視覺卡片 ── */
.score-card{background:linear-gradient(135deg,#1e1e2e,#2a2a3e);
  border-radius:16px;padding:20px;text-align:center;
  border:1px solid #3a3a5e;margin-bottom:12px}
.big-score{font-size:3rem;font-weight:900;line-height:1.1}
.status-card{background:#1e1e2e;border-radius:12px;padding:14px;
  margin:6px 0;border-left:5px solid #7c3aed}
.entry-card{background:linear-gradient(135deg,#0d2b0d,#1a3a1a);
  border-radius:12px;padding:13px;margin:5px 0;border:1px solid #2a5a2a}
.stop-card{background:#2a0d0d;border-radius:12px;padding:13px;
  margin:5px 0;border:1px solid #5a1a1a}
.target-card{background:#0d1a2b;border-radius:12px;padding:13px;
  margin:5px 0;border:1px solid #1a3a5a}
.predict-card{background:linear-gradient(135deg,#1a0d2b,#2b1a3a);
  border-radius:14px;padding:16px;margin:8px 0;border:2px solid #6b2fba}
.bull-card{background:linear-gradient(135deg,#2b0d0d,#3a1a1a);
  border-radius:12px;padding:14px;margin:5px 0;border:2px solid #cc3333}
.bear-card{background:linear-gradient(135deg,#0d2b0d,#1a3a1a);
  border-radius:12px;padding:14px;margin:5px 0;border:2px solid #33cc33}
.judge-card{background:linear-gradient(135deg,#1a1a2b,#2b2a3a);
  border-radius:12px;padding:14px;margin:5px 0;border:2px solid #9966cc}
.event-warn{background:#3a1a00;border-radius:8px;padding:10px;
  border:1px solid #aa4400;margin:4px 0}
.confirm-warn{background:#3a1a00;border-radius:8px;padding:10px;
  border:1px solid #aa4400;margin:6px 0}
/* ── 台灣色系強調 ── */
.price-up{color:#ff4444!important;font-weight:700}
.price-dn{color:#22cc44!important;font-weight:700}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# 4. Session State
# ══════════════════════════════════════════════
_DEFS = dict(
    user_id=None, username=None, logged_in=False, _pin="",
    api_key="", watchlist=[], alerts={}, portfolio={},
    trade_history=[], recent_searches=[], quick_sym="",
    auto_analyze=False,
    confirm_clear_watch=False, confirm_clear_port=False,
    confirm_clear_trades=False,
    macro_regime="未知",
)
for k, v in _DEFS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════
# 5. 加密工具
# ══════════════════════════════════════════════
_SALT = b"tw_stock_pro_v2_salt"

def _derive_key(pin: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=_SALT, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(pin.encode()))

def encrypt_key(api_key: str, pin: str) -> str:
    return Fernet(_derive_key(pin)).encrypt(api_key.encode()).decode()

def decrypt_key(token: str, pin: str) -> str:
    try: return Fernet(_derive_key(pin)).decrypt(token.encode()).decode()
    except: return ""

# ══════════════════════════════════════════════
# 6. 資料庫函數
# ══════════════════════════════════════════════
def make_uid(username: str, pin: str) -> str:
    return hashlib.sha256(f"{username.lower().strip()}:{pin}".encode()).hexdigest()[:20]

def db_verify_user(username: str, pin: str):
    if not HAS_DB: return True, make_uid(username, pin), None
    try:
        uid = make_uid(username, pin)
        r = _supabase.table("users").select("id,encrypted_api_key") \
            .eq("username", username.lower().strip()) \
            .eq("password_hash", uid).execute()
        if r.data: return True, uid, r.data[0].get("encrypted_api_key")
        return False, None, None
    except: return False, None, None

def db_create_user(username: str, pin: str):
    if not HAS_DB: return True, make_uid(username, pin), "本機模式"
    try:
        uid = make_uid(username, pin)
        ex = _supabase.table("users").select("id") \
            .eq("username", username.lower().strip()).execute()
        if ex.data: return False, None, "帳號已存在"
        _supabase.table("users").insert({
            "username": username.lower().strip(), "password_hash": uid}).execute()
        return True, uid, "帳號建立成功！"
    except Exception as e: return False, None, str(e)[:60]

def db_save_enc_key(username: str, pin: str, api_key: str):
    if not HAS_DB or not api_key: return
    try:
        token = encrypt_key(api_key, pin)
        _supabase.table("users").update({"encrypted_api_key": token}) \
            .eq("username", username.lower().strip()).execute()
    except: pass

# ── Watchlist ──
def db_load_wl(uid): 
    if not HAS_DB: return []
    try: return [x["symbol"] for x in _supabase.table("watchlists").select("symbol").eq("user_id",uid).execute().data]
    except: return []
def db_add_wl(uid,sym):
    if not HAS_DB: return
    try:
        if not _supabase.table("watchlists").select("id").eq("user_id",uid).eq("symbol",sym).execute().data:
            _supabase.table("watchlists").insert({"user_id":uid,"symbol":sym}).execute()
    except: pass
def db_del_wl(uid,sym):
    if not HAS_DB: return
    try: _supabase.table("watchlists").delete().eq("user_id",uid).eq("symbol",sym).execute()
    except: pass

# ── Alerts ──
def db_load_alerts(uid):
    if not HAS_DB: return {}
    try: return {x["symbol"]:{"above":x.get("above_price"),"below":x.get("below_price")} for x in _supabase.table("alerts").select("*").eq("user_id",uid).execute().data}
    except: return {}
def db_save_alert(uid,sym,above,below):
    if not HAS_DB: return
    try:
        d={"user_id":uid,"symbol":sym,"above_price":above or None,"below_price":below or None}
        ex=_supabase.table("alerts").select("id").eq("user_id",uid).eq("symbol",sym).execute()
        if ex.data: _supabase.table("alerts").update(d).eq("user_id",uid).eq("symbol",sym).execute()
        else: _supabase.table("alerts").insert(d).execute()
    except: pass
def db_del_alert(uid,sym):
    if not HAS_DB: return
    try: _supabase.table("alerts").delete().eq("user_id",uid).eq("symbol",sym).execute()
    except: pass

# ── Portfolio ──
def db_load_port(uid):
    if not HAS_DB: return {}
    try:
        # 改成抓取所有原始列資料
        data = _supabase.table("portfolio").select("*").eq("user_id", uid).execute().data
        # 整理成以 symbol 為 key，內容為 list 的格式
        port = {}
        for x in data:
            sym = x["symbol"]
            if sym not in port: port[sym] = []
            port[sym].append({
                "db_id": x["id"], # 存下資料庫的唯一 ID 用於刪除
                "cost": x["cost_price"],
                "shares": x["shares"],
                "note": x.get("note",""),
                "buy_date": x.get("buy_date","")
            })
        return port
    except: return {}
def db_save_port(uid, sym, cost, shares, note="", buy_date=""):
    if not HAS_DB: return
    try:
        # 直接插入新的一列，不再檢查重複
        _supabase.table("portfolio").insert({
            "user_id": uid, "symbol": sym, 
            "cost_price": cost, "shares": shares, 
            "note": note, "buy_date": buy_date
        }).execute()
    except: pass
def db_del_port_by_id(uid, db_id):
    if not HAS_DB: return
    try:
        _supabase.table("portfolio").delete().eq("id", db_id).eq("user_id", uid).execute()
    except: pass

# ── Trade History ──
def db_load_trades(uid):
    if not HAS_DB: return []
    try: return _supabase.table("trade_history").select("*").eq("user_id",uid).order("created_at",desc=True).execute().data
    except: return []
def db_add_trade(uid,sym,direction,entry_price,exit_price,shares,entry_date,exit_date,note=""):
    if not HAS_DB: return
    try:
        pnl_amt = round((exit_price-entry_price)*shares*(1 if direction=="LONG" else -1),2)
        pnl_pct = round((exit_price-entry_price)/max(entry_price,0.01)*100*(1 if direction=="LONG" else -1),2)
        _supabase.table("trade_history").insert({
            "user_id":uid,"symbol":sym,"direction":direction,
            "entry_price":entry_price,"exit_price":exit_price,"shares":shares,
            "entry_date":entry_date,"exit_date":exit_date,
            "pnl_amount":pnl_amt,"pnl_pct":pnl_pct,"note":note
        }).execute()
    except: pass
def db_del_trade(uid,trade_id):
    if not HAS_DB: return
    try: _supabase.table("trade_history").delete().eq("id",trade_id).eq("user_id",uid).execute()
    except: pass

# ══════════════════════════════════════════════
# 7. 靜態資料
# ══════════════════════════════════════════════
TW_HOT = {
    "半導體": [("2330","台積電"),("2454","聯發科"),("2303","聯電"),("3711","日月光")],
    "ETF":    [("0050","台灣50"),("0056","高股息"),("00878","永續高息"),("00929","科技優息")],
    "金融":   [("2882","國泰金"),("2881","富邦金"),("2891","中信金"),("2884","玉山金")],
    "傳產":   [("1301","台塑"),("2002","中鋼"),("2412","中華電"),("1216","統一")],
}
US_HOT = {
    "科技":    [("AAPL","蘋果"),("MSFT","微軟"),("NVDA","輝達"),("GOOGL","Google")],
    "AI/半導": [("AMD","超微"),("TSM","台積電ADR"),("SMCI","超微電腦"),("PLTR","Palantir")],
    "ETF":     [("SPY","S&P500"),("QQQ","那斯達克"),("VT","全球"),("ARKK","方舟")],
    "其他":    [("TSLA","特斯拉"),("AMZN","亞馬遜"),("META","Meta"),("NFLX","Netflix")],
}
GLOSSARY = {
    "RSI":"相對強弱指標0~100。>70超買（漲太快），<30超賣（跌太多）。",
    "MACD":"動能指標。柱狀圖正值=動能增強；負值=動能減弱。",
    "布林通道":"股價正常波動範圍。通道收窄=大行情即將爆發。",
    "ATR":"每天平均波動多少錢。ATR大=風險高；小=比較穩。",
    "Stochastic KD":"K>80超買，K<20超賣。",
    "OBV能量潮":"OBV上升=資金流入；下降=資金流出。",
    "VWAP":"機構法人的成本均價，現價>VWAP=多方強勢。",
    "費波那契":"黃金比例支撐壓力位，0.618是最重要的位置。",
    "本益比PE":"花多少錢買1元獲利，越低可能越便宜。",
    "ROE":"公司用你的錢賺錢的效率，越高越好。",
    "停損":"跌到設定價位就出場，保護本金最重要工具。",
    "風報比":"預期獲利÷預期虧損，至少要2:1以上。",
    "MDD最大回撤":"從最高點到最低點的最大跌幅，衡量最壞情況。",
    "蒙地卡羅":"用歷史波動率隨機模擬未來數千條可能路徑，顯示機率區間。",
    "VIX恐慌指數":">30=市場極度恐慌；<15=市場過度樂觀。",
    "處置效應":"散戶常見心理偏誤：太早賣出獲利股，太晚出清虧損股。",
    "總體宏觀制度":"指當前全球經濟所處的大環境，如通膨衰退、復甦成長等，影響所有資產走向。",
}
MACRO_REGIMES = ["未知","成長擴張（Risk-On）","通膨衰退（Stagflation）","衰退（Risk-Off）","復甦反彈（Early Cycle）","流動性危機"]

# ══════════════════════════════════════════════
# 8. 工具函數
# ══════════════════════════════════════════════
def get_sym(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"):
        return raw + ".TW"
    return raw

def safe_f(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if v == v else default
    except: return default

def add_recent(sym: str):
    r = st.session_state.recent_searches
    if sym in r: r.remove(sym)
    r.insert(0, sym)
    st.session_state.recent_searches = r[:8]

def fmt_large(v):
    if not isinstance(v,(int,float)): return str(v)
    if abs(v)>=1e12: return f"{v/1e12:.2f}兆"
    if abs(v)>=1e8:  return f"{v/1e8:.1f}億"
    if abs(v)>=1e4:  return f"{v/1e4:.0f}萬"
    return f"{v:,.2f}"

def pct_fmt(v):
    return f"{v*100:.1f}%" if isinstance(v,float) and v==v else "N/A"

# ══════════════════════════════════════════════
# 9. 數據抓取（全域替換為 yf.download 批量下載，徹底解決 429 封鎖）
# ══════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data(symbol: str, period: str):
    try:
        # 使用 download 替代 history，更穩定且支援批量，不易被鎖
        h = yf.download(symbol, period=period, progress=False)
        if h is None or h.empty: 
            return None, None, "查無此代號或暫無數據"
            
        # 處理 yfinance 新版的 MultiIndex 格式
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = [col[0] for col in h.columns]
            
        info = {}
        try:
            # 這是最容易被鎖的端點，加入嚴格 try-except 保護
            t = yf.Ticker(symbol)
            info['longName'] = t.info.get('longName', symbol)
            info['sector'] = t.info.get('sector', '其他')
            info['trailingPE'] = t.info.get('trailingPE', 'N/A')
            info['priceToBook'] = t.info.get('priceToBook', 'N/A')
            info['beta'] = t.info.get('beta', 'N/A')
        except:
            info = {'longName': symbol, 'sector': '其他'}
            
        return h, info, None
    except Exception as e:
        return None, None, f"抓取失敗：{str(e)[:50]}"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_overview():
    syms = {"台灣加權":"^TWII","S&P 500":"^GSPC","那斯達克":"^IXIC",
            "VIX恐慌":"^VIX","費城半導":"^SOX","美元指數":"DX-Y.NYB"}
    tickers = list(syms.values())
    rows = []
    try:
        # 批量下載，發送 1 次請求取代 6 次
        data = yf.download(tickers, period="2d", group_by="ticker", progress=False)
        for name, sym in syms.items():
            try:
                df = data[sym] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
                if not df.empty and len(df)>=2:
                    c1 = float(df["Close"].iloc[-2])
                    c2 = float(df["Close"].iloc[-1])
                    ch = round((c2 - c1) / max(c1, 0.01) * 100, 2)
                    rows.append({"名稱":name, "現值":c2, "漲跌%":ch})
            except: continue
    except: pass
    return sorted(rows, key=lambda x: list(syms.keys()).index(x["名稱"])) if rows else []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_batch_quotes(symbols: tuple) -> dict:
    if not symbols: return {}
    results = {}
    try:
        # 批量下載自選股，只發送 1 次請求
        data = yf.download(list(symbols), period="5d", group_by="ticker", progress=False)
        for sym in symbols:
            try:
                df = data[sym] if len(symbols)>1 else data
                if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
                if not df.empty and len(df)>=2:
                    c1 = float(df["Close"].iloc[-2])
                    c2 = float(df["Close"].iloc[-1])
                    ch = round((c2 - c1) / max(c1, 0.01) * 100, 2)
                    results[sym] = (c2, ch)
                else: results[sym] = (None, None)
            except: results[sym] = (None, None)
    except: pass
    return results

@st.cache_data(ttl=600, show_spinner=False)
def fetch_heatmap_data(market: str) -> pd.DataFrame:
    hot = TW_HOT if "台股" in market else US_HOT
    tickers = []
    sym_map = {}
    for sector, stocks in hot.items():
        for sym_, name_ in stocks:
            full = sym_+".TW" if "台股" in market and not sym_.endswith(".TW") else sym_
            tickers.append(full)
            sym_map[full] = (sector, name_)
            
    rows = []
    if not tickers: return pd.DataFrame()
    
    try:
        # 批量下載，發送 1 次請求取代 16 次，且完全不呼叫最毒的 t.info
        data = yf.download(tickers, period="2d", group_by="ticker", progress=False)
        for full in tickers:
            try:
                df = data[full] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
                if not df.empty and len(df)>=2:
                    c1 = float(df["Close"].iloc[-2])
                    c2 = float(df["Close"].iloc[-1])
                    if c1 > 0:
                        ch = round((c2 - c1) / c1 * 100, 2)
                        sector, name = sym_map[full]
                        rows.append({
                            "板塊": sector, "名稱": name, "代號": full.replace(".TW",""),
                            "漲跌%": ch, "市值": 1e9 # 統一大小以防觸發 429
                        })
            except: continue
    except: pass
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════
# 10. 技術指標計算（15項 + NaN全防護）
# ══════════════════════════════════════════════
def calc_indicators(hist: pd.DataFrame) -> dict:
    c = hist["Close"].squeeze().astype(float)
    h = hist["High"].squeeze().astype(float)
    l = hist["Low"].squeeze().astype(float)
    v = hist["Volume"].squeeze().astype(float)
    n = len(c)

    def _last(s):
        try:
            val = float(s.iloc[-1])
            return val if val==val else 0.0
        except: return 0.0

    ma5   = c.rolling(5).mean()
    ma20  = c.rolling(20).mean()
    ma60  = c.rolling(min(60,n)).mean()
    ema12 = c.ewm(span=12,adjust=False).mean()
    ema26 = c.ewm(span=26,adjust=False).mean()
    macd  = ema12-ema26
    macd_s= macd.ewm(span=9,adjust=False).mean()
    macd_h= macd-macd_s

    d     = c.diff()
    gain  = d.clip(lower=0).rolling(14).mean()
    loss  = (-d.clip(upper=0)).rolling(14).mean()
    rsi   = (100-100/(1+gain/loss.replace(0,1e-10))).clip(0,100)

    r_min = rsi.rolling(14).min(); r_max = rsi.rolling(14).max()
    stk   = (100*(rsi-r_min)/(r_max-r_min+1e-10)).clip(0,100)
    std_  = stk.rolling(3).mean()

    bb_m  = c.rolling(20).mean(); bb_s=c.rolling(20).std()
    bb_u  = bb_m+2*bb_s; bb_l=bb_m-2*bb_s
    bb_pct= ((c-bb_l)/(bb_u-bb_l+1e-10)*100).clip(0,100)
    bb_w  = ((bb_u-bb_l)/(bb_m+1e-10)*100)

    pc    = c.shift(1)
    tr    = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr   = tr.rolling(14).mean()

    obv   = (v*((c.diff()>0).astype(float)*2-1)).fillna(0).cumsum()
    hh    = h.rolling(14).max(); ll_=l.rolling(14).min()
    wr    = (-100*(hh-c)/(hh-ll_+1e-10)).clip(-100,0)
    tp    = (h+l+c)/3
    vwap  = (tp*v).rolling(20).sum()/(v.rolling(20).sum()+1e-10)

    price  = round(_last(c),2)
    atr_v  = round(_last(atr),4)
    if atr_v==0: atr_v = round(price*0.02,2)

    def chg(k):
        if n>k:
            ref=safe_f(c.iloc[-(k+1)])
            return round((price-ref)/max(ref,0.01)*100,2)
        return 0.0

    ind = {
        "price":price,"change_pct":chg(1),"change_5d":chg(5),"change_1m":chg(21),
        "ma5":round(_last(ma5),2),"ma20":round(_last(ma20),2),
        "ma60":round(_last(ma60),2),"vwap":round(_last(vwap),2),
        "rsi":round(_last(rsi),1),"stoch_k":round(_last(stk),1),"stoch_d":round(_last(std_),1),
        "williams_r":round(_last(wr),1),
        "macd":round(_last(macd),4),"macd_sig":round(_last(macd_s),4),"macd_hist":round(_last(macd_h),4),
        "atr":atr_v,
        "bb_upper":round(_last(bb_u),2),"bb_mid":round(_last(bb_m),2),"bb_lower":round(_last(bb_l),2),
        "bb_pct":round(_last(bb_pct),1),"bb_width":round(_last(bb_w),1),
        "volume":int(_last(v)),"vol_ma20":int(_last(v.rolling(20).mean())),
        "obv":round(_last(obv),0),
        "high_52w":round(float(c.rolling(min(252,n)).max().iloc[-1]),2),
        "low_52w": round(float(c.rolling(min(252,n)).min().iloc[-1]),2),
        "_c":c,"_h":h,"_l":l,"_v":v,
        "_rsi":rsi,"_stk":stk,"_macd":macd,"_macd_sig":macd_s,"_macd_h":macd_h,
        "_bb_u":bb_u,"_bb_l":bb_l,"_bb_m":bb_m,
        "_ma5":ma5,"_ma20":ma20,"_ma60":ma60,"_obv":obv,
        "_hist":hist,
    }

    vr = ind["volume"]/max(ind["vol_ma20"],1)
    ind["vol_ratio"] = round(vr,2)
    if vr>=2.5:   ind["vol_desc"]=f"🔥爆量{vr:.1f}倍均量"
    elif vr>=1.5: ind["vol_desc"]=f"📢放量{vr:.1f}倍"
    elif vr>=0.8: ind["vol_desc"]=f"📊正常量{vr:.1f}倍"
    else:         ind["vol_desc"]=f"😴縮量{vr:.1f}倍，訊號可信度低"

    pos=(price-ind["low_52w"])/max(ind["high_52w"]-ind["low_52w"],0.01)*100
    ind["position_52w"]=round(pos,1)

    rv=ind["rsi"]; kv=ind["stoch_k"]; mv=ind["macd_hist"]
    if ind["ma5"]>ind["ma20"]>ind["ma60"] and rv>55 and mv>0:
        ind["status"]="強勢多頭 📈";ind["sc"]="🔴";ind["status_desc"]="均線多頭排列＋RSI偏強＋MACD正值，三重確認多頭。"
    elif ind["ma5"]<ind["ma20"]<ind["ma60"] and rv<45 and mv<0:
        ind["status"]="強勢空頭 📉";ind["sc"]="🟢";ind["status_desc"]="均線空頭排列＋RSI偏弱＋MACD負值，三重確認空頭。"
    elif rv<=30 and kv<20:
        ind["status"]="雙重超賣 🟡";ind["sc"]="🟡";ind["status_desc"]="RSI與Stochastic雙超賣，反彈機率升高，需量能確認。"
    elif rv>=70 and kv>80:
        ind["status"]="雙重超買 🟡";ind["sc"]="🟡";ind["status_desc"]="RSI與Stochastic雙超買，短線獲利了結壓力大。"
    elif abs(ind["ma5"]-ind["ma20"])/max(price,0.01)<0.015:
        ind["status"]="均線糾結蓄勢 ⚪";ind["sc"]="⚪";ind["status_desc"]="均線纏繞，等待突破，大行情可能即將爆發。"
    elif ind["ma5"]>ind["ma20"] and rv>50:
        ind["status"]="短線偏多 🔵";ind["sc"]="🔵";ind["status_desc"]="短均線在長均線上方，RSI偏強，短線多方略佔優勢。"
    else:
        ind["status"]="弱勢盤整 🟠";ind["sc"]="🟠";ind["status_desc"]="走勢疲軟，方向不明，建議觀望。"

    if rv>=80:    ind["rsi_desc"]=f"⚠️ RSI {rv}，嚴重超買"
    elif rv>=70:  ind["rsi_desc"]=f"⚠️ RSI {rv}，超買區"
    elif rv<=20:  ind["rsi_desc"]=f"💡 RSI {rv}，嚴重超賣，留意反彈"
    elif rv<=30:  ind["rsi_desc"]=f"💡 RSI {rv}，超賣區"
    elif rv>=55:  ind["rsi_desc"]=f"✅ RSI {rv}，多方偏強"
    elif rv<=45:  ind["rsi_desc"]=f"⚠️ RSI {rv}，空方偏強"
    else:         ind["rsi_desc"]=f"➡️ RSI {rv}，多空均衡"
    return ind

# ══════════════════════════════════════════════
# 11. 評分
# ══════════════════════════════════════════════
def calc_score(ind: dict, info: dict) -> dict:
    trend = min(30,(8 if ind["ma5"]>ind["ma20"] else 0)+
                   (8 if ind["ma20"]>ind["ma60"] else 0)+
                   (7 if ind["price"]>ind["ma20"] else 0)+
                   (7 if ind["macd_hist"]>0 else 0))
    rv=ind["rsi"]; kv=ind["stoch_k"]; wrv=ind["williams_r"]
    mom=min(25,(10 if 50<=rv<=70 else 8 if rv<30 else 5 if 40<=rv<50 else 3)+
               (8 if 40<=kv<=80 else 5 if kv<20 else 0)+
               (7 if wrv>-50 else 0))
    vr=ind["vol_ratio"]
    vol=min(20,20 if vr>=1.5 and ind["change_pct"]>0 else
               15 if vr>=1.2 and ind["change_pct"]>0 else
               10 if 0.8<=vr<=1.5 else 5)
    pos=ind["position_52w"]
    psc=min(15,15 if 30<=pos<=70 else 12 if pos<20 else 10 if pos<30 or pos<80 else 4)
    bsc=min(10,10 if 20<=ind["bb_pct"]<=80 else 7 if ind["bb_pct"]<20 else 3)
    total=trend+mom+vol+psc+bsc
    if total>=80:   grade,gc="A（優秀）","#ff4444"
    elif total>=65: grade,gc="B（良好）","#ff8800"
    elif total>=50: grade,gc="C（普通）","#ffcc00"
    elif total>=35: grade,gc="D（偏弱）","#88cc44"
    else:           grade,gc="E（警示）","#22aa44"
    return {"total":total,"grade":grade,"gc":gc,
            "trend":trend,"mom":mom,"vol":vol,"pos":psc,"bb":bsc}

# ══════════════════════════════════════════════
# 12. 入場策略
# ══════════════════════════════════════════════
def calc_entry(ind: dict, hist: pd.DataFrame) -> dict:
    c=ind["_c"]; h=ind["_h"]; l=ind["_l"]
    price=ind["price"]; atr=max(ind["atr"],price*0.005)
    n=len(c); w=min(60,n)
    ph=round(float(h.iloc[-w:].max()),2); pl=round(float(l.iloc[-w:].min()),2)
    fr=max(ph-pl,atr)
    fibs={k:round(ph-v*fr,2) for k,v in [("0.236",0.236),("0.382",0.382),("0.500",0.500),("0.618",0.618),("0.786",0.786)]}
    sup1=round(float(l.iloc[-20:].min()),2); sup2=round(float(l.iloc[-w:].min()),2)
    res1=round(float(h.iloc[-20:].max()),2); res2=round(float(h.iloc[-w:].max()),2)
    con_buy=round(min(sup1,fibs["0.382"]),2)
    mod_buy=round((sup1+ind["ma20"])/2,2)
    agg_buy=round(price*0.995,2)
    sl_tight=round(price-1.5*atr,2); sl_normal=round(price-2.5*atr,2)
    sl_wide=round(max(sup2*0.97,price-4*atr),2)
    tp1=round(price+2*atr,2); tp2=round(price+4*atr,2)
    tp3=round(max(res2*1.02,price+6*atr),2)
    rr=round((tp1-mod_buy)/max(mod_buy-sl_normal,0.01),2)
    return dict(fibs=fibs,sup1=sup1,sup2=sup2,res1=res1,res2=res2,
                con_buy=con_buy,mod_buy=mod_buy,agg_buy=agg_buy,
                sl_tight=sl_tight,sl_normal=sl_normal,sl_wide=sl_wide,
                tp1=tp1,tp2=tp2,tp3=tp3,rr=rr,ph=ph,pl=pl,
                atr=atr,lot_cost=round(mod_buy*1000,0))

# ══════════════════════════════════════════════
# 13. 蒙地卡羅模擬（幾何布朗運動）
# ══════════════════════════════════════════════
def monte_carlo_simulation(hist: pd.DataFrame, days: int = 30, simulations: int = 2000) -> dict:
    """Geometric Brownian Motion，30日錐形不確定區間"""
    close = hist["Close"].squeeze().astype(float)
    log_returns = np.log(close / close.shift(1)).dropna()
    mu    = float(log_returns.mean())
    sigma = float(log_returns.std())
    last_price = float(close.iloc[-1])

    dt = 1
    np.random.seed(42)
    rand_matrix = np.random.standard_normal((simulations, days))
    price_matrix = np.zeros((simulations, days))
    price_matrix[:, 0] = last_price * np.exp(
        (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, 0]
    )
    for t in range(1, days):
        price_matrix[:, t] = price_matrix[:, t-1] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, t]
        )

    percentiles = {
        "p02": np.percentile(price_matrix, 2.5, axis=0),
        "p16": np.percentile(price_matrix, 16, axis=0),
        "p50": np.percentile(price_matrix, 50, axis=0),
        "p84": np.percentile(price_matrix, 84, axis=0),
        "p97": np.percentile(price_matrix, 97.5, axis=0),
    }
    future_dates = [hist.index[-1] + timedelta(days=i+1) for i in range(days)]
    return {"dates": future_dates, "pcts": percentiles,
            "last": last_price, "mu": mu, "sigma": sigma,
            "matrix_sample": price_matrix[:50]}

# ══════════════════════════════════════════════
# 14. Screener（技術面篩選）
# ══════════════════════════════════════════════
def run_screener(symbols: list, conditions: dict) -> list:
    """多條件批量篩選，ThreadPoolExecutor 加速"""
    results = []
    def _check(sym):
        try:
            h, info, err = fetch_data(sym, "3mo")
            if err or h is None: return None
            ind = calc_indicators(h)
            # 條件判斷
            ok = True
            if conditions.get("rsi_lt") and ind["rsi"] >= conditions["rsi_lt"]: ok=False
            if conditions.get("rsi_gt") and ind["rsi"] <= conditions["rsi_gt"]: ok=False
            if conditions.get("macd_cross_up") and ind["macd_hist"] <= 0: ok=False
            if conditions.get("above_ma20") and ind["price"] <= ind["ma20"]: ok=False
            if conditions.get("vol_spike") and ind["vol_ratio"] < 1.5: ok=False
            if conditions.get("bb_near_lower") and ind["bb_pct"] > 25: ok=False
            if ok:
                return {"代號":sym,"現價":ind["price"],
                        "RSI":ind["rsi"],"MACD_H":ind["macd_hist"],
                        "量比":ind["vol_ratio"],"狀態":ind["status"],
                        "評分":calc_score(ind,info)["total"]}
        except: pass
        return None
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_check,s) for s in symbols]
        for f in as_completed(futs):
            r = f.result()
            if r: results.append(r)
    return sorted(results, key=lambda x: x["評分"], reverse=True)

# ══════════════════════════════════════════════
# 15. DCA 回測
# ══════════════════════════════════════════════
def run_dca(symbol: str, monthly_amount: float, years: int):
    hist, _, err = fetch_data(symbol, f"{years}y")
    if err or hist is None: return None, None, err
    hist = hist.copy()
    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz: hist.index = hist.index.tz_localize(None)
    hist["ym"] = hist.index.to_period("M")
    monthly = hist.groupby("ym").first()
    recs=[]; total_inv=0.0; total_sh=0.0
    for period_lbl, row in monthly.iterrows():
        price=float(row["Close"])
        if price<=0: continue
        total_sh+=monthly_amount/price; total_inv+=monthly_amount
        recs.append({"date":period_lbl.to_timestamp(),"累積投入":total_inv,"資產現值":total_sh*price})
    if not recs: return None, None, "無足夠歷史數據"
    df=pd.DataFrame(recs).set_index("date")
    fv=df["資產現值"].iloc[-1]; rtn=round((fv-total_inv)/max(total_inv,0.01)*100,2)
    peak=df["資產現值"].cummax(); dd=(df["資產現值"]-peak)/(peak+1e-10)*100
    mdd=round(dd.min(),2)
    stats={"總投入本金":round(total_inv,0),"最終資產現值":round(fv,0),
           "累積報酬率":f"{rtn:+.2f}%","年化報酬率":f"{rtn/max(years,1):+.2f}%",
           "最大回撤MDD":f"{mdd:.2f}%","回測年限":f"{years}年","每月投入":f"{monthly_amount:,.0f}元"}
    return df, stats, None

# ══════════════════════════════════════════════
# 16. 行為偏誤分析（處置效應）
# ══════════════════════════════════════════════
def analyze_behavioral_bias(trades: list) -> dict:
    if len(trades) < 3: return {}
    wins  = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    loses = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
    if not wins or not loses: return {}

    def hold_days(t):
        try: return (date.fromisoformat(t.get("exit_date",""))-date.fromisoformat(t.get("entry_date",""))).days
        except: return 0

    avg_win_pct  = sum(t.get("pnl_pct",0) for t in wins)/len(wins)
    avg_loss_pct = sum(abs(t.get("pnl_pct",0)) for t in loses)/len(loses)
    avg_win_days  = sum(hold_days(t) for t in wins)/len(wins)
    avg_loss_days = sum(hold_days(t) for t in loses)/len(loses)

    disposition = avg_loss_days > avg_win_days * 1.3 and avg_loss_pct > avg_win_pct
    return {
        "win_count": len(wins), "lose_count": len(loses),
        "avg_win_pct": round(avg_win_pct,2),
        "avg_loss_pct": round(avg_loss_pct,2),
        "avg_win_days": round(avg_win_days,1),
        "avg_loss_days": round(avg_loss_days,1),
        "disposition_effect": disposition,
        "win_rate": round(len(wins)/len(trades)*100,1),
    }

# ══════════════════════════════════════════════
# 17. 加權平均成本（多次買入同一股票）
# ══════════════════════════════════════════════
def weighted_avg_cost(entries: list) -> dict:
    """entries = [{"price":xx,"shares":xx}, ...]"""
    total_cost = sum(e["price"]*e["shares"] for e in entries)
    total_shares= sum(e["shares"] for e in entries)
    if total_shares==0: return {"avg_cost":0,"total_shares":0,"total_cost":0}
    return {"avg_cost":round(total_cost/total_shares,4),
            "total_shares":total_shares,"total_cost":round(total_cost,2)}

# ══════════════════════════════════════════════
# 18. Gemini AI（自動切換模型）
# ══════════════════════════════════════════════
def call_ai(api_key: str, prompt: str, use_search: bool = False) -> str:
    client = genai.Client(api_key=api_key)
    models = [("gemini-2.5-flash","Gemini 2.5 Flash"),
              ("gemini-2.0-flash","Gemini 2.0 Flash"),
              ("gemini-2.0-flash-lite","Gemini Flash Lite")]
    last_err = None
    for mid, mname in models:
        try:
            if use_search:
                cfg = genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.2)
                resp = client.models.generate_content(model=mid,contents=prompt,config=cfg)
            else:
                resp = client.models.generate_content(model=mid,contents=prompt)
            tag = "＋🔍即時搜尋" if use_search else ""
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
            return f"> 🤖 {mname}{tag}　｜　{ts}\n\n{resp.text}"
        except Exception as e:
            err=str(e)
            if any(k in err for k in ["quota","429","RESOURCE_EXHAUSTED","404","not found"]):
                last_err=err[:80]; continue
            raise
    raise Exception(f"所有模型均無法使用：{last_err}")

# ══════════════════════════════════════════════
# 19. AI Prompts（三方辯論 + 宏觀制度過濾）
# ══════════════════════════════════════════════
def ai_macro_regime(api_key: str) -> str:
    """先確認當前宏觀制度"""
    prompt = """請即時搜尋並判斷當前（本週）全球總體經濟所處的宏觀制度（Macro Regime）。

從以下選項選擇最符合的一個並說明理由（50字以內）：
- 成長擴張（Risk-On）
- 通膨衰退（Stagflation）
- 衰退（Risk-Off）
- 復甦反彈（Early Cycle）
- 流動性危機

格式（嚴格遵守）：
**制度：** [選項名稱]
**理由：** [50字以內說明，包含聯準會動向、GDP、通膨數據]

禁止廢話。繁體中文。"""
    return call_ai(api_key, prompt, use_search=True)

def ai_three_agent_debate(ind, info, sym, api_key, entry, score, macro_regime) -> tuple:
    """三方辯論：多頭 vs 空頭 vs CIO裁判"""
    co  = info.get("longName") or info.get("shortName") or sym
    atr = entry["atr"]
    bull_range = f"{round(ind['price']+1.5*atr,2)}"
    bear_range = f"{round(ind['price']-1.5*atr,2)}"

    base_data = f"""
股票：{co}（{sym}）｜現價：{ind['price']}｜今日：{ind['change_pct']}%｜月：{ind['change_1m']}%
評分：{score['total']}/100（{score['grade']}）｜狀態：{ind['status']}
MA5={ind['ma5']} MA20={ind['ma20']} MA60={ind['ma60']}
RSI={ind['rsi']} StochK={ind['stoch_k']} Williams%R={ind['williams_r']}
MACD_H={ind['macd_hist']} ATR={atr} OBV={'↑' if ind['obv']>0 else '↓'}
布林位置={ind['bb_pct']:.0f}% {ind['vol_desc']} 52W位置={ind['position_52w']}%
支撐={entry['sup1']}/{entry['sup2']} 壓力={entry['res1']}/{entry['res2']}
PE={info.get('trailingPE','N/A')} PB={info.get('priceToBook','N/A')} Beta={info.get('beta','N/A')}
**當前宏觀制度：{macro_regime}**
    """

    # ── 多頭代理人 ──
    bull_prompt = f"""你是一位狂熱的多頭分析師（Permabull Agent）。你的任務是找出所有看漲理由，並做最強力的多頭辯護。

{base_data}

宏觀制度懲罰/獎勵規則：
- 若制度為「成長擴張」或「復甦反彈」→ 多頭論點信心加成+20%
- 若制度為「通膨衰退」或「衰退」→ 你的論點需特別強調防禦性與超賣反彈邏輯
- 若制度為「流動性危機」→ 你必須承認大環境不利，但找個股alpha

請即時搜尋最新正面消息後，輸出（禁止廢話、條列式、繁體中文）：

## 🔴 多頭論點（Permabull）
- **核心催化劑**：（搜尋最新正面消息，條列3點）
- **技術面多頭證據**：（從15項指標中找最強的3個多頭訊號）
- **ATR多頭情境**：明日若多方主導，目標 **{bull_range}**（說明技術依據）
- **宏觀制度加分**：在「{macro_regime}」環境下，為什麼這支股票仍有機會？
- **多頭信心評級**：⬛/5（說明理由）

不得提任何空頭觀點。禁止「一定」「保證」「必漲」。"""

    # ── 空頭代理人 ──
    bear_prompt = f"""你是一位極度悲觀的空頭分析師（Ruthless Bear Agent）。你的任務是無情揭露所有看跌風險，做最嚴酷的空頭論證。

{base_data}

宏觀制度懲罰/獎勵規則：
- 若制度為「通膨衰退」或「衰退」或「流動性危機」→ 空頭論點信心加成+20%
- 若制度為「成長擴張」→ 你需要找個股特定風險和技術面超買訊號
- 所有宏觀制度下，你都必須指出聯準會政策風險和地緣政治黑天鵝

請即時搜尋最新負面消息後，輸出（禁止廢話、條列式、繁體中文）：

## 🟢 空頭論點（Ruthless Bear）
- **核心威脅**：（搜尋最新負面消息/風險，條列3點）
- **技術面空頭證據**：（從15項指標中找最強的3個空頭訊號）
- **ATR空頭情境**：明日若空方主導，目標 **{bear_range}**（說明技術依據）
- **宏觀制度懲罰**：在「{macro_regime}」環境下，為什麼這支股票面臨更大風險？
- **黑天鵝事件**：最可能摧毀多頭論點的1個具體風險
- **空頭信心評級**：⬛/5

不得提任何多頭觀點。禁止「一定」「保證」「必跌」。"""

    # ── CIO裁判 ──
    judge_prompt = f"""你是一位冷靜理性的投資長（CIO Judge）。你已收到多頭和空頭的辯論報告，現在做出最終裁決。

{base_data}

**宏觀制度裁決規則（必須執行）：**
- 「成長擴張」→ 給多頭+10%信心加成
- 「通膨衰退/衰退」→ 給空頭+15%信心加成，要求更高的安全邊際
- 「流動性危機」→ 直接評為觀望，除非有極強防禦性
- 「復甦反彈」→ 給多頭+5%，但提醒反彈幅度有限

ATR計算參數：現價={ind['price']}，ATR={atr}
樂觀情境：{round(ind['price']+1.5*atr,2)}，悲觀情境：{round(ind['price']-1.5*atr,2)}，中性：{round(ind['price']-0.5*atr,2)}～{round(ind['price']+0.5*atr,2)}

輸出（禁止廢話、條列式、繁體中文）：

## 🟣 CIO最終裁決
- **多空力道對比**：多頭論點強度X/10 vs 空頭論點強度Y/10
- **宏觀制度影響**：在「{macro_regime}」環境下的最終加減分評估
- **最終方向裁決**：偏多/偏空/中性觀望（必須明確，附理由）
- **明日精準預測**（嚴格基於ATR={atr}，不超過±3倍ATR）：
  - 最可能情境：___～___ 
  - 關鍵多方守位：**{entry['sup1']}**（跌破=空方勝）
  - 關鍵空方突破：**{entry['res1']}**（帶量突破=多方勝）
- **投資建議**（⚠️僅供參考不構成投資建議）：
  - 穩健買入區：{entry['mod_buy']}｜停損：{entry['sl_normal']}｜T1：{entry['tp1']}｜風報比：{entry['rr']}:1
  - 台股一張≈{entry['lot_cost']:,.0f}元
- **信心評級**：⬛/5（說明）
- **新手一句話**：（用最簡單的語言告訴小白現在應該怎麼對待這支股票）

禁止「一定」「保證」「必漲」「必跌」。"""

    # 三路並發（但 Streamlit 中需Sequential避免rate limit）
    bull_rpt = call_ai(api_key, bull_prompt, use_search=True)
    bear_rpt = call_ai(api_key, bear_prompt, use_search=True)
    judge_rpt= call_ai(api_key, judge_prompt, use_search=False)
    return bull_rpt, bear_rpt, judge_rpt

def ai_portfolio_cio(portfolio_data: str, sector_data: str, api_key: str) -> str:
    prompt = f"""你是一位極度嚴苛的投資長（CIO），負責審查以下客戶的整體投資組合並強制執行「汰弱留強」。

{portfolio_data}

板塊分佈：{sector_data}

請即時搜尋各持股最新動態後，輸出（繁體中文、條列式、禁止廢話）：

## 🏦 組合健康診斷
- 板塊集中度風險（某板塊>40%則視為過度集中）
- 整體多空配置評估
- Beta加權組合波動度估算

## ⚔️ 汰弱留強建議
（對每支持股給出：繼續持有/減碼/立即清倉，附一句話理由）

## 🔄 組合優化建議
- 應該移除的1~2支最弱標的（附具體理由）
- 可以加倉的1~2支最強標的（附具體理由）
- 是否需要加入防禦性資產對沖？

## ⚠️ 新手常見組合錯誤
（針對此組合的3個具體問題）

禁止「一定」「保證」「必漲」「必跌」。"""
    return call_ai(api_key, prompt, use_search=True)

def ai_entry_critique(sym, co, buy_price, buy_date, ind_at_buy, current_price, api_key) -> str:
    prompt = f"""你是一位無情的交易教練，對以下買入點進行事後覆盤（Post-Mortem）。

**交易資訊：**
股票：{co}（{sym}）
買入日期：{buy_date}｜買入價：{buy_price}｜現價：{current_price}
損益：{round((current_price-buy_price)/max(buy_price,0.01)*100,2):+.2f}%

**買入當日技術面（重建）：**
{ind_at_buy}

請輸出（繁體中文、條列式、禁止廢話）：

## 🔬 買點覆盤診斷
- 買入時技術面評估（合理/偏早/偏晚/嚴重錯誤）
- 哪個指標支持買入？哪個指標反對？
- 如果用現在的系統評分，當時可能得幾分？

## 🎯 當前持股處置建議
**明確選擇一個（必須）：A.繼續持有 / B.移動停利 / C.停損出場**
- 選擇理由（技術面為主，3點）
- 具體操作：止損價/移動停利位/加碼條件

## 🧠 心理偏誤提醒
（根據此交易，診斷可能存在的心理偏誤，如處置效應、確認偏誤等）

禁止廢話開場白。禁止「一定」「保證」。"""
    return call_ai(api_key, prompt, use_search=False)

def ai_bias_warning(bias_data: dict, trades_summary: str, api_key: str) -> str:
    disposition = bias_data.get("disposition_effect", False)
    prompt = f"""你是行為財務學專家，分析以下投資人的交易記錄，診斷心理偏誤。

交易統計：
- 總交易次數：{bias_data.get('win_count',0)+bias_data.get('lose_count',0)}
- 勝率：{bias_data.get('win_rate',0)}%
- 平均獲利幅度：+{bias_data.get('avg_win_pct',0):.2f}%
- 平均虧損幅度：-{bias_data.get('avg_loss_pct',0):.2f}%
- 平均持有獲利股天數：{bias_data.get('avg_win_days',0):.0f}天
- 平均持有虧損股天數：{bias_data.get('avg_loss_days',0):.0f}天
- 處置效應診斷：{'⚠️ 是（持虧損股時間顯著長於持獲利股）' if disposition else '✅ 未明顯發現'}

近期交易記錄：
{trades_summary}

請輸出（繁體中文、條列式）：

## 🧠 行為偏誤診斷報告
{'## ⚠️ 嚴重警告：偵測到處置效應（Disposition Effect）！' if disposition else ''}
- 你的交易數據顯示：（說明具體數字問題）
- 最可能的3個心理偏誤（附白話解釋）
- 這樣的行為模式，長期會如何影響報酬？

## 💊 矯正方案
- 3個具體的交易紀律改善方法
- 建議設立的強制規則（如：任何交易最大虧損不超過X%）

禁止廢話開場白。"""
    return call_ai(api_key, prompt, use_search=False)

# ══════════════════════════════════════════════
# 20. 圖表（台灣色系：紅漲綠跌）
# ══════════════════════════════════════════════
DARK = "plotly_dark"
TW_UP   = "#ff3333"   # 台灣：紅色=漲
TW_DOWN = "#22cc44"   # 台灣：綠色=跌

def build_main_chart(hist, ind, entry, sym, mc_data=None, buy_markers=None):
    """主圖表：K線+均線+布林+蒙地卡羅+買入標記"""
    idx = hist.index
    rows = 4; heights = [0.50,0.18,0.17,0.15]
    titles = ["K線+均線+布林（台灣色系：紅漲綠跌）","成交量","RSI+Stochastic","MACD"]
    if mc_data:
        rows=5; heights=[0.42,0.18,0.15,0.13,0.12]
        titles.append("蒙地卡羅模擬（30日錐形區間）")

    fig = make_subplots(rows=rows,cols=1,shared_xaxes=True,
                        row_heights=heights,subplot_titles=titles,vertical_spacing=0.03)

    # ── K線（台灣色系）──
    fig.add_trace(go.Candlestick(
        x=idx,open=hist["Open"],high=hist["High"],
        low=hist["Low"],close=hist["Close"],name="K線",
        increasing_line_color=TW_UP,   # 紅=漲
        decreasing_line_color=TW_DOWN, # 綠=跌
        increasing_fillcolor=TW_UP,
        decreasing_fillcolor=TW_DOWN,
    ),row=1,col=1)

    # 均線
    for key,color,nm in [("_ma5","#FFA726","MA5"),("_ma20","#42A5F5","MA20"),("_ma60","#AB47BC","MA60")]:
        fig.add_trace(go.Scatter(x=idx,y=ind[key],line=dict(color=color,width=1.3),name=nm),row=1,col=1)

    # 布林通道
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_u"],
        line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林上",showlegend=False),row=1,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_l"],
        line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林下",showlegend=False,
        fill="tonexty",fillcolor="rgba(255,235,59,0.04)"),row=1,col=1)

    # 支撐壓力
    for y_val,color,label in [
        (entry["sup1"],"rgba(34,204,68,0.8)",f"支撐 {entry['sup1']}"),
        (entry["res1"],"rgba(255,51,51,0.8)", f"壓力 {entry['res1']}"),
        (entry["mod_buy"],"rgba(255,200,50,0.8)",f"參考買入 {entry['mod_buy']}"),
    ]:
        fig.add_hline(y=y_val,line_dash="dash",line_color=color,
                      annotation_text=label,annotation_font_size=10,row=1,col=1)

    # 買入標記
    if buy_markers:
        for bm in buy_markers:
            fig.add_trace(go.Scatter(
                x=[bm["date"]],y=[bm["price"]],
                mode="markers+text",
                marker=dict(symbol="triangle-up",size=14,color="#FFD700",line=dict(color="#FF8C00",width=2)),
                text=[f"買入\n{bm['price']}"],textposition="bottom center",
                textfont=dict(color="#FFD700",size=10),
                name=f"買入 {bm['price']}",showlegend=True,
            ),row=1,col=1)

    # 成交量（台灣色系）
    vc=[TW_UP if c>=o else TW_DOWN for c,o in zip(hist["Close"],hist["Open"])]
    fig.add_trace(go.Bar(x=idx,y=ind["_v"],marker_color=vc,showlegend=False),row=2,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_v"].rolling(20).mean(),
        line=dict(color="#FFA726",width=1.2),showlegend=False),row=2,col=1)

    # RSI + Stochastic
    fig.add_trace(go.Scatter(x=idx,y=ind["_rsi"],line=dict(color="#FF7043",width=1.5),name="RSI",showlegend=False),row=3,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_stk"],line=dict(color="#66BB6A",width=1,dash="dot"),name="StochK",showlegend=False),row=3,col=1)
    for lv,lc in [(70,"rgba(255,51,51,0.4)"),(50,"rgba(150,150,150,0.3)"),(30,"rgba(34,204,68,0.4)")]:
        fig.add_hline(y=lv,line_dash="dash",line_color=lc,row=3,col=1)

    # MACD（台灣色系）
    mc_c=[TW_UP if x>=0 else TW_DOWN for x in ind["_macd_h"]]
    fig.add_trace(go.Bar(x=idx,y=ind["_macd_h"],marker_color=mc_c,showlegend=False),row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd"],line=dict(color="#42A5F5",width=1),showlegend=False),row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd_sig"],line=dict(color="#FF7043",width=1),showlegend=False),row=4,col=1)

    # 蒙地卡羅（第5列）
    if mc_data:
        mc_row = 5
        fd = mc_data["dates"]
        p = mc_data["pcts"]
        fig.add_trace(go.Scatter(x=fd,y=p["p97"],line=dict(color="rgba(255,200,50,0.3)",width=1),
            showlegend=False,name="95%上界"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p02"],line=dict(color="rgba(255,200,50,0.3)",width=1),
            showlegend=False,fill="tonexty",fillcolor="rgba(255,200,50,0.08)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p84"],line=dict(color="rgba(100,180,255,0.5)",width=1),
            showlegend=False,name="68%上界"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p16"],line=dict(color="rgba(100,180,255,0.5)",width=1),
            showlegend=False,fill="tonexty",fillcolor="rgba(100,180,255,0.12)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p50"],line=dict(color="#FFD700",width=2),
            name="中位數路徑"),row=mc_row,col=1)
        # 加幾條樣本路徑
        for path in mc_data["matrix_sample"][:5]:
            fig.add_trace(go.Scatter(x=fd,y=path,
                line=dict(color="rgba(200,200,200,0.1)",width=0.5),showlegend=False),row=mc_row,col=1)

    fig.update_layout(template=DARK,title=f"{sym} 技術分析（🔴漲 🟢跌）",
                      height=900 if mc_data else 780,
                      xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h",y=1.02,font_size=11),
                      margin=dict(l=50,r=50,t=80,b=30))
    return fig

def build_heatmap_chart(df: pd.DataFrame, market: str):
    """板塊熱力圖（台灣色系）"""
    if df.empty: return None
    fig = px.treemap(df,path=["板塊","名稱"],values="市值",
        color="漲跌%",
        color_continuous_scale=[(0.0,TW_DOWN),(0.5,"#333333"),(1.0,TW_UP)],  # 台灣色系
        color_continuous_midpoint=0,
        custom_data=["代號","漲跌%"],
        title=f"{'台股' if '台股' in market else '美股'} 板塊熱力圖（🔴漲 🟢跌）",
        template=DARK)
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[1]:.2f}%",
        textfont_size=13,
    )
    fig.update_layout(height=550,margin=dict(l=10,r=10,t=60,b=10),
                      coloraxis_colorbar=dict(title="漲跌%"))
    return fig

def build_portfolio_sunburst(portfolio: dict, sector_map: dict) -> go.Figure:
    """持股板塊旭日圖"""
    rows = []
    for sym,data in portfolio.items():
        cost_val = data["cost"]*data["shares"]
        sector   = sector_map.get(sym,"其他")
        rows.append({"板塊":sector,"代號":sym,"市值":cost_val})
    if not rows: return None
    df = pd.DataFrame(rows)
    fig = px.sunburst(df,path=["板塊","代號"],values="市值",
        title="持股板塊旭日圖（方塊大小=持倉成本）",template=DARK,
        color_discrete_sequence=px.colors.qualitative.Set3)
    fig.update_layout(height=450,margin=dict(l=10,r=10,t=60,b=10))
    return fig

def build_dca_chart(df_dca: pd.DataFrame, sym: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["累積投入"],
        fill="tozeroy",name="累積投入本金",
        line=dict(color="#42A5F5",width=2),fillcolor="rgba(66,165,245,0.15)"))
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["資產現值"],
        fill="tozeroy",name="資產現值",
        line=dict(color=TW_UP,width=2),fillcolor="rgba(255,51,51,0.15)"))
    fig.update_layout(template=DARK,title=f"{sym} 定期定額回測",
                      yaxis_title="金額（元）",height=420,
                      legend=dict(orientation="h",y=1.02),
                      margin=dict(l=50,r=30,t=60,b=30))
    return fig

def build_mc_standalone(mc_data: dict, sym: str) -> go.Figure:
    """獨立蒙地卡羅圖"""
    fig = go.Figure()
    fd = mc_data["dates"]; p = mc_data["pcts"]
    fig.add_trace(go.Scatter(x=fd,y=p["p97"],line=dict(color="rgba(255,200,50,0.3)",width=1),name="95%區間上界"))
    fig.add_trace(go.Scatter(x=fd,y=p["p02"],line=dict(color="rgba(255,200,50,0.3)",width=1),
        name="95%區間下界",fill="tonexty",fillcolor="rgba(255,200,50,0.08)"))
    fig.add_trace(go.Scatter(x=fd,y=p["p84"],line=dict(color="rgba(100,180,255,0.5)",width=1),name="68%區間上界"))
    fig.add_trace(go.Scatter(x=fd,y=p["p16"],line=dict(color="rgba(100,180,255,0.5)",width=1),
        name="68%區間下界",fill="tonexty",fillcolor="rgba(100,180,255,0.12)"))
    fig.add_trace(go.Scatter(x=fd,y=p["p50"],line=dict(color="#FFD700",width=2.5),name="中位數路徑"))
    for i,path in enumerate(mc_data["matrix_sample"][:20]):
        fig.add_trace(go.Scatter(x=fd,y=path,
            line=dict(color="rgba(200,200,200,0.07)",width=0.5),showlegend=False))
    fig.add_hline(y=mc_data["last"],line_dash="dash",line_color="rgba(255,255,255,0.5)",
                  annotation_text="現價")
    fig.update_layout(template=DARK,title=f"{sym} 蒙地卡羅30日模擬（幾何布朗運動，2000條路徑）",
                      yaxis_title="預估價格",height=450,
                      legend=dict(orientation="h",y=1.02),
                      margin=dict(l=50,r=30,t=70,b=30))
    return fig

# ══════════════════════════════════════════════
# 21. 側邊欄
# ══════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定")
    db_icon = "🟢 雲端已連線" if HAS_DB else "🟡 本機模式"
    st.caption(db_icon)

    st.divider()
    st.header("👤 個人帳號")
    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號", placeholder="英文+數字", key="sb_u",
                                  help="自訂帳號，登入後資料雲端永久保存")
            upin  = st.text_input("密碼", type="password", key="sb_p",
                                  help="請牢記密碼，系統無法找回")
            ca, cb = st.columns(2)
            with ca:
                if st.button("🔑 登入", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok,uid,enc = db_verify_user(uname.strip(),upin.strip())
                        if ok:
                            st.session_state.user_id   = uid
                            st.session_state.username  = uname.strip()
                            st.session_state._pin      = upin.strip()
                            st.session_state.logged_in = True
                            st.session_state.watchlist = db_load_wl(uid)
                            st.session_state.alerts    = db_load_alerts(uid)
                            st.session_state.portfolio = db_load_port(uid)
                            st.session_state.trade_history = db_load_trades(uid)
                            if enc:
                                dec = decrypt_key(enc, upin.strip())
                                if dec: st.session_state.api_key = dec
                            st.success(f"✅ 歡迎，{uname}！")
                            st.rerun()
                        else: st.error("❌ 帳號或密碼錯誤")
            with cb:
                if st.button("✨ 建立", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok,uid,msg = db_create_user(uname.strip(),upin.strip())
                        if ok:
                            st.session_state.user_id=uid; st.session_state.username=uname.strip()
                            st.session_state._pin=upin.strip(); st.session_state.logged_in=True
                            st.success(f"✅ {msg}"); st.rerun()
                        else: st.error(f"❌ {msg}")
    else:
        st.success(f"👤 {st.session_state.username}")
        st.caption("✅ 雲端同步" if HAS_DB else "⚠️ 本機模式")
        if st.button("🚪 登出", use_container_width=True):
            for k in ["user_id","username","logged_in","api_key","_pin"]:
                st.session_state[k] = False if k=="logged_in" else "" if k in ["api_key","_pin"] else None
            for k in ["watchlist","trade_history"]: st.session_state[k]=[]
            for k in ["alerts","portfolio"]: st.session_state[k]={}
            st.rerun()

    # API Key
    st.divider()
    if st.session_state.logged_in and st.session_state.api_key:
        st.success("🔑 API 金鑰已自動帶入")
        if st.button("🔄 更換金鑰"):
            st.session_state.api_key=""; st.rerun()
        api_key = st.session_state.api_key
    else:
        api_key_in = st.text_input("🔑 Gemini API 金鑰",type="password",placeholder="AIza...",
            help="至 aistudio.google.com 免費取得。登入後加密儲存，下次自動帶入。",
            value=st.session_state.api_key)
        if api_key_in and api_key_in!=st.session_state.api_key:
            st.session_state.api_key=api_key_in
            if st.session_state.logged_in and HAS_DB:
                db_save_enc_key(st.session_state.username,st.session_state._pin,api_key_in)
                st.success("🔒 已加密儲存")
        api_key = st.session_state.api_key

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("市場",["🇹🇼 台股","🇺🇸 美股"],
                      help="選台股會自動加上 .TW 後綴")
    period = st.selectbox("分析區間",["3mo","6mo","1y","2y"],index=1,
        format_func=lambda x:{"3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年"}[x],
        help="區間越長，趨勢判斷越可靠")
    st.caption("⏱️ 數據每5分鐘更新")

    # 宏觀制度
    st.divider()
    st.header("🌍 宏觀制度設定")
    macro_regime = st.selectbox("當前宏觀制度",MACRO_REGIMES,
        index=MACRO_REGIMES.index(st.session_state.macro_regime),
        help="宏觀制度會影響AI三方辯論的加減分邏輯",key="macro_sel")
    st.session_state.macro_regime = macro_regime
    if api_key and st.button("🔍 AI自動偵測制度",use_container_width=True):
        with st.spinner("搜尋中..."):
            try:
                regime_rpt = ai_macro_regime(api_key)
                # 嘗試解析
                for r in MACRO_REGIMES[1:]:
                    if r in regime_rpt:
                        st.session_state.macro_regime=r
                        macro_regime=r; break
                st.success(f"✅ 制度偵測完成：{st.session_state.macro_regime}")
                with st.expander("查看AI制度分析"): st.markdown(regime_rpt)
            except Exception as e: st.error(str(e)[:50])

    # 自選股
    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號",placeholder="如2330或AAPL",key="sb_nw",
                       help="輸入後按Enter新增")
    if nw and nw.strip():
        sa=get_sym(nw.strip(),market)
        if sa not in st.session_state.watchlist:
            st.session_state.watchlist.append(sa)
            if st.session_state.logged_in: db_add_wl(st.session_state.user_id,sa)
            st.rerun()
    for i,s in enumerate(st.session_state.watchlist):
        c1,c2=st.columns([4,1])
        c1.write(f"• {s}")
        if c2.button("❌",key=f"dw_{i}_{s}"):
            if st.session_state.logged_in: db_del_wl(st.session_state.user_id,s)
            st.session_state.watchlist.pop(i); st.rerun()

    # 警報
    st.divider()
    st.header("🔔 警報")
    al_s=st.text_input("代號",key="al_s",help="設定到達特定價格時提醒")
    al_u=st.number_input("↑漲破提醒",0.0,step=0.5,help="漲到此價出現紅色警報")
    al_d=st.number_input("↓跌破提醒",0.0,step=0.5,help="跌到此價出現警報")
    if st.button("✅ 設定",use_container_width=True):
        if al_s.strip():
            sa2=get_sym(al_s.strip(),market)
            st.session_state.alerts[sa2]={"above":al_u or None,"below":al_d or None}
            if st.session_state.logged_in: db_save_alert(st.session_state.user_id,sa2,al_u,al_d)
            st.success("✅")
    for sa3,av in list(st.session_state.alerts.items()):
        pts=[f"↑{av['above']}" if av.get("above") else "",f"↓{av['below']}" if av.get("below") else ""]
        pts=[p for p in pts if p]
        c1a,c2a=st.columns([4,1])
        c1a.caption(f"• {sa3}: {' '.join(pts)}")
        if c2a.button("❌",key=f"dal_{sa3}"):
            if st.session_state.logged_in: db_del_alert(st.session_state.user_id,sa3)
            del st.session_state.alerts[sa3]; st.rerun()

    # 名詞解釋
    st.divider()
    st.header("📖 名詞解釋")
    for term,desc in GLOSSARY.items():
        with st.expander(term): st.info(desc)

# ══════════════════════════════════════════════
# 22. 主頁面
# ══════════════════════════════════════════════
st.title("📈 股市小白分析系統 Pro V2")
st.caption("AI三方辯論 × 蒙地卡羅模擬 × 行為偏誤診斷 × 機構級量化 × 🔴紅漲🟢跌（台灣色系）")

# 大盤列
mkt = fetch_market_overview()
if mkt:
    mcols = st.columns(len(mkt))
    for col,row in zip(mcols,mkt):
        chg=row["漲跌%"]
        col.metric(row["名稱"],str(row["現值"]),
            f"{'▲' if chg>=0 else '▼'}{abs(chg):.2f}%",
            delta_color="inverse")  # 台灣色系：inverse

# 最近查詢
if st.session_state.recent_searches:
    st.markdown("**🕐 最近查詢：**")
    rc=st.columns(min(len(st.session_state.recent_searches),8))
    for i,rs in enumerate(st.session_state.recent_searches):
        if rc[i].button(rs,key=f"rc_{i}"):
            st.session_state.quick_sym=rs.replace(".TW","")
            st.session_state.auto_analyze=True; st.rerun()

# 宏觀制度橫幅
regime_colors={"成長擴張（Risk-On）":"#cc2222","復甦反彈（Early Cycle）":"#aa3333",
               "通膨衰退（Stagflation）":"#446644","衰退（Risk-Off）":"#228844",
               "流動性危機":"#4422aa","未知":"#444444"}
rc=regime_colors.get(macro_regime,"#444444")
st.markdown(f"""<div style="background:{rc};border-radius:8px;padding:8px 16px;margin:6px 0;text-align:center">
    <span style="color:white;font-weight:bold">🌍 當前宏觀制度：{macro_regime}</span>
    <span style="color:rgba(255,255,255,0.7);font-size:12px;margin-left:12px">（影響AI三方辯論加減分）</span>
</div>""",unsafe_allow_html=True)

st.divider()

TABS = st.tabs(["📊 個股戰情室","💼 我的資產庫","📊 選股+回測","🗺️ 市場總覽","🧠 交易心理診斷"])

# ══════════════════════════════════════════════
# TAB 1：個股戰情室
# ══════════════════════════════════════════════
with TABS[0]:
    # 快速選股
    st.markdown("### 🚀 快速選股")
    hot = TW_HOT if "台股" in market else US_HOT
    for cat,stocks in hot.items():
        st.caption(f"**{cat}**")
        qcols=st.columns(len(stocks))
        for col,(sym_,name_) in zip(qcols,stocks):
            if col.button(f"{sym_}\n{name_}",use_container_width=True,key=f"qs_{sym_}_{cat}"):
                st.session_state.quick_sym=sym_; st.session_state.auto_analyze=True; st.rerun()

    st.divider()
    ic1,ic2 = st.columns([3,1])
    with ic1:
        ticker_in = st.text_input("輸入股票代號",
            value=st.session_state.quick_sym or "",
            placeholder="台股如2330，美股如NVDA",
            help="台股輸入數字代號，美股輸入英文，系統自動處理格式")
    with ic2:
        st.write(""); st.write("")
        go_btn = st.button("🔍 開始分析",use_container_width=True,type="primary")

    should_run = go_btn or (st.session_state.auto_analyze and st.session_state.quick_sym)
    if st.session_state.auto_analyze: st.session_state.auto_analyze=False

    if should_run and (ticker_in or st.session_state.quick_sym).strip():
        use_sym = ticker_in.strip() or st.session_state.quick_sym
        if not api_key: st.warning("⚠️ 請先輸入 Gemini API 金鑰"); st.stop()
        sym = get_sym(use_sym, market)
        add_recent(sym)

        with st.spinner(f"抓取 {sym} 數據..."):
            hist, info, err = fetch_data(sym, period)
        if err: st.error(f"❌ {err}"); st.stop()

        ind   = calc_indicators(hist)
        entry = calc_entry(ind, hist)
        score = calc_score(ind, info)
        co    = info.get("longName") or info.get("shortName") or sym
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 警報
        if sym in st.session_state.alerts:
            a=st.session_state.alerts[sym]
            if a.get("above") and ind["price"]>=a["above"]:
                st.error(f"🔔 警報！{sym} 漲破 {a['above']}，現價 {ind['price']}")
            if a.get("below") and ind["price"]<=a["below"]:
                st.error(f"🔔 警報！{sym} 跌破 {a['below']}，現價 {ind['price']}")

        # 即將到來的財報/除息警報
        try:
            t_obj = yf.Ticker(sym)
            cal   = t_obj.calendar
            if cal is not None and not cal.empty:
                for label,col_name in [("📅 財報日","Earnings Date"),("💰 除息日","Ex-Dividend Date")]:
                    if col_name in cal.columns:
                        ev_date = cal[col_name].iloc[0]
                        if ev_date and (pd.to_datetime(ev_date).date()-date.today()).days<=14:
                            st.markdown(f'<div class="event-warn">⚠️ 事件雷達：{label} = {ev_date} （距今≤14天！）</div>',
                                        unsafe_allow_html=True)
        except: pass

        # 標題列
        hc,sc_col=st.columns([5,1])
        with hc:
            st.subheader(f"📌 {co}（{sym}）")
            st.caption(f"數據時間：{ts}｜宏觀制度：{macro_regime}")
        with sc_col:
            if sym not in st.session_state.watchlist:
                if st.button("⭐ 追蹤",use_container_width=True):
                    st.session_state.watchlist.append(sym)
                    if st.session_state.logged_in: db_add_wl(st.session_state.user_id,sym)
                    st.success("✅")
            else: st.success("⭐ 追蹤中")

        # 評分 + 指標
        score_col, kpi_col = st.columns([1,2])
        with score_col:
            st.markdown(f"""
            <div class="score-card">
                <div style="color:#64748b;font-size:11px">綜合健康評分</div>
                <div class="big-score" style="color:{score['gc']}">{score['total']}</div>
                <div style="color:#e2e8f0;font-size:13px">{score['grade']}</div>
            </div>""",unsafe_allow_html=True)
            st.progress(score["trend"]/30,text=f"趨勢 {score['trend']}/30")
            st.progress(score["mom"]/25,  text=f"動能 {score['mom']}/25")
            st.progress(score["vol"]/20,  text=f"量能 {score['vol']}/20")
            st.progress(score["pos"]/15,  text=f"位置 {score['pos']}/15")
            st.progress(score["bb"]/10,   text=f"布林 {score['bb']}/10")
        with kpi_col:
            st.markdown(f"""
            <div class="status-card">
                <h3 style="margin:0;color:#e2e8f0">{ind['sc']} {ind['status']}</h3>
                <p style="margin:5px 0 0;color:#94a3b8;font-size:13px">{ind['status_desc']}</p>
            </div>""",unsafe_allow_html=True)
            # 台灣色系：漲=紅=inverse
            ci="🔴" if ind["change_pct"]>=0 else "🟢"
            r1,r2,r3 = st.columns(3)
            r1.metric("💰 現價",  ind["price"])
            r2.metric("今日",     f"{ci}{ind['change_pct']}%",  delta=str(ind["change_pct"]), delta_color="inverse")
            r3.metric("本月",     f"{ind['change_1m']}%",       delta=str(ind["change_1m"]),  delta_color="inverse")
            r4,r5,r6 = st.columns(3)
            r4.metric("📏 RSI",  ind["rsi"],           help="0~100，>70超買，<30超賣")
            r5.metric("📦 量比", f"{ind['vol_ratio']}x",help="今日量/20日均量，>1.5放量")
            r6.metric("📐 ATR",  ind["atr"],            help="每天平均波動多少錢")

        st.divider()

        # 指標解讀
        with st.expander("🔍 各指標白話解讀", expanded=True):
            ia,ib,ic_ = st.columns(3)
            with ia:
                st.info(f"**📏 RSI（{ind['rsi']}）**\n\n{ind['rsi_desc']}")
                sk=ind["stoch_k"]
                st.info(f"**📊 Stoch K（{sk}）**\n\n{'⚠️ >80超買' if sk>80 else '💡 <20超賣' if sk<20 else '➡️ 中性'}")
            with ib:
                st.info(f"**📦 {ind['vol_desc']}**")
                bp=ind["bb_pct"]
                st.info(f"**📐 布林（{bp:.0f}%）**\n\n{'⚠️ 接近上軌，過熱' if bp>80 else '💡 接近下軌，超賣' if bp<20 else '✅ 通道中段'}")
            with ic_:
                st.info(f"**📅 52週（{ind['position_52w']}%）**\n\n{'接近高點，相對貴' if ind['position_52w']>80 else '接近低點，相對便宜' if ind['position_52w']<20 else '中間區域'}")
                mh=ind["macd_hist"]
                st.info(f"**📡 MACD（{mh:.4f}）**\n\n{'📈正值，動能增強' if mh>0 else '📉負值，動能減弱'}")

        st.divider()

        # 入場策略
        with st.expander("💰 入場策略參考（⚠️ 僅供參考，不構成投資建議）", expanded=True):
            e1,e2,e3 = st.columns(3)
            with e1:
                st.markdown(f"""<div class="entry-card">
                    <div style="color:#66cc66;font-weight:bold">🎯 參考買入區</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        保守：<b>{entry['con_buy']}</b><br>
                        穩健：<b>{entry['mod_buy']}</b><br>
                        積極：<b>{entry['agg_buy']}</b></div>
                    <div style="color:#94a3b8;font-size:11px">台股一張≈{entry['lot_cost']:,.0f}元</div>
                </div>""",unsafe_allow_html=True)
            with e2:
                st.markdown(f"""<div class="stop-card">
                    <div style="color:#ff6666;font-weight:bold">🛡️ 停損參考</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        緊（短線）：<b>{entry['sl_tight']}</b><br>
                        標準：<b>{entry['sl_normal']}</b><br>
                        寬（長線）：<b>{entry['sl_wide']}</b></div>
                    <div style="color:#94a3b8;font-size:11px">跌破即出場，保護本金</div>
                </div>""",unsafe_allow_html=True)
            with e3:
                st.markdown(f"""<div class="target-card">
                    <div style="color:#66aaff;font-weight:bold">🎯 目標價</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        T1（短）：<b>{entry['tp1']}</b><br>
                        T2（中）：<b>{entry['tp2']}</b><br>
                        T3（壓力）：<b>{entry['tp3']}</b></div>
                    <div style="color:#94a3b8;font-size:11px">風報比：{entry['rr']}:1</div>
                </div>""",unsafe_allow_html=True)

        st.divider()

        # 圖表 + 蒙地卡羅選項
        st.markdown("### 📈 技術分析圖表")
        show_mc = st.checkbox("🎲 開啟蒙地卡羅30日模擬（幾何布朗運動）",
                              help="顯示基於歷史波動率的30日價格機率錐形區間，需要額外幾秒計算")
        mc_data = monte_carlo_simulation(hist) if show_mc else None
        if mc_data:
            st.caption(f"蒙地卡羅參數：日均報酬率={mc_data['mu']:.4f}，日波動率σ={mc_data['sigma']:.4f}，模擬2000條路徑")

        # 買入標記（從持股記錄）
        buy_markers = []
        if sym in st.session_state.portfolio:
            pd2 = st.session_state.portfolio[sym]
            if pd2.get("buy_date"):
                try:
                    bdate = pd.to_datetime(pd2["buy_date"])
                    if bdate.tz: bdate=bdate.tz_localize(None)
                    buy_markers.append({"date":bdate,"price":pd2["cost"]})
                except: pass

        st.plotly_chart(build_main_chart(hist,ind,entry,sym,mc_data,buy_markers if buy_markers else None),
                        use_container_width=True)

        if show_mc and mc_data:
            st.plotly_chart(build_mc_standalone(mc_data,sym),use_container_width=True)
            p=mc_data["pcts"]
            mc1,mc2,mc3 = st.columns(3)
            mc1.metric("30日樂觀預估（95%上界）",f"{round(p['p97'][-1],2)}",
                       delta=f"{round((p['p97'][-1]-mc_data['last'])/mc_data['last']*100,1)}%",
                       delta_color="inverse")
            mc2.metric("30日中位數預估",f"{round(p['p50'][-1],2)}",
                       delta=f"{round((p['p50'][-1]-mc_data['last'])/mc_data['last']*100,1)}%",
                       delta_color="inverse")
            mc3.metric("30日悲觀預估（95%下界）",f"{round(p['p02'][-1],2)}",
                       delta=f"{round((p['p02'][-1]-mc_data['last'])/mc_data['last']*100,1)}%",
                       delta_color="inverse")
            st.caption("⚠️ 蒙地卡羅僅基於歷史波動率，無法預測突發事件。黑天鵝事件不在模型假設內。")

        st.divider()

        # AI 三方辯論（核心功能）
        st.markdown("### 🤖 AI 三方辯論分析")
        st.markdown(f"""
        <div style="background:#1e1e2e;border-radius:10px;padding:12px;margin:8px 0;border:1px solid #3a3a5e">
            <b>🔴 多頭代理人</b> vs <b>🟢 空頭代理人</b> → <b>🟣 CIO裁判最終裁決</b><br>
            <span style="color:#64748b;font-size:12px">三個AI代理人從不同角度辯論，CIO根據「{macro_regime}」宏觀制度加減分後做出最終裁決</span>
        </div>""",unsafe_allow_html=True)

        if st.button("⚔️ 啟動三方辯論（約90秒）",type="primary",key="debate_btn"):
            with st.spinner("🔴 多頭代理人搜尋中..."):
                try:
                    bull_rpt,bear_rpt,judge_rpt = ai_three_agent_debate(
                        ind,info,sym,api_key,entry,score,macro_regime)

                    debate_tab1,debate_tab2,debate_tab3 = st.tabs(
                        ["🔴 多頭論點","🟢 空頭論點","🟣 CIO最終裁決"])

                    with debate_tab1:
                        st.markdown(f'<div class="bull-card"><b>🔴 多頭代理人（Permabull Agent）</b></div>',
                                    unsafe_allow_html=True)
                        secs=bull_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines=sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True):
                                st.markdown(lines[1] if len(lines)>1 else "")

                    with debate_tab2:
                        st.markdown(f'<div class="bear-card"><b>🟢 空頭代理人（Ruthless Bear Agent）</b></div>',
                                    unsafe_allow_html=True)
                        secs=bear_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines=sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True):
                                st.markdown(lines[1] if len(lines)>1 else "")

                    with debate_tab3:
                        st.markdown(f'<div class="judge-card"><b>🟣 CIO最終裁決（宏觀制度：{macro_regime}）</b></div>',
                                    unsafe_allow_html=True)
                        secs=judge_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines=sec.split("\n",1)
                            if "CIO" in lines[0] or "裁決" in lines[0] or "預測" in lines[0]:
                                st.markdown(f"""<div class="predict-card">
                                    <div style="color:#c084fc;font-size:14px;font-weight:bold">## {lines[0]}</div>
                                </div>""",unsafe_allow_html=True)
                                st.markdown(lines[1] if len(lines)>1 else "")
                            else:
                                with st.expander(f"## {lines[0]}",expanded=True):
                                    st.markdown(lines[1] if len(lines)>1 else "")
                except Exception as e:
                    st.error(f"❌ AI 辯論失敗：{str(e)}")

        st.divider()
        st.warning("⚠️ 本系統所有分析與建議**僅供學習參考**，不構成任何投資建議。股市有風險，請自行判斷。")

        with st.expander("🔧 完整原始指標數據"):
            raw_df=pd.DataFrame({
                "指標":["現價","今日%","5日%","月%","MA5","MA20","MA60","VWAP",
                        "RSI","Stoch K","Stoch D","Williams%R","MACD","Signal","Hist",
                        "布林上","布林中","布林下","BB%","布林寬度","ATR","OBV",
                        "成交量","20日均量","量比","52週高","52週低","52週位置%"],
                "數值":[ind["price"],f"{ind['change_pct']}%",f"{ind['change_5d']}%",f"{ind['change_1m']}%",
                        ind["ma5"],ind["ma20"],ind["ma60"],ind["vwap"],
                        ind["rsi"],ind["stoch_k"],ind["stoch_d"],ind["williams_r"],
                        ind["macd"],ind["macd_sig"],ind["macd_hist"],
                        ind["bb_upper"],ind["bb_mid"],ind["bb_lower"],
                        f"{ind['bb_pct']:.0f}%",f"{ind['bb_width']:.1f}%",
                        ind["atr"],ind["obv"],
                        ind["volume"],ind["vol_ma20"],f"{ind['vol_ratio']}x",
                        ind["high_52w"],ind["low_52w"],f"{ind['position_52w']}%"],
            })
            st.dataframe(raw_df,use_container_width=True,hide_index=True)

# ══════════════════════════════════════════════
# TAB 2：我的資產庫
# ══════════════════════════════════════════════
with TABS[1]:
    if not st.session_state.logged_in:
        st.info("💡 登入帳號後，所有資料永久雲端保存")

    asset_tab1,asset_tab2,asset_tab3 = st.tabs(["💼 持股損益","⭐ 自選股","📋 交易記錄"])

# ── 持股損益 ──
    with asset_tab1:
        st.markdown("### 💼 持股損益試算")
        p1,p2,p3,p4,p5 = st.columns(5)
        with p1: ps_=st.text_input("代號",placeholder="如2330",key="pf_s_",help="股票代號")
        with p2: pc_=st.number_input("買入成本",0.0,step=0.5,key="pf_c_",help="每股買入價格")
        with p3: pn_=st.number_input("持有股數",0.0,step=100.0,key="pf_n_",help="台股一張=1000股")
        with p4: pd_=st.date_input("買入日期",key="pf_d_")
        with p5:
            st.write(""); st.write("")
            p_btn=st.button("📊 計算",use_container_width=True,type="primary",key="pf_calc")

        # 💡 修復 Bug 1：用 session_state 記住計算狀態，避免按按鈕後消失
        if "show_pf_calc" not in st.session_state:
            st.session_state.show_pf_calc = False
        
        if p_btn:
            st.session_state.show_pf_calc = True

        # 如果處於計算狀態，就顯示卡片與分析按鈕
        if st.session_state.show_pf_calc and ps_.strip() and pc_>0 and pn_>0:
            ps_sym=get_sym(ps_.strip(),market)
            ph_,pi_,pe_=fetch_data(ps_sym,"5d")
            if pe_: st.error(f"❌ {pe_}")
            else:
                cp_=round(float(ph_["Close"].iloc[-1]),2)
                pnl=round((cp_-pc_)*pn_,2); pct_v=round((cp_-pc_)/max(pc_,0.01)*100,2)
                tc=round(pc_*pn_,0); cv=round(cp_*pn_,0)
                hd=(date.today()-pd_).days; ann=round(pct_v/max(hd,1)*365,2)
                co_n=(pi_ or {}).get("longName") or ps_sym
                st.subheader(f"📌 {co_n}（{ps_sym}）")

                mc1,mc2,mc3,mc4,mc5=st.columns(5)
                mc1.metric("💰 現價",cp_)
                mc2.metric("📊 總成本",f"{tc:,.0f}")
                mc3.metric("💎 現值",f"{cv:,.0f}")
                mc4.metric("損益",f"{pnl:+,.0f}",delta=f"{pct_v:+.2f}%",delta_color="inverse")
                mc5.metric("年化報酬",f"{ann:+.1f}%",delta=str(ann),delta_color="inverse")

                clr="#2b0d0d" if pct_v>=0 else "#0d2b0d"
                bdr=TW_UP if pct_v>=0 else TW_DOWN
                ico="📈 獲利中" if pct_v>=0 else "📉 虧損中"
                st.markdown(f"""
                <div style="background:{clr};border-radius:12px;padding:14px;margin:8px 0;border:1px solid {bdr}">
                    <h3 style="margin:0;color:{bdr}">{ico}　{abs(pnl):,.0f}元（{pct_v:+.2f}%）</h3>
                    <p style="color:#94a3b8;margin:5px 0 0;line-height:1.8">
                        成本：{pc_}×{pn_:.0f}股＝{tc:,.0f}元　現值：{cp_}×{pn_:.0f}股＝{cv:,.0f}元<br>
                        每股{'獲利' if pct_v>=0 else '虧損'}：{cp_-pc_:+.2f}元　持有{hd}天　年化：{ann:+.1f}%　台股約{pn_/1000:.1f}張
                    </p>
                </div>""",unsafe_allow_html=True)

                # AI覆盤教練
                if api_key:
                    if st.button("🤖 AI交易覆盤教練",key="review_btn",type="primary"):
                        _h2,_,_=fetch_data(ps_sym,"6mo")
                        if _h2 is not None:
                            _ind2=calc_indicators(_h2)
                            _en2=calc_entry(_ind2,_h2)
                            # 買入當日指標（重建）
                            try:
                                _h2_idx=_h2.copy(); _h2_idx.index=pd.to_datetime(_h2_idx.index)
                                if _h2_idx.index.tz: _h2_idx.index=_h2_idx.index.tz_localize(None)
                                buy_dt=pd.to_datetime(str(pd_))
                                near=_h2_idx.index[_h2_idx.index.searchsorted(buy_dt)]
                                row_buy=_h2_idx.loc[near]
                                ind_at_buy_str=f"當日收盤：{row_buy['Close']:.2f}，開盤：{row_buy['Open']:.2f}，成交量：{row_buy['Volume']:,.0f}"
                            except: ind_at_buy_str="買入當日數據無法重建"
                            with st.spinner("AI評估中..."):
                                try:
                                    rev=ai_entry_critique(ps_sym,co_n,pc_,str(pd_),ind_at_buy_str,cp_,api_key)
                                    secs=rev.split("\n## ")
                                    st.markdown(secs[0])
                                    for sec in secs[1:]:
                                        lines=sec.split("\n",1)
                                        with st.expander(f"## {lines[0]}",expanded=True):
                                            st.markdown(lines[1] if len(lines)>1 else "")
                                except Exception as e: st.error(str(e)[:80])

                c1_s,c2_s=st.columns(2)
                with c1_s:
                    if st.session_state.logged_in:
                        if st.button("💾 存入持股記錄",key="save_pf"):
                            # 💡 檢查是否已經持有該股票，若有則進行加權平均計算
                            if ps_sym in st.session_state.portfolio:
                                old_data = st.session_state.portfolio[ps_sym]
                                old_cost = old_data["cost"]
                                old_shares = old_data["shares"]
                                
                                # 計算新的總股數與加權平均成本
                                total_shares = old_shares + pn_
                                if total_shares > 0:
                                    avg_cost = ((old_cost * old_shares) + (pc_ * pn_)) / total_shares
                                else:
                                    avg_cost = 0
                                
                                new_cost = round(avg_cost, 2)
                                new_shares = total_shares
                                success_msg = f"✅ 已加碼合併！新均價：{new_cost}，總計：{new_shares} 股"
                            else:
                                new_cost = pc_
                                new_shares = pn_
                                success_msg = "✅ 已新增持股記錄"

                            # 寫入更新後的數據到資料庫與暫存
                            db_save_port(st.session_state.user_id, ps_sym, new_cost, new_shares, "", str(pd_))
                            st.session_state.portfolio[ps_sym] = {"cost": new_cost, "shares": new_shares, "note": "", "buy_date": str(pd_)}
                            st.success(success_msg)
                with c2_s:
                    if ps_sym in st.session_state.portfolio:
                        if st.button("🗑️ 移除持股記錄",key="del_pf"):
                            db_del_port(st.session_state.user_id,ps_sym)
                            del st.session_state.portfolio[ps_sym]
                            st.success("✅ 已移除")
                            st.session_state.show_pf_calc = False # 移除後關閉試算卡片
                            st.rerun()

        # 💡 修復 Bug 2：把持股總覽「移出」計算條件外，確保只要有庫存就一定顯示
        # 💡 方案 B：動態加總與分筆刪除區塊
        if st.session_state.portfolio:
            st.divider()
            st.markdown("### 📋 持股組合總覽")
            sector_map = {}
            pr_rows = []; tc_all = 0; cv_all = 0
            
            for sym, entries in st.session_state.portfolio.items():
                # 防呆：確保 entries 是列表（如果抓到舊版資料，自動包裝成列表）
                if isinstance(entries, dict): entries = [entries]
                
                # 動態加總 list 裡面的股數和成本，計算精準均價
                total_s = sum(e.get("shares", 0) for e in entries)
                total_c = sum(e.get("cost", 0) * e.get("shares", 0) for e in entries)
                avg_c = round(total_c / total_s, 2) if total_s > 0 else 0
                
                try:
                    hh2 = yf.Ticker(sym).history(period="2d")
                    if not hh2.empty:
                        cp2 = round(float(hh2["Close"].iloc[-1]), 2)
                        pnl_pct = round((cp2 - avg_c) / max(avg_c, 0.01) * 100, 2)
                        v2 = round(cp2 * total_s, 0)
                        c2 = round(total_c, 0)
                        
                        try: sec = yf.Ticker(sym).info.get("sector", "其他") or "其他"
                        except: sec = "其他"
                        sector_map[sym] = sec
                        
                        pr_rows.append({
                            "代號": sym, "均價": avg_c, "現價": cp2,
                            "損益%": f"{pnl_pct:+.2f}%", "總損益": f"{v2-c2:+,.0f}",
                            "總股數": total_s, "板塊": sec
                        })
                        tc_all += c2
                        cv_all += v2
                except: pass
            
            if pr_rows:
                st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)
                tp = cv_all - tc_all; tpct = round(tp / max(tc_all, 1) * 100, 2)
                st.metric("📊 組合總損益", f"{tp:+,.0f}元", delta=f"{tpct:+.2f}%", delta_color="inverse")

                # 旭日圖
                fake_port_for_chart = {r["代號"]: {"cost": r["均價"], "shares": r["總股數"]} for r in pr_rows}
                sb_fig = build_portfolio_sunburst(fake_port_for_chart, sector_map)
                if sb_fig: st.plotly_chart(sb_fig, use_container_width=True)

                # AI 投資長 CIO
                if api_key:
                    if st.button("🏦 AI投資長（CIO）組合審查", type="primary", key="cio_btn"):
                        port_str = "\n".join([f"- {r['代號']}: 成本{r['均價']} 現價{r['現價']} 損益{r['損益%']} 板塊{r.get('板塊','未知')}" for r in pr_rows])
                        sec_count = {}
                        for r in pr_rows: sec_count[r.get("板塊","其他")] = sec_count.get(r.get("板塊","其他"), 0) + 1
                        with st.spinner("AI投資長審查中（含即時搜尋）..."):
                            try:
                                cio_rpt = ai_portfolio_cio(port_str, str(sec_count), api_key)
                                secs = cio_rpt.split("\n## ")
                                st.markdown(secs[0])
                                for sec in secs[1:]:
                                    lines = sec.split("\n", 1)
                                    with st.expander(f"## {lines[0]}", expanded=True):
                                        st.markdown(lines[1] if len(lines) > 1 else "")
                            except Exception as e: st.error(str(e)[:80])

            # 👇 方案 B：雙層選單分筆刪除功能
            st.divider()
            st.markdown("#### 🗑️ 刪除特定買入記錄")
            del_c1, del_c2 = st.columns([2, 2])
            with del_c1:
                target_sym = st.selectbox("1. 選擇股票代號", options=list(st.session_state.portfolio.keys()))
            
            with del_c2:
                if target_sym:
                    entries = st.session_state.portfolio[target_sym]
                    if isinstance(entries, dict): entries = [entries] # 防呆
                    
                    # 格式化顯示文字
                    entry_options = {f"買入價 {e.get('cost','?')} | {e.get('shares','?')}股 | 日期 {e.get('buy_date','')}": e for e in entries}
                    selected_label = st.selectbox("2. 選擇要刪除的特定筆數", options=list(entry_options.keys()))
                    to_delete = entry_options[selected_label]
            
            if target_sym:
                if st.button("❌ 確認刪除此筆記錄"):
                    # 1. 從資料庫刪除
                    if st.session_state.logged_in and "db_id" in to_delete:
                        db_del_port_by_id(st.session_state.user_id, to_delete["db_id"])
                    
                    # 2. 從本地暫存中移除該筆
                    if isinstance(st.session_state.portfolio[target_sym], list):
                        st.session_state.portfolio[target_sym].remove(to_delete)
                        if not st.session_state.portfolio[target_sym]:
                            del st.session_state.portfolio[target_sym]
                    else:
                        del st.session_state.portfolio[target_sym] # 舊資料防呆刪除
                        
                    st.success(f"✅ 已成功刪除一筆 {target_sym} 記錄")
                    st.rerun()

    # ── 自選股 ──
    with asset_tab2:
        st.markdown("### ⭐ 自選股即時監控")
        if not st.session_state.watchlist:
            st.info("在左側新增股票代號，或分析後點「追蹤」")
        else:
            with st.spinner("ThreadPoolExecutor 批量抓取股價..."):
                quotes=fetch_batch_quotes(tuple(st.session_state.watchlist))
            wrows=[]
            for s in st.session_state.watchlist:
                p_,ch_=quotes.get(s,(None,None))
                chg_str=f"{'🔴+' if (ch_ or 0)>=0 else '🟢'}{ch_:.2f}%" if ch_ is not None else "-"
                wrows.append({"代號":s,"現價":p_ or "N/A","今日":chg_str,"警報":"🔔" if s in st.session_state.alerts else ""})
            st.dataframe(pd.DataFrame(wrows),use_container_width=True,hide_index=True)
            st.markdown("**快速分析：**")
            bcols=st.columns(min(len(st.session_state.watchlist),6))
            for i,s in enumerate(st.session_state.watchlist[:6]):
                if bcols[i].button(f"📊{s}",key=f"wa_{i}",use_container_width=True):
                    st.session_state.quick_sym=s.replace(".TW",""); st.session_state.auto_analyze=True; st.rerun()
            # 雙重確認
            if not st.session_state.confirm_clear_watch:
                if st.button("🗑️ 清空自選股",key="clr_wl"): st.session_state.confirm_clear_watch=True; st.rerun()
            else:
                st.markdown('<div class="confirm-warn">⚠️ 確定要清空所有自選股？</div>',unsafe_allow_html=True)
                cc1,cc2=st.columns(2)
                if cc1.button("✅確定",type="primary",key="cw_ok"):
                    if st.session_state.logged_in:
                        for s in st.session_state.watchlist: db_del_wl(st.session_state.user_id,s)
                    st.session_state.watchlist=[]; st.session_state.confirm_clear_watch=False; st.rerun()
                if cc2.button("❌取消",key="cw_can"): st.session_state.confirm_clear_watch=False; st.rerun()

    # ── 交易記錄（已平倉）──
    with asset_tab3:
        st.markdown("### 📋 已平倉交易記錄")
        st.caption("記錄已出場的交易，用於計算績效與行為分析")

        # 新增交易記錄
        with st.expander("➕ 新增已平倉交易"):
            t1,t2,t3,t4 = st.columns(4)
            with t1: t_sym=st.text_input("代號",key="th_sym")
            with t2: t_ep=st.number_input("買入價",0.0,step=0.5,key="th_ep")
            with t3: t_xp=st.number_input("賣出價",0.0,step=0.5,key="th_xp")
            with t4: t_sh=st.number_input("股數",0.0,step=100.0,key="th_sh")
            t5,t6,t7=st.columns(3)
            with t5: t_ed=st.date_input("買入日",key="th_ed")
            with t6: t_xd=st.date_input("賣出日",key="th_xd")
            with t7: t_note=st.text_input("備注",key="th_note",placeholder="可選")
            if st.button("💾 記錄此交易",key="add_trade_btn"):
                if t_sym.strip() and t_ep>0 and t_xp>0 and t_sh>0:
                    ts_sym=get_sym(t_sym.strip(),market)
                    pnl_a=round((t_xp-t_ep)*t_sh,2); pnl_p=round((t_xp-t_ep)/max(t_ep,0.01)*100,2)
                    db_add_trade(st.session_state.user_id if st.session_state.logged_in else "local",
                                 ts_sym,"LONG",t_ep,t_xp,t_sh,str(t_ed),str(t_xd),t_note)
                    st.session_state.trade_history=db_load_trades(st.session_state.user_id) if st.session_state.logged_in else st.session_state.trade_history+[{"symbol":ts_sym,"direction":"LONG","entry_price":t_ep,"exit_price":t_xp,"shares":t_sh,"entry_date":str(t_ed),"exit_date":str(t_xd),"pnl_amount":pnl_a,"pnl_pct":pnl_p,"note":t_note}]
                    st.success(f"✅ 已記錄 {ts_sym}，損益：{pnl_a:+,.0f}元（{pnl_p:+.2f}%）")

        # 顯示記錄
        trades = st.session_state.trade_history
        if trades:
            tr_df=pd.DataFrame([{
                "代號":t.get("symbol",""),
                "買入價":t.get("entry_price",0),
                "賣出價":t.get("exit_price",0),
                "股數":t.get("shares",0),
                "損益":f"{(t.get('pnl_amount') or 0):+,.0f}",
                "損益%":f"{(t.get('pnl_pct') or 0):+.2f}%",
                "買入日":t.get("entry_date",""),
                "賣出日":t.get("exit_date",""),
                "備注":t.get("note",""),
            } for t in trades])
            st.dataframe(tr_df,use_container_width=True,hide_index=True)

            total_pnl_t=sum((t.get("pnl_amount") or 0) for t in trades)
            win_t=sum(1 for t in trades if (t.get("pnl_pct") or 0)>0)
            st.metric("📊 累積損益",f"{total_pnl_t:+,.0f}元",
                      delta=f"勝率{round(win_t/max(len(trades),1)*100,1)}%",delta_color="inverse")

            # 雙重確認清空
            if not st.session_state.confirm_clear_trades:
                if st.button("🗑️ 清空全部記錄"): st.session_state.confirm_clear_trades=True; st.rerun()
            else:
                st.markdown('<div class="confirm-warn">⚠️ 確定清空所有交易記錄？不可復原！</div>',unsafe_allow_html=True)
                cc1,cc2=st.columns(2)
                if cc1.button("✅確定清空",type="primary",key="ct_ok"):
                    st.session_state.trade_history=[]; st.session_state.confirm_clear_trades=False; st.rerun()
                if cc2.button("❌取消",key="ct_can"): st.session_state.confirm_clear_trades=False; st.rerun()

# ══════════════════════════════════════════════
# TAB 3：選股 + DCA 回測
# ══════════════════════════════════════════════
with TABS[2]:
    scr_tab, dca_tab = st.tabs(["🔎 技術面選股器","⏳ 定期定額回測"])

    with scr_tab:
        st.markdown("### 🔎 技術面選股器")
        st.caption("設定篩選條件，從熱門股清單中找符合條件的標的（ThreadPoolExecutor 加速）")

        col1,col2 = st.columns(2)
        with col1:
            scr_rsi_lt = st.number_input("RSI <（超賣篩選）",0.0,100.0,35.0,step=5.0,help="RSI低於此值才入選，設0=不篩選")
            scr_macd   = st.checkbox("MACD Histogram > 0（動能向上）",help="柱狀圖為正值，代表上漲動能")
            scr_ma20   = st.checkbox("現價 > MA20（站上月線）",help="股價在20日均線上方")
        with col2:
            scr_rsi_gt = st.number_input("RSI >（超買篩選）",0.0,100.0,0.0,step=5.0,help="設0=不篩選")
            scr_vol    = st.checkbox("成交量 > 1.5倍均量（放量）",help="今日成交量超過20日均量1.5倍")
            scr_bb_lo  = st.checkbox("布林位置 < 25%（接近下軌）",help="股價接近布林下軌，超賣區域")

        if st.button("🔍 開始篩選",type="primary",use_container_width=True):
            hot=TW_HOT if "台股" in market else US_HOT
            all_syms=[]
            for stocks in hot.values():
                for sym_,_ in stocks:
                    all_syms.append(get_sym(sym_,market))

            conditions={}
            if scr_rsi_lt>0:   conditions["rsi_lt"]=scr_rsi_lt
            if scr_rsi_gt>0:   conditions["rsi_gt"]=scr_rsi_gt
            if scr_macd:       conditions["macd_cross_up"]=True
            if scr_ma20:       conditions["above_ma20"]=True
            if scr_vol:        conditions["vol_spike"]=True
            if scr_bb_lo:      conditions["bb_near_lower"]=True

            with st.spinner(f"掃描 {len(all_syms)} 支股票中（ThreadPoolExecutor加速）..."):
                results=run_screener(all_syms,conditions)
            if results:
                st.success(f"✅ 找到 {len(results)} 支符合條件的股票")
                scr_df=pd.DataFrame(results)
                st.dataframe(scr_df,use_container_width=True,hide_index=True)
                st.caption("點擊代號可跳到個股戰情室分析")
                btn_cols2=st.columns(min(len(results),6))
                for i,r in enumerate(results[:6]):
                    if btn_cols2[i].button(f"📊 {r['代號']}",key=f"scr_{i}"):
                        st.session_state.quick_sym=r["代號"].replace(".TW","")
                        st.session_state.auto_analyze=True; st.rerun()
            else:
                st.info("😔 目前沒有股票符合篩選條件，嘗試放寬條件")

    with dca_tab:
        st.markdown("### ⏳ 定期定額回測（DCA Backtester）")
        st.info("💡 每月固定投入固定金額，用真實歷史數據模擬。ETF（如0050、SPY）最適合此策略。")
        d1,d2,d3,d4=st.columns(4)
        with d1: dca_sym=st.text_input("代號",placeholder="如0050或SPY",key="dca_s",help="建議用ETF")
        with d2: dca_amt=st.number_input("每月投入（元）",1000.0,1000000.0,10000.0,step=1000.0,key="dca_a",help="建議月收入10~20%")
        with d3: dca_yr =st.selectbox("回測年限",[3,5,10,15,20],index=1,format_func=lambda x:f"{x}年",key="dca_y",help="至少5年才有意義")
        with d4:
            st.write(""); st.write("")
            dca_btn=st.button("⏳ 開始回測",type="primary",use_container_width=True)
        if dca_btn and dca_sym.strip():
            dca_full=get_sym(dca_sym.strip(),market)
            with st.spinner(f"模擬 {dca_full} {dca_yr}年定期定額..."):
                df_dca,stats,err=run_dca(dca_full,dca_amt,dca_yr)
            if df_dca is None: st.error(f"❌ {err}")
            else:
                st.markdown(f"### 📊 {dca_full} {dca_yr}年定期定額結果")
                scols=st.columns(len(stats))
                for col,(k,v) in zip(scols,stats.items()): col.metric(k,v)
                st.plotly_chart(build_dca_chart(df_dca,dca_full),use_container_width=True)
                fv=df_dca["資產現值"].iloc[-1]; ti=df_dca["累積投入"].iloc[-1]; profit=fv-ti
                col_p=TW_UP if profit>=0 else TW_DOWN
                st.markdown(f"""
                <div style="background:#1e1e2e;border-radius:12px;padding:14px;margin:10px 0;border:1px solid #2a2a3e">
                    <h4 style="color:#e2e8f0;margin:0">📖 白話解讀</h4>
                    <p style="color:#94a3b8;margin:8px 0 0;line-height:1.8">
                        如果從<b>{dca_yr}年前</b>每月投入<b>{dca_amt:,.0f}元</b>，總投入<b>{ti:,.0f}元</b>，
                        今天資產現值<b>{fv:,.0f}元</b>，
                        <span style="color:{col_p};font-weight:bold">{'獲利' if profit>=0 else '虧損'} {abs(profit):,.0f}元（{stats['累積報酬率']}）</span><br>
                        最大回撤<b>{stats['最大回撤MDD']}</b>：這段期間你的資產最多曾縮水這麼多，能撐住才能享受最終報酬。
                    </p>
                </div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════
# TAB 4：市場總覽
# ══════════════════════════════════════════════
with TABS[3]:
    st.markdown("### 🗺️ 板塊熱力圖（🔴漲 🟢跌，台灣色系）")
    st.caption("方塊大小=市值，顏色=今日漲跌（ThreadPoolExecutor 批量抓取）")
    if st.button("🔄 載入熱力圖（約30~60秒）",type="primary"):
        with st.spinner("批量抓取板塊數據..."):
            df_hm=fetch_heatmap_data(market)
        if not df_hm.empty:
            fig_hm=build_heatmap_chart(df_hm,market)
            if fig_hm: st.plotly_chart(fig_hm,use_container_width=True)
        else: st.warning("數據載入失敗，請稍後再試")

    st.divider()
    st.markdown("### 📊 全球主要指數")
    mkt_all=fetch_market_overview()
    if mkt_all:
        for row in mkt_all:
            chg=row["漲跌%"]; icon="▲" if chg>=0 else "▼"
            color=TW_UP if chg>=0 else TW_DOWN
            st.markdown(f"""
            <div style="background:#1e1e2e;border-radius:8px;padding:10px 16px;
                margin:3px 0;border-left:4px solid {color};display:flex;justify-content:space-between">
                <span style="color:#e2e8f0">{row['名稱']}</span>
                <span style="color:{color};font-weight:bold">{row['現值']} {icon}{abs(chg):.2f}%</span>
            </div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════
# TAB 5：交易心理診斷
# ══════════════════════════════════════════════
with TABS[4]:
    st.markdown("### 🧠 交易心理與行為偏誤診斷")
    st.info("""
    💡 **為什麼需要行為分析？**
    研究顯示，90%的散戶虧損不是因為不懂技術，而是**心理偏誤**導致的錯誤決策。
    最常見的是**處置效應**：太快賣掉賺錢的股票，卻死抱著虧損的股票不放。
    本系統分析你的交易記錄，診斷你的行為偏誤。
    """)

    trades=st.session_state.trade_history
    if len(trades)<3:
        st.warning("⚠️ 需要至少3筆已平倉交易記錄才能進行行為分析。請先在「我的資產庫→交易記錄」新增記錄。")
    else:
        bias=analyze_behavioral_bias(trades)
        if not bias: st.warning("數據不足以分析"); st.stop()

        # 統計儀表板
        b1,b2,b3,b4 = st.columns(4)
        b1.metric("勝率",f"{bias['win_rate']}%",help="獲利交易/總交易次數")
        b2.metric("平均獲利",f"+{bias['avg_win_pct']:.2f}%",help="獲利交易的平均報酬率")
        b3.metric("平均虧損",f"-{bias['avg_loss_pct']:.2f}%",help="虧損交易的平均虧損率")
        b4.metric("獲利/虧損比",
                  f"{round(bias['avg_win_pct']/max(bias['avg_loss_pct'],0.01),2)}x",
                  help="平均獲利幅度/平均虧損幅度，理想值>1.5")

        b5,b6,b7 = st.columns(3)
        b5.metric("平均持有獲利股",f"{bias['avg_win_days']:.0f}天")
        b6.metric("平均持有虧損股",f"{bias['avg_loss_days']:.0f}天",
                  delta="⚠️ 高於獲利股" if bias['avg_loss_days']>bias['avg_win_days'] else "✅ 正常",
                  delta_color="off")
        b7.metric("總交易次數",f"{bias['win_count']+bias['lose_count']}次")

        # 處置效應警告
        if bias["disposition_effect"]:
            st.markdown("""
            <div style="background:#3a0000;border-radius:12px;padding:16px;margin:12px 0;
                border:2px solid #ff3333">
                <h3 style="color:#ff6666;margin:0">🚨 偵測到處置效應（Disposition Effect）！</h3>
                <p style="color:#ffaaaa;margin:8px 0 0">
                    你的數據顯示：<b>持有虧損股的時間顯著長於持有獲利股</b>。<br>
                    這是散戶最常見的致命偏誤：急著鎖住獲利，卻死抱著虧損股等待解套。<br>
                    長期下來，你的帳戶將充滿「套牢股」，而所有獲利都被你過早了結。
                </p>
            </div>""",unsafe_allow_html=True)

        # 交易記錄視覺化
        if len(trades)>=2:
            tr_viz=pd.DataFrame([{
                "交易":f"{t.get('symbol','')}（{t.get('exit_date','')}）",
                "損益%":t.get("pnl_pct",0),
                "持有天數":max((date.fromisoformat(t.get("exit_date","2000-01-01"))-date.fromisoformat(t.get("entry_date","2000-01-01"))).days,0) if t.get("exit_date") and t.get("entry_date") else 0,
            } for t in trades])
            fig_tr=px.scatter(tr_viz,x="持有天數",y="損益%",text="交易",
                color="損益%",
                color_continuous_scale=[(0.0,TW_DOWN),(0.5,"#888888"),(1.0,TW_UP)],
                color_continuous_midpoint=0,
                title="交易散佈圖：持有天數 vs 損益（🔴獲利 🟢虧損）",
                template=DARK)
            fig_tr.add_hline(y=0,line_dash="dash",line_color="rgba(255,255,255,0.3)")
            fig_tr.update_layout(height=400)
            st.plotly_chart(fig_tr,use_container_width=True)

        # AI 行為偏誤報告
        if api_key:
            if st.button("🧠 AI 深度行為偏誤診斷",type="primary"):
                trades_summary="\n".join([
                    f"- {t.get('symbol','')}：買入{t.get('entry_price',0)} 賣出{t.get('exit_price',0)} 損益{t.get('pnl_pct',0):+.1f}% 持有{max((date.fromisoformat(t.get('exit_date','2000-01-01'))-date.fromisoformat(t.get('entry_date','2000-01-01'))).days,0) if t.get('exit_date') and t.get('entry_date') else 0}天"
                    for t in trades[:10]
                ])
                with st.spinner("AI分析行為模式中..."):
                    try:
                        bias_rpt=ai_bias_warning(bias,trades_summary,api_key)
                        secs=bias_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines=sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True):
                                st.markdown(lines[1] if len(lines)>1 else "")
                    except Exception as e: st.error(str(e)[:80])

# ══════════════════════════════════════════════
# 頁尾
# ══════════════════════════════════════════════
st.divider()
st.caption(
    "📈 股市小白分析系統 Pro V2.0 ｜ "
    "AI三方辯論 × 蒙地卡羅GBM × 行為偏誤診斷 × 15項指標 × 帳號雲端記憶 ｜ "
    "🔴紅漲🟢跌（台灣色系）｜ "
    "⚠️ 所有內容僅供學習參考，不構成任何投資建議"
)