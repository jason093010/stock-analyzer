# ╔═══════════════════════════════════════════════════════════════════╗
# ║  股市小白分析系統 Pro  V5.3  ─  極簡白話文 × NaN防護 × 記憶防暴衝   ║
# ║  Taiwan Color: RED=漲  GREEN=跌  |  當沖/短線/長線 三維度決策整合   ║
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

try:
    from streamlit_cookies_controller import CookieController
    cookie_controller = CookieController()
except ImportError:
    cookie_controller = None

# ══════════════════════════════════════════════
# 1. 頁面設定與 CSS
# ══════════════════════════════════════════════
st.set_page_config(page_title="股市小白分析系統 Pro V5", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@media(max-width:768px){ h1{font-size:1.2rem!important} h3{font-size:0.95rem!important} }
.score-card{background:linear-gradient(135deg,#1e1e2e,#2a2a3e);border-radius:12px;padding:15px;text-align:center;border:1px solid #3a3a5e;margin-bottom:10px}
.big-score{font-size:2.5rem;font-weight:900;line-height:1.1}
.status-card{background:#1e1e2e;border-radius:12px;padding:14px;margin:6px 0;border-left:5px solid #7c3aed}
.predict-card{background:linear-gradient(135deg,#1a0d2b,#2b1a3a);border-radius:14px;padding:16px;margin:8px 0;border:2px solid #6b2fba}
.bull-card{background:linear-gradient(135deg,#2b0d0d,#3a1a1a);border-radius:12px;padding:14px;margin:5px 0;border:2px solid #cc3333}
.bear-card{background:linear-gradient(135deg,#0d2b0d,#1a3a1a);border-radius:12px;padding:14px;margin:5px 0;border:2px solid #33cc33}
.judge-card{background:linear-gradient(135deg,#1a1a2b,#2b2a3a);border-radius:12px;padding:14px;margin:5px 0;border:2px solid #9966cc}
.price-up{color:#ff4444!important;font-weight:700}
.price-dn{color:#22cc44!important;font-weight:700}
.stDataFrame {border-radius: 8px; overflow: hidden;}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# 2. Supabase 與 Session State
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
except Exception: pass

_DEFS = dict(
    user_id=None, username=None, logged_in=False, _pin="", api_key="", 
    watchlist=[], alerts={}, portfolio={}, trade_history=[], 
    recent_searches=[], quick_sym="", auto_analyze=False,
    confirm_clear_watch=False, confirm_clear_port=False, confirm_clear_trades=False,
    macro_regime="未知", macro_auto_tried=False,
)
for k, v in _DEFS.items():
    if k not in st.session_state: 
        st.session_state[k] = v

# ══════════════════════════════════════════════
# 3. 加密工具與資料庫函數
# ══════════════════════════════════════════════
_SALT = b"tw_stock_pro_v5_salt"

def _derive_key(pin: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(pin.encode()))

def encrypt_key(api_key: str, pin: str) -> str: return Fernet(_derive_key(pin)).encrypt(api_key.encode()).decode()
def decrypt_key(token: str, pin: str) -> str:
    try: return Fernet(_derive_key(pin)).decrypt(token.encode()).decode()
    except: return ""

def make_uid(username: str, pin: str) -> str: return hashlib.sha256(f"{username.lower().strip()}:{pin}".encode()).hexdigest()[:20]

def db_verify_user(username: str, pin: str):
    if not HAS_DB: return True, make_uid(username, pin), None
    try:
        uid = make_uid(username, pin)
        r = _supabase.table("users").select("id,encrypted_api_key").eq("username", username.lower().strip()).eq("password_hash", uid).execute()
        if r.data: return True, uid, r.data[0].get("encrypted_api_key")
        return False, None, None
    except: return False, None, None

def db_create_user(username: str, pin: str):
    if not HAS_DB: return True, make_uid(username, pin), "本機模式"
    try:
        uid = make_uid(username, pin)
        ex = _supabase.table("users").select("id").eq("username", username.lower().strip()).execute()
        if ex.data: return False, None, "帳號已存在"
        _supabase.table("users").insert({"username": username.lower().strip(), "password_hash": uid}).execute()
        return True, uid, "帳號建立成功！"
    except Exception as e: return False, None, str(e)[:60]

def db_save_enc_key(username: str, pin: str, api_key: str):
    if not HAS_DB or not api_key: return
    try:
        token = encrypt_key(api_key, pin)
        _supabase.table("users").update({"encrypted_api_key": token}).eq("username", username.lower().strip()).execute()
    except: pass

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

def db_load_port(uid):
    if not HAS_DB: return {}
    try:
        data = _supabase.table("portfolio").select("*").eq("user_id", uid).execute().data
        port = {}
        for x in data:
            sym = x["symbol"]
            if sym not in port: port[sym] = []
            port[sym].append({"db_id": x["id"], "cost": x["cost_price"], "shares": x["shares"], "note": x.get("note",""), "buy_date": x.get("buy_date","")})
        return port
    except: return {}

def db_save_port(uid, sym, cost, shares, note="", buy_date=""):
    if not HAS_DB: return
    try: _supabase.table("portfolio").insert({"user_id": uid, "symbol": sym, "cost_price": cost, "shares": shares, "note": note, "buy_date": buy_date}).execute()
    except: pass

def db_del_port_by_id(uid, db_id):
    if not HAS_DB: return
    try: _supabase.table("portfolio").delete().eq("id", db_id).eq("user_id", uid).execute()
    except: pass

def db_del_port(uid, sym):
    if not HAS_DB: return
    try: _supabase.table("portfolio").delete().eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

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
            "user_id":uid,"symbol":sym,"direction":direction, "entry_price":entry_price,"exit_price":exit_price,"shares":shares,
            "entry_date":entry_date,"exit_date":exit_date, "pnl_amount":pnl_amt,"pnl_pct":pnl_pct,"note":note
        }).execute()
    except: pass

def db_del_trade(uid,trade_id):
    if not HAS_DB: return
    try: _supabase.table("trade_history").delete().eq("id",trade_id).eq("user_id",uid).execute()
    except: pass

# ══════════════════════════════════════════════
# 4. 靜態資料與工具函數
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
    "RSI":"相對強弱指標0~100。>70超買(漲太快)，<30超賣(跌太多)。",
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
    "處置效應":"散戶常見心理偏誤: 太早賣出獲利股，太晚出清虧損股。",
    "總體宏觀制度":"指當前全球經濟所處的大環境，如通膨衰退、復甦成長等，影響所有資產走向。",
}

MACRO_REGIMES = ["未知","成長擴張(Risk-On)","通膨衰退(Stagflation)","衰退(Risk-Off)","復甦反彈(Early Cycle)","流動性危機"]

def get_sym(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"): 
        return raw + ".TW"
    return raw

def safe_f(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if v == v else default
    except: 
        return default

def add_recent(sym: str):
    r = st.session_state.recent_searches
    if sym in r: 
        r.remove(sym)
    r.insert(0, sym)
    st.session_state.recent_searches = r[:8]

def fmt_large(v):
    if not isinstance(v,(int,float)): return str(v)
    if abs(v)>=1e12: return f"{v/1e12:.2f}兆"
    if abs(v)>=1e8:  return f"{v/1e8:.2f}億"
    if abs(v)>=1e4:  return f"{v/1e4:.0f}萬"
    return f"{v:,.2f}"

# ══════════════════════════════════════════════
# 5. 數據抓取模組 (NaN 終極防護)
# ══════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data(symbol: str, period: str):
    try:
        h = yf.download(symbol, period=period, progress=False)
        if h is None or h.empty: 
            return None, None, "查無此代號或暫無數據"
        if isinstance(h.columns, pd.MultiIndex): 
            h.columns = [col[0] for col in h.columns]
        if "Close" in h.columns: 
            h = h.dropna(subset=["Close"])
        if h.empty: 
            return None, None, "查無有效數據或逢休市無資料"
            
        info = {}
        try:
            t = yf.Ticker(symbol)
            info['longName'] = t.info.get('longName', symbol)
            info['sector'] = t.info.get('sector', '其他')
            info['trailingPE'] = t.info.get('trailingPE', 'N/A')
            info['forwardPE'] = t.info.get('forwardPE', 'N/A')
            info['priceToBook'] = t.info.get('priceToBook', 'N/A')
            info['beta'] = t.info.get('beta', 'N/A')
            info['marketCap'] = t.info.get('marketCap', 'N/A')
            
            dy = t.info.get('dividendYield', 'N/A')
            if isinstance(dy, float):
                info['dividendYield'] = f"{dy * 100:.2f}%"
            else:
                info['dividendYield'] = 'N/A'
        except: 
            info = {'longName': symbol, 'sector': '其他'}
        return h, info, None
    except Exception as e: 
        return None, None, f"抓取失敗: {str(e)[:50]}"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_overview():
    syms = {"台灣加權":"^TWII","S&P 500":"^GSPC","那斯達克":"^IXIC","VIX恐慌":"^VIX","費城半導":"^SOX","美元指數":"DX-Y.NYB"}
    tickers = list(syms.values())
    rows = []
    try:
        data = yf.download(tickers, period="5d", group_by="ticker", progress=False)
        for name, sym in syms.items():
            try:
                df = data[sym] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = [c[0] for c in df.columns]
                # 強制剔除 NaN 並抓取最後兩筆有效收盤價
                if "Close" in df.columns:
                    df_clean = df["Close"].dropna()
                    if len(df_clean) >= 2:
                        c1 = float(df_clean.iloc[-2])
                        c2 = float(df_clean.iloc[-1])
                        rows.append({"名稱":name, "現值":round(c2, 2), "漲跌%":round((c2 - c1) / max(c1, 0.01) * 100, 2)})
            except: 
                continue
    except: 
        pass
    return sorted(rows, key=lambda x: list(syms.keys()).index(x["名稱"])) if rows else []

@st.cache_data(ttl=60, show_spinner=False)
def fetch_batch_quotes(symbols: tuple) -> dict:
    if not symbols: 
        return {}
    results = {}
    try:
        data = yf.download(list(symbols), period="5d", group_by="ticker", progress=False)
        if data is None or data.empty: 
            return {sym: (None, None) for sym in symbols}
        for sym in symbols:
            try:
                df = data[sym] if len(symbols)>1 else data
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = [c[0] for c in df.columns]
                if "Close" in df.columns:
                    df_clean = df["Close"].dropna()
                    if len(df_clean) >= 2:
                        c1 = float(df_clean.iloc[-2])
                        c2 = float(df_clean.iloc[-1])
                        results[sym] = (round(c2, 2), round((c2 - c1) / max(c1, 0.01) * 100, 2))
                    else: 
                        results[sym] = (None, None)
                else:
                    results[sym] = (None, None)
            except: 
                results[sym] = (None, None)
    except: 
        results = {sym: (None, None) for sym in symbols}
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
    if not tickers: 
        return pd.DataFrame()
    try:
        data = yf.download(tickers, period="5d", group_by="ticker", progress=False)
        for full in tickers:
            try:
                df = data[full] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = [c[0] for c in df.columns]
                if "Close" in df.columns:
                    df_clean = df["Close"].dropna()
                    if len(df_clean) >= 2:
                        c1 = float(df_clean.iloc[-2])
                        c2 = float(df_clean.iloc[-1])
                        if c1 > 0:
                            sector, name = sym_map[full]
                            rows.append({"板塊": sector, "名稱": name, "代號": full.replace(".TW",""), "漲跌%": round((c2 - c1) / c1 * 100, 2), "市值": 1e9})
            except: 
                continue
    except: 
        pass
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════
# 6. 多週期量化指標計算
# ══════════════════════════════════════════════
def calc_indicators(hist: pd.DataFrame) -> dict:
    c = hist["Close"].astype(float)
    h = hist["High"].astype(float)
    l = hist["Low"].astype(float)
    v = hist["Volume"].astype(float)
    n = len(c)

    def _last(s):
        try:
            val = float(s.iloc[-1])
            return val if val==val else 0.0
        except: 
            return 0.0

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

    r_min = rsi.rolling(14).min()
    r_max = rsi.rolling(14).max()
    stk   = (100*(rsi-r_min)/(r_max-r_min+1e-10)).clip(0,100)
    std_  = stk.rolling(3).mean()

    bb_m  = c.rolling(20).mean()
    bb_s  = c.rolling(20).std()
    bb_u  = bb_m+2*bb_s
    bb_l  = bb_m-2*bb_s
    bb_pct= ((c-bb_l)/(bb_u-bb_l+1e-10)*100).clip(0,100)
    bb_w  = ((bb_u-bb_l)/(bb_m+1e-10)*100)

    pc    = c.shift(1)
    tr    = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr   = tr.rolling(14).mean()

    obv   = (v*((c.diff()>0).astype(float)*2-1)).fillna(0).cumsum()
    hh    = h.rolling(14).max()
    ll_   = l.rolling(14).min()
    wr    = (-100*(hh-c)/(hh-ll_+1e-10)).clip(-100,0)
    tp    = (h+l+c)/3
    vwap  = (tp*v).rolling(20).sum()/(v.rolling(20).sum()+1e-10)

    price  = round(_last(c),2)
    atr_v  = round(_last(atr),4)
    if atr_v==0: 
        atr_v = round(price*0.02,2)

    def chg(k):
        if n>k:
            ref=safe_f(c.iloc[-(k+1)])
            return round((price-ref)/max(ref,0.01)*100,2)
        return 0.0

    ind = {
        "price":price,"change_pct":chg(1),"change_5d":chg(5),"change_1m":chg(21),
        "ma5":round(_last(ma5),2),"ma20":round(_last(ma20),2),"ma60":round(_last(ma60),2),"vwap":round(_last(vwap),2),
        "rsi":round(_last(rsi),1),"stoch_k":round(_last(stk),1),"stoch_d":round(_last(std_),1),"williams_r":round(_last(wr),1),
        "macd":round(_last(macd),4),"macd_sig":round(_last(macd_s),4),"macd_hist":round(_last(macd_h),4),
        "atr":atr_v, "bb_upper":round(_last(bb_u),2),"bb_mid":round(_last(bb_m),2),"bb_lower":round(_last(bb_l),2),
        "bb_pct":round(_last(bb_pct),1),"bb_width":round(_last(bb_w),1),
        "volume":int(_last(v)),"vol_ma20":int(_last(v.rolling(20).mean())),"obv":round(_last(obv),0),
        "high_52w":round(float(c.rolling(min(252,n)).max().iloc[-1]),2),"low_52w": round(float(c.rolling(min(252,n)).min().iloc[-1]),2),
        "_c":c,"_h":h,"_l":l,"_v":v,"_rsi":rsi,"_stk":stk,"_macd":macd,"_macd_sig":macd_s,"_macd_h":macd_h,
        "_bb_u":bb_u,"_bb_l":bb_l,"_bb_m":bb_m,"_ma5":ma5,"_ma20":ma20,"_ma60":ma60,"_obv":obv,"_hist":hist,
    }

    vr = ind["volume"]/max(ind["vol_ma20"],1)
    ind["vol_ratio"] = round(vr,2)
    
    if vr >= 2.5:   
        ind["vol_desc"] = f"🔥爆量{vr:.1f}倍均量"
    elif vr >= 1.5: 
        ind["vol_desc"] = f"📢放量{vr:.1f}倍"
    elif vr >= 0.8: 
        ind["vol_desc"] = f"📊正常量{vr:.1f}倍"
    else:         
        ind["vol_desc"] = f"😴縮量{vr:.1f}倍，訊號可信度低"

    pos = (price-ind["low_52w"])/max(ind["high_52w"]-ind["low_52w"],0.01)*100
    ind["position_52w"] = round(pos,1)

    ind["dt_status"] = "強勢 (站上VWAP且放量)" if price > ind["vwap"] and vr > 1.2 else "弱勢 (VWAP壓制)" if price < ind["vwap"] else "震盪 (貼近VWAP)"
    ind["st_status"] = "偏多 (站上月線且RSI>50)" if ind["ma5"] > ind["ma20"] and ind["rsi"] > 50 else "偏空 (跌破月線且RSI<50)" if ind["ma5"] < ind["ma20"] and ind["rsi"] < 50 else "盤整 (均線糾結或指標分歧)"
    ind["lt_status"] = "多頭格局 (季線之上且強勢)" if price > ind["ma60"] and pos > 50 else "空頭/超賣 (季線之下且弱勢)" if price < ind["ma60"] and pos < 30 else "中性格局 (季線震盪)"

    rv=ind["rsi"]
    kv=ind["stoch_k"]
    mv=ind["macd_hist"]
    if ind["ma5"]>ind["ma20"]>ind["ma60"] and rv>55 and mv>0: 
        ind["status"], ind["sc"], ind["status_desc"] = "強勢多頭 📈", "🔴", "均線多頭排列，上漲動能強"
    elif ind["ma5"]<ind["ma20"]<ind["ma60"] and rv<45 and mv<0: 
        ind["status"], ind["sc"], ind["status_desc"] = "強勢空頭 📉", "🟢", "均線空頭排列，下跌壓力大"
    elif rv<=30 and kv<20: 
        ind["status"], ind["sc"], ind["status_desc"] = "雙重超賣 🟡", "🟡", "跌很多了，隨時可能出現反彈"
    elif rv>=70 and kv>80: 
        ind["status"], ind["sc"], ind["status_desc"] = "雙重超買 🟡", "🟡", "漲太多了，短期可能有獲利了結賣壓"
    elif abs(ind["ma5"]-ind["ma20"])/max(price,0.01)<0.015: 
        ind["status"], ind["sc"], ind["status_desc"] = "盤整蓄勢 ⚪", "⚪", "價格上下震盪，等待出明確方向"
    elif ind["ma5"]>ind["ma20"] and rv>50: 
        ind["status"], ind["sc"], ind["status_desc"] = "短線偏多 🔵", "🔵", "短期趨勢向上，多方稍微佔優勢"
    else: 
        ind["status"], ind["sc"], ind["status_desc"] = "方向不明 🟠", "🟠", "走勢疲軟，建議新手先觀望"

    return ind

def calc_score(ind: dict, info: dict) -> dict:
    trend = min(30,(8 if ind["ma5"]>ind["ma20"] else 0)+(8 if ind["ma20"]>ind["ma60"] else 0)+(7 if ind["price"]>ind["ma20"] else 0)+(7 if ind["macd_hist"]>0 else 0))
    rv=ind["rsi"]
    kv=ind["stoch_k"]
    wrv=ind["williams_r"]
    mom=min(25,(10 if 50<=rv<=70 else 8 if rv<30 else 5 if 40<=rv<50 else 3)+(8 if 40<=kv<=80 else 5 if kv<20 else 0)+(7 if wrv>-50 else 0))
    vr=ind["vol_ratio"]
    vol=min(20,20 if vr>=1.5 and ind["change_pct"]>0 else 15 if vr>=1.2 and ind["change_pct"]>0 else 10 if 0.8<=vr<=1.5 else 5)
    pos=ind["position_52w"]
    psc=min(15,15 if 30<=pos<=70 else 12 if pos<20 else 10 if pos<30 or pos<80 else 4)
    bsc=min(10,10 if 20<=ind["bb_pct"]<=80 else 7 if ind["bb_pct"]<20 else 3)
    total=trend+mom+vol+psc+bsc
    
    if total>=80: 
        grade,gc="A(優秀)","#ff4444"
    elif total>=65: 
        grade,gc="B(良好)","#ff8800"
    elif total>=50: 
        grade,gc="C(普通)","#ffcc00"
    elif total>=35: 
        grade,gc="D(偏弱)","#88cc44"
    else: 
        grade,gc="E(警示)","#22aa44"
        
    return {"total":total,"grade":grade,"gc":gc,"trend":trend,"mom":mom,"vol":vol,"pos":psc,"bb":bsc}

def calc_entry(ind: dict, hist: pd.DataFrame) -> dict:
    c=ind["_c"]
    h=ind["_h"]
    l=ind["_l"]
    price=ind["price"]
    atr=max(ind["atr"],price*0.005)
    n=len(c)
    w=min(60,n)
    ph=round(float(h.iloc[-w:].max()),2)
    pl=round(float(l.iloc[-w:].min()),2)
    fr=max(ph-pl,atr)
    fibs={k:round(ph-v*fr,2) for k,v in [("0.236",0.236),("0.382",0.382),("0.500",0.500),("0.618",0.618),("0.786",0.786)]}
    sup1=round(float(l.iloc[-20:].min()),2)
    sup2=round(float(l.iloc[-w:].min()),2)
    res1=round(float(h.iloc[-20:].max()),2)
    res2=round(float(h.iloc[-w:].max()),2)
    
    agg_buy=round(price*0.995,2)                 
    mod_buy=round((sup1+ind["ma20"])/2,2)        
    con_buy=round(min(sup1,fibs["0.382"]),2)     
    sl_tight=round(price-1.5*atr,2)              
    sl_normal=round(price-2.5*atr,2)             
    sl_wide=round(max(sup2*0.97,price-4*atr),2)  
    tp1=round(price+2*atr,2)
    tp2=round(price+4*atr,2)
    tp3=round(max(res2*1.02,price+6*atr),2)
    rr=round((tp1-mod_buy)/max(mod_buy-sl_normal,0.01),2)
    
    return dict(fibs=fibs,sup1=sup1,sup2=sup2,res1=res1,res2=res2,
                con_buy=con_buy,mod_buy=mod_buy,agg_buy=agg_buy,
                sl_tight=sl_tight,sl_normal=sl_normal,sl_wide=sl_wide,
                tp1=tp1,tp2=tp2,tp3=tp3,rr=rr,ph=ph,pl=pl,
                atr=atr,lot_cost=round(mod_buy*1000,0))

# ══════════════════════════════════════════════
# 7. 蒙地卡羅模擬
# ══════════════════════════════════════════════
def monte_carlo_simulation(hist: pd.DataFrame, days: int = 30, simulations: int = 2000) -> dict:
    close = hist["Close"].astype(float)
    log_returns = np.log(close / close.shift(1)).dropna()
    mu = float(log_returns.mean())
    sigma = float(log_returns.std())
    last_price = float(close.iloc[-1])
    dt = 1
    np.random.seed(42)
    rand_matrix = np.random.standard_normal((simulations, days))
    price_matrix = np.zeros((simulations, days))
    price_matrix[:, 0] = last_price * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, 0])
    
    for t in range(1, days): 
        price_matrix[:, t] = price_matrix[:, t-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, t])
        
    percentiles = {
        "p02": np.percentile(price_matrix, 2.5, axis=0), 
        "p16": np.percentile(price_matrix, 16, axis=0), 
        "p50": np.percentile(price_matrix, 50, axis=0), 
        "p84": np.percentile(price_matrix, 84, axis=0), 
        "p97": np.percentile(price_matrix, 97.5, axis=0)
    }
    future_dates = [hist.index[-1] + timedelta(days=i+1) for i in range(days)]
    
    return {
        "dates": future_dates, "pcts": percentiles, "last": last_price, 
        "mu": mu, "sigma": sigma, "matrix_sample": price_matrix[:50]
    }

# ══════════════════════════════════════════════
# 8. Screener, DCA 與行為分析
# ══════════════════════════════════════════════
def run_screener(symbols: list, conditions: dict) -> list:
    results = []
    def _check(sym):
        try:
            h, info, err = fetch_data(sym, "3mo")
            if err or h is None: 
                return None
            ind = calc_indicators(h)
            ok = True
            
            if conditions.get("rsi_lt") and ind["rsi"] >= conditions["rsi_lt"]: 
                ok = False
            if conditions.get("rsi_gt") and ind["rsi"] <= conditions["rsi_gt"]: 
                ok = False
            if conditions.get("macd_cross_up") and ind["macd_hist"] <= 0: 
                ok = False
            if conditions.get("above_ma20") and ind["price"] <= ind["ma20"]: 
                ok = False
            if conditions.get("vol_spike") and ind["vol_ratio"] < 1.5: 
                ok = False
            if conditions.get("bb_near_lower") and ind["bb_pct"] > 25: 
                ok = False
                
            if ok: 
                return {
                    "代號":sym,"現價":ind["price"],"RSI":ind["rsi"],"MACD_H":ind["macd_hist"],
                    "量比":ind["vol_ratio"],"狀態":ind["status"],"評分":calc_score(ind,info)["total"]
                }
        except: 
            pass
        return None
        
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(_check,s) for s in symbols]
        for f in as_completed(futs):
            r = f.result()
            if r: 
                results.append(r)
                
    return sorted(results, key=lambda x: x["評分"], reverse=True)

def run_dca(symbol: str, monthly_amount: float, years: int, market: str):
    bm_sym = "^TWII" if "台股" in market else "^GSPC"
    
    hist, _, err = fetch_data(symbol, f"{years}y")
    if err or hist is None: 
        return None, None, err
        
    hist = hist.copy()
    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz: 
        hist.index = hist.index.tz_localize(None)
        
    hist["ym"] = hist.index.to_period("M")
    monthly = hist.groupby("ym").first()
    
    recs=[]
    total_inv=0.0
    total_sh=0.0
    
    for period_lbl, row in monthly.iterrows():
        price=float(row["Close"])
        if price<=0: 
            continue
        total_sh+=monthly_amount/price
        total_inv+=monthly_amount
        recs.append({"date":period_lbl.to_timestamp(),"累積投入":total_inv,"資產現值":total_sh*price})
        
    if not recs: 
        return None, None, "無足夠歷史數據"
        
    df=pd.DataFrame(recs).set_index("date")
    fv=df["資產現值"].iloc[-1]
    rtn=round((fv-total_inv)/max(total_inv,0.01)*100,2)
    peak=df["資產現值"].cummax()
    dd=(df["資產現值"]-peak)/(peak+1e-10)*100
    mdd=round(dd.min(),2)
    
    bm_hist, _, _ = fetch_data(bm_sym, f"{years}y")
    bm_rtn_str = "N/A"
    sharpe_str = "N/A"
    
    if bm_hist is not None and not bm_hist.empty:
        try:
            # 確保提取出無 NaN 的收盤價以計算基準報酬
            bm_clean = bm_hist["Close"].dropna()
            if len(bm_clean) > 0:
                bm_start = float(bm_clean.iloc[0])
                bm_end = float(bm_clean.iloc[-1])
                bm_rtn = ((bm_end - bm_start) / bm_start) * 100
                bm_rtn_str = f"{bm_rtn:+.2f}%"
            
            daily_returns = hist["Close"].pct_change().dropna()
            ann_vol = daily_returns.std() * np.sqrt(252) * 100
            ann_rtn = rtn / max(years, 1)
            if ann_vol > 0:
                sharpe = (ann_rtn - 2.0) / ann_vol
                sharpe_str = f"{sharpe:.2f}"
        except:
            pass
    
    stats={
        "總投入本金":round(total_inv,0),"最終資產現值":round(fv,0),
        "累積報酬率":f"{rtn:+.2f}%","大盤同期報酬": bm_rtn_str,
        "年化報酬率":f"{rtn/max(years,1):+.2f}%",
        "最大回撤MDD":f"{mdd:.2f}%","夏普值 (Sharpe)": sharpe_str
    }
    return df, stats, None

def analyze_behavioral_bias(trades: list) -> dict:
    if len(trades) < 3: 
        return {}
    wins  = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    loses = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
    if not wins or not loses: 
        return {}
        
    def hold_days(t):
        try: 
            return (date.fromisoformat(t.get("exit_date",""))-date.fromisoformat(t.get("entry_date",""))).days
        except: 
            return 0
            
    avg_win_pct = sum(t.get("pnl_pct",0) for t in wins)/len(wins)
    avg_loss_pct = sum(abs(t.get("pnl_pct",0)) for t in loses)/len(loses)
    avg_win_days = sum(hold_days(t) for t in wins)/len(wins)
    avg_loss_days = sum(hold_days(t) for t in loses)/len(loses)
    disposition = avg_loss_days > avg_win_days * 1.3 and avg_loss_pct > avg_win_pct
    
    return {
        "win_count": len(wins), "lose_count": len(loses), 
        "avg_win_pct": round(avg_win_pct,2), "avg_loss_pct": round(avg_loss_pct,2), 
        "avg_win_days": round(avg_win_days,1), "avg_loss_days": round(avg_loss_days,1), 
        "disposition_effect": disposition, "win_rate": round(len(wins)/len(trades)*100,1)
    }

# ══════════════════════════════════════════════
# 9. AI 生成模組 (強制極簡新手白話文版)
# ══════════════════════════════════════════════
def call_ai(api_key: str, prompt: str, use_search: bool = False) -> str:
    client = genai.Client(api_key=api_key)
    models = [("gemini-2.5-flash","Gemini 2.5 Flash"),("gemini-2.0-flash","Gemini 2.0 Flash"),("gemini-2.0-flash-lite","Gemini Flash Lite")]
    last_err = None
    for mid, mname in models:
        try:
            if use_search:
                cfg = genai_types.GenerateContentConfig(tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],temperature=0.2)
                resp = client.models.generate_content(model=mid,contents=prompt,config=cfg)
            else: 
                resp = client.models.generate_content(model=mid,contents=prompt)
            tag = "+Search" if use_search else ""
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
            return f"> [AI] {mname}{tag} | {ts}\n\n{resp.text}"
        except Exception as e:
            err=str(e)
            if any(k in err for k in ["quota","429","RESOURCE_EXHAUSTED","404","not found"]): 
                last_err=err[:80]
                continue
            raise
    raise Exception(f"所有模型均無法使用: {last_err}")

def ai_macro_regime(api_key: str) -> str:
    prompt = """You are an elite Macroeconomist. Analyze the current global macroeconomic regime based on this week's data.
Choose EXACTLY ONE from the following list and output that exact string: [未知, 成長擴張(Risk-On), 通膨衰退(Stagflation), 衰退(Risk-Off), 復甦反彈(Early Cycle), 流動性危機].

You MUST format your output exactly as shown below:

**制度: ** [Exact string from the list above]
**理由: ** [Under 30 words explaining FED policy or inflation in Traditional Chinese.]"""
    return call_ai(api_key, prompt, use_search=True)

def ai_three_agent_debate(ind, info, sym, api_key, entry, score, macro_regime) -> tuple:
    co  = info.get("longName") or info.get("shortName") or sym
    atr = entry["atr"]

    base_data = f"""[STOCK DATA]
Symbol: {co} ({sym}) | Price: {ind['price']} | 1D: {ind['change_pct']}% | 1M: {ind['change_1m']}%
Score: {score['total']}/100 ({score['grade']}) | Status: {ind['status']}
MA5={ind['ma5']} MA20={ind['ma20']} MA60={ind['ma60']}
RSI={ind['rsi']} StochK={ind['stoch_k']} Williams%R={ind['williams_r']}
MACD_H={ind['macd_hist']} ATR={atr} OBV={'Up' if ind['obv']>0 else 'Down'}
BB_Position={ind['bb_pct']:.0f}% | Vol_Desc={ind.get('vol_desc', 'N/A')} | 52W_Position={ind['position_52w']}%
Support={entry['sup1']}/{entry['sup2']} | Resistance={entry['res1']}/{entry['res2']}
Current Macro Regime: {macro_regime}"""

    # 💡 強制要求極簡、抓重點、不廢話
    bull_prompt = f"""You are a Permabull Analyst. Construct the strongest bullish argument for this stock.
{base_data}
[TONE REQUIREMENT]: MUST write for a beginner (股市小白). Use simple everyday analogies. AVOID jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. NO introductory or concluding pleasantries. Get straight to the point. Output in Traditional Chinese (zh-TW).

## 🔴 為什麼看漲？ (利多)
- (1 short bullet point: Latest positive news)
- (1 short bullet point: Strongest technical signal)
## ⏱️ 給你的建議
- ⚡ **當沖**: (Short advice)
- 📈 **波段**: (Short advice)
- 💎 **存股**: (Short advice)
"""

    bear_prompt = f"""You are a Ruthless Bear Analyst. Expose all bearish risks for this stock.
{base_data}
[TONE REQUIREMENT]: MUST write for a beginner (股市小白). Use simple everyday analogies. AVOID jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. NO introductory or concluding pleasantries. Get straight to the point. Output in Traditional Chinese (zh-TW).

## 🟢 為什麼看跌？ (風險)
- (1 short bullet point: Latest negative news/risk)
- (1 short bullet point: Weakest technical signal)
## ⏱️ 給你的警告
- ⚡ **當沖**: (Short warning)
- 📉 **波段**: (Short warning)
- 🏚️ **存股**: (Short warning)
"""

    judge_prompt = f"""You are a CIO. Adjudicate the bullish and bearish arguments objectively.
{base_data}
[TONE REQUIREMENT]: MUST write for a beginner (股市小白). Use simple everyday analogies. AVOID jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. NO introductory or concluding pleasantries. Get straight to the point. Output in Traditional Chinese (zh-TW).

## 🟣 裁判最終判定
- **多空大對決**: (Who wins? Bull or Bear? 1 sentence)
## ⏱️ 最終操作建議
- ⚡ **當沖**: (Buy/Sell/Wait + 1 reason)
- 📈 **波段**: (Buy/Sell/Wait + 1 reason)
- 💎 **存股**: (Yes/No + 1 reason)
## 💡 給新手的一句真心話
- (1 punchy, brutal advice regarding this stock)
"""

    # 序列執行確保不觸發 429
    bull_rpt = call_ai(api_key, bull_prompt, use_search=True)
    time.sleep(1.5)
    bear_rpt = call_ai(api_key, bear_prompt, use_search=True)
    time.sleep(1.5)
    judge_rpt= call_ai(api_key, judge_prompt, use_search=False)
    
    return bull_rpt, bear_rpt, judge_rpt

def ai_portfolio_cio(portfolio_data: str, sector_data: str, api_key: str) -> str:
    prompt = f"""You are a strict Chief Investment Officer (CIO) auditing a client's portfolio.
[PORTFOLIO DATA]
{portfolio_data}
Sector Allocation: {sector_data}

[TONE REQUIREMENT]: MUST write for a beginner. Avoid jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. Output in Traditional Chinese (zh-TW).

## 🏦 你的持股健康檢查
- (1 sentence assessing risk)
## ⚔️ 汰弱留強大掃除
(For EACH stock):
- **[Symbol]**: 短線(留/砍), 長線(留/砍) - (Brief reason)
## 🔄 這樣做會更好
- (1 worst stock to sell)
- (1 best stock to keep/add)
"""
    return call_ai(api_key, prompt, use_search=True)

def ai_entry_critique(sym, co, buy_price, buy_date, ind_at_buy, current_price, api_key) -> str:
    prompt = f"""You are a Trading Coach. Post-mortem analysis:
Trade: {co} ({sym}) bought at {buy_price} on {buy_date}. Current price: {current_price}. Indicators at buy: {ind_at_buy}.

[TONE REQUIREMENT]: MUST write for a beginner. Avoid jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. Output in Traditional Chinese (zh-TW).

## 🔬 買點健檢
- (Was it a good entry? 1 sentence)
## 🎯 現在該怎麼辦？
- **短線**: (Hold/Sell/Stop)
- **長線**: (Add/Hold/Sell)
## 🧠 心理防線
- (1 common behavioral mistake they might be making right now)
"""
    return call_ai(api_key, prompt, use_search=False)

def ai_bias_warning(bias_data: dict, trades_summary: str, api_key: str) -> str:
    disposition = bias_data.get("disposition_effect", False)
    prompt = f"""You are a Behavioral Finance Expert. Diagnose biases.
Win rate: {bias_data.get('win_rate',0)}%, Disposition effect: {'Yes' if disposition else 'No'}. Recent trades: {trades_summary}.

[TONE REQUIREMENT]: MUST write for a beginner. Avoid jargon.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. NO fluff. Output in Traditional Chinese (zh-TW).

## 🧠 投資壞習慣診斷
- (Top 2 mistakes observed)
## 💊 幫你開處方籤
- **短線藥方**: (1 strict rule)
- **長線藥方**: (1 mindset fix)
"""
    return call_ai(api_key, prompt, use_search=False)

# ══════════════════════════════════════════════
# 10. 圖表建構 (台灣色系: 紅漲綠跌)
# ══════════════════════════════════════════════
DARK = "plotly_dark"
TW_UP = "#ff3333"
TW_DOWN = "#22cc44"

def build_main_chart(hist, ind, entry, sym, mc_data=None, buy_markers=None):
    idx = hist.index
    rows = 4
    heights = [0.50, 0.18, 0.17, 0.15]
    titles = ["K線+均線+布林(台灣色系: 紅漲綠跌)","成交量","RSI+Stochastic","MACD"]
    
    if mc_data: 
        rows = 5
        heights = [0.42, 0.18, 0.15, 0.13, 0.12]
        titles.append("蒙地卡羅模擬(30日錐形區間)")
        
    fig = make_subplots(rows=rows,cols=1,shared_xaxes=True,row_heights=heights,subplot_titles=titles,vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(x=idx,open=hist["Open"],high=hist["High"],low=hist["Low"],close=hist["Close"],name="K線",increasing_line_color=TW_UP,decreasing_line_color=TW_DOWN,increasing_fillcolor=TW_UP,decreasing_fillcolor=TW_DOWN),row=1,col=1)
    
    for key,color,nm in [("_ma5","#FFA726","MA5"),("_ma20","#42A5F5","MA20"),("_ma60","#AB47BC","MA60")]: 
        fig.add_trace(go.Scatter(x=idx,y=ind[key],line=dict(color=color,width=1.3),name=nm),row=1,col=1)
        
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_u"],line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林上",showlegend=False),row=1,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_l"],line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林下",showlegend=False,fill="tonexty",fillcolor="rgba(255,235,59,0.04)"),row=1,col=1)

    for y_val,color,label in [(entry["sup1"],"rgba(34,204,68,0.8)",f"短撐 {entry['sup1']}"),(entry["res1"],"rgba(255,51,51,0.8)", f"短壓 {entry['res1']}"),(entry["mod_buy"],"rgba(255,200,50,0.8)",f"波段買 {entry['mod_buy']}")]: 
        fig.add_hline(y=y_val,line_dash="dash",line_color=color,annotation_text=label,annotation_font_size=10,row=1,col=1)
        
    if buy_markers:
        for bm in buy_markers: 
            fig.add_trace(go.Scatter(x=[bm["date"]],y=[bm["price"]],mode="markers+text",marker=dict(symbol="triangle-up",size=14,color="#FFD700",line=dict(color="#FF8C00",width=2)),text=[f"買入\n{bm['price']}"],textposition="bottom center",textfont=dict(color="#FFD700",size=10),name=f"買入 {bm['price']}",showlegend=True),row=1,col=1)

    vc = [TW_UP if c>=o else TW_DOWN for c,o in zip(hist["Close"],hist["Open"])]
    fig.add_trace(go.Bar(x=idx,y=ind["_v"],marker_color=vc,showlegend=False),row=2,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_v"].rolling(20).mean(),line=dict(color="#FFA726",width=1.2),showlegend=False),row=2,col=1)
    
    fig.add_trace(go.Scatter(x=idx,y=ind["_rsi"],line=dict(color="#FF7043",width=1.5),name="RSI",showlegend=False),row=3,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_stk"],line=dict(color="#66BB6A",width=1,dash="dot"),name="StochK",showlegend=False),row=3,col=1)
    for lv,lc in [(70,"rgba(255,51,51,0.4)"),(50,"rgba(150,150,150,0.3)"),(30,"rgba(34,204,68,0.4)")]: 
        fig.add_hline(y=lv,line_dash="dash",line_color=lc,row=3,col=1)
        
    mc_c = [TW_UP if x>=0 else TW_DOWN for x in ind["_macd_h"]]
    fig.add_trace(go.Bar(x=idx,y=ind["_macd_h"],marker_color=mc_c,showlegend=False),row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd"],line=dict(color="#42A5F5",width=1),showlegend=False),row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd_sig"],line=dict(color="#FF7043",width=1),showlegend=False),row=4,col=1)

    if mc_data:
        mc_row = 5
        fd = mc_data["dates"]
        p = mc_data["pcts"]
        fig.add_trace(go.Scatter(x=fd,y=p["p97"],line=dict(color="rgba(255,200,50,0.3)",width=1),showlegend=False,name="95%上界"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p02"],line=dict(color="rgba(255,200,50,0.3)",width=1),showlegend=False,fill="tonexty",fillcolor="rgba(255,200,50,0.08)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p84"],line=dict(color="rgba(100,180,255,0.5)",width=1),showlegend=False,name="68%上界"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p16"],line=dict(color="rgba(100,180,255,0.5)",width=1),showlegend=False,fill="tonexty",fillcolor="rgba(100,180,255,0.12)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p50"],line=dict(color="#FFD700",width=2),name="中位數路徑"),row=mc_row,col=1)
        for path in mc_data["matrix_sample"][:5]: 
            fig.add_trace(go.Scatter(x=fd,y=path,line=dict(color="rgba(200,200,200,0.1)",width=0.5),showlegend=False),row=mc_row,col=1)

    fig.update_layout(template=DARK,title=f"{sym} 技術分析(🔴漲 🟢跌)",height=900 if mc_data else 780,xaxis_rangeslider_visible=False,legend=dict(orientation="h",y=1.02,font_size=11),margin=dict(l=50,r=50,t=80,b=30))
    return fig

def build_heatmap_chart(df: pd.DataFrame, market: str):
    if df.empty: 
        return None
    fig = px.treemap(df,path=["板塊","名稱"],values="市值",color="漲跌%",color_continuous_scale=[(0.0,TW_DOWN),(0.5,"#333333"),(1.0,TW_UP)],color_continuous_midpoint=0,custom_data=["代號","漲跌%"],title=f"{'台股' if '台股' in market else '美股'} 板塊熱力圖(🔴漲 🟢跌)",template=DARK)
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{customdata[1]:.2f}%",textfont_size=13)
    fig.update_layout(height=550,margin=dict(l=10,r=10,t=60,b=10),coloraxis_colorbar=dict(title="漲跌%"))
    return fig

def build_portfolio_sunburst(portfolio: dict, sector_map: dict) -> go.Figure:
    rows = []
    for sym,data in portfolio.items():
        if isinstance(data, list):
             for entry in data:
                 rows.append({"板塊":sector_map.get(sym,"其他"),"代號":sym,"市值":entry["cost"]*entry["shares"]})
        else:
             rows.append({"板塊":sector_map.get(sym,"其他"),"代號":sym,"市值":data["cost"]*data["shares"]})
    if not rows: 
        return None
    df = pd.DataFrame(rows)
    fig = px.sunburst(df,path=["板塊","代號"],values="市值",title="持股板塊旭日圖(方塊大小=持倉成本)",template=DARK,color_discrete_sequence=px.colors.qualitative.Set3)
    fig.update_layout(height=450,margin=dict(l=10,r=10,t=60,b=10))
    return fig

def build_dca_chart(df_dca: pd.DataFrame, sym: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["累積投入"],fill="tozeroy",name="累積投入本金",line=dict(color="#42A5F5",width=2),fillcolor="rgba(66,165,245,0.15)"))
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["資產現值"],fill="tozeroy",name="資產現值",line=dict(color=TW_UP,width=2),fillcolor="rgba(255,51,51,0.15)"))
    fig.update_layout(template=DARK,title=f"{sym} 定期定額回測",yaxis_title="金額(元)",height=420,legend=dict(orientation="h",y=1.02),margin=dict(l=50,r=30,t=60,b=30))
    return fig

def build_mc_standalone(mc_data: dict, sym: str) -> go.Figure:
    fig = go.Figure()
    fd = mc_data["dates"]
    p = mc_data["pcts"]
    fig.add_trace(go.Scatter(x=fd,y=p["p97"],line=dict(color="rgba(255,200,50,0.3)",width=1),name="95%區間上界"))
    fig.add_trace(go.Scatter(x=fd,y=p["p02"],line=dict(color="rgba(255,200,50,0.3)",width=1),name="95%區間下界",fill="tonexty",fillcolor="rgba(255,200,50,0.08)"))
    fig.add_trace(go.Scatter(x=fd,y=p["p84"],line=dict(color="rgba(100,180,255,0.5)",width=1),name="68%區間上界"))
    fig.add_trace(go.Scatter(x=fd,y=p["p16"],line=dict(color="rgba(100,180,255,0.5)",width=1),name="68%區間下界",fill="tonexty",fillcolor="rgba(100,180,255,0.12)"))
    fig.add_trace(go.Scatter(x=fd,y=p["p50"],line=dict(color="#FFD700",width=2.5),name="中位數路徑"))
    
    for i,path in enumerate(mc_data["matrix_sample"][:20]): 
        fig.add_trace(go.Scatter(x=fd,y=path,line=dict(color="rgba(200,200,200,0.07)",width=0.5),showlegend=False))
        
    fig.add_hline(y=mc_data["last"],line_dash="dash",line_color="rgba(255,255,255,0.5)",annotation_text="現價")
    fig.update_layout(template=DARK,title=f"{sym} 蒙地卡羅30日模擬",yaxis_title="預估價格",height=450,legend=dict(orientation="h",y=1.02),margin=dict(l=50,r=30,t=70,b=30))
    return fig

# ══════════════════════════════════════════════
# 11. 側邊欄 (含 Cookie 自動登入機制與名詞解釋)
# ══════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定")
    st.caption("🟢 雲端已連線" if HAS_DB else "🟡 本機模式")

    st.divider()
    st.header("👤 個人帳號")
    
    if not st.session_state.logged_in and cookie_controller is not None:
        saved_u = cookie_controller.get("tw_stock_u")
        saved_p = cookie_controller.get("tw_stock_p")
        if saved_u and saved_p:
            ok, uid, enc = db_verify_user(saved_u, saved_p)
            if ok:
                st.session_state.user_id = uid
                st.session_state.username = saved_u
                st.session_state._pin = saved_p
                st.session_state.logged_in = True
                st.session_state.watchlist = db_load_wl(uid)
                st.session_state.alerts = db_load_alerts(uid)
                st.session_state.portfolio = db_load_port(uid)
                st.session_state.trade_history = db_load_trades(uid)
                if enc:
                    dec = decrypt_key(enc, saved_p)
                    if dec: 
                        st.session_state.api_key = dec

    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號", placeholder="英文+數字", key="sb_u")
            upin  = st.text_input("密碼", type="password", key="sb_p")
            ca, cb = st.columns(2)
            with ca:
                if st.button("🔑 登入", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok,uid,enc = db_verify_user(uname.strip(),upin.strip())
                        if ok:
                            st.session_state.user_id=uid
                            st.session_state.username=uname.strip()
                            st.session_state._pin=upin.strip()
                            st.session_state.logged_in=True
                            st.session_state.watchlist=db_load_wl(uid)
                            st.session_state.alerts=db_load_alerts(uid)
                            st.session_state.portfolio=db_load_port(uid)
                            st.session_state.trade_history=db_load_trades(uid)
                            if enc:
                                dec = decrypt_key(enc, upin.strip())
                                if dec: 
                                    st.session_state.api_key = dec
                            if cookie_controller is not None:
                                cookie_controller.set("tw_stock_u", uname.strip(), max_age=30*86400)
                                cookie_controller.set("tw_stock_p", upin.strip(), max_age=30*86400)
                            st.success(f"✅ 歡迎！")
                            st.rerun()
                        else: 
                            st.error("❌ 錯誤")
            with cb:
                if st.button("✨ 建立", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok,uid,msg = db_create_user(uname.strip(),upin.strip())
                        if ok:
                            st.session_state.user_id=uid
                            st.session_state.username=uname.strip()
                            st.session_state._pin=upin.strip()
                            st.session_state.logged_in=True
                            if cookie_controller is not None:
                                cookie_controller.set("tw_stock_u", uname.strip(), max_age=30*86400)
                                cookie_controller.set("tw_stock_p", upin.strip(), max_age=30*86400)
                            st.success("✅ 建立成功")
                            st.rerun()
                        else: 
                            st.error(f"❌ {msg}")
    else:
        st.success(f"👤 {st.session_state.username}")
        if st.button("🚪 登出", use_container_width=True):
            for k in ["user_id","username","logged_in","api_key","_pin"]: 
                st.session_state[k] = False if k=="logged_in" else "" if k in ["api_key","_pin"] else None
            for k in ["watchlist","trade_history"]: 
                st.session_state[k]=[]
            for k in ["alerts","portfolio"]: 
                st.session_state[k]={}
            if cookie_controller is not None: 
                cookie_controller.remove("tw_stock_u")
                cookie_controller.remove("tw_stock_p")
            st.rerun()

    st.divider()
    if st.session_state.logged_in and st.session_state.api_key:
        st.success("🔑 API 金鑰已帶入")
        if st.button("🔄 更換金鑰"): 
            st.session_state.api_key=""
            st.rerun()
        api_key = "".join(c for c in str(st.session_state.api_key) if ord(c) < 128).strip() if st.session_state.api_key else ""
    else:
        api_key_in = st.text_input("🔑 Gemini API 金鑰",type="password",placeholder="AIza...",value=st.session_state.api_key)
        if api_key_in and api_key_in!=st.session_state.api_key:
            st.session_state.api_key="".join(c for c in str(api_key_in) if ord(c) < 128).strip()
            if st.session_state.logged_in and HAS_DB: 
                db_save_enc_key(st.session_state.username,st.session_state._pin,api_key_in)
                st.success("🔒 已加密")
        api_key = "".join(c for c in str(st.session_state.api_key) if ord(c) < 128).strip() if st.session_state.api_key else ""

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("市場",["🇹🇼 台股","🇺🇸 美股"])
    period = st.selectbox("分析區間",["3mo","6mo","1y","2y"],index=1,format_func=lambda x:{"3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年"}[x])

    st.divider()
    st.header("🌍 宏觀制度設定")
    
    current_regime = st.session_state.macro_regime
    if current_regime not in MACRO_REGIMES:
        current_regime = MACRO_REGIMES[0]
        st.session_state.macro_regime = current_regime

    # 💡 修正: 只在系統剛開啟、沒測試過的情況下背景測試 1 次
    if api_key and current_regime == MACRO_REGIMES[0] and not st.session_state.macro_auto_tried:
        st.session_state.macro_auto_tried = True
        with st.spinner("🌍 系統初始化：背景自動偵測全球宏觀制度中..."):
            try:
                regime_rpt = ai_macro_regime(api_key)
                for r in MACRO_REGIMES[1:]:
                    if r in regime_rpt: 
                        st.session_state.macro_regime = r
                        current_regime = r
                        break
            except: 
                pass

    macro_regime = st.selectbox("當前宏觀制度",MACRO_REGIMES,index=MACRO_REGIMES.index(current_regime),key="macro_sel")
    st.session_state.macro_regime = macro_regime
    
    if api_key and st.button("🔄 手動重新偵測",use_container_width=True):
        with st.spinner("重新搜尋與評估中..."):
            try:
                regime_rpt = ai_macro_regime(api_key)
                for r in MACRO_REGIMES[1:]:
                    if r in regime_rpt: 
                        st.session_state.macro_regime=r
                        macro_regime=r
                        break
                st.success(f"✅ 偵測完成: {st.session_state.macro_regime}")
                with st.expander("查看 AI 分析報告"): 
                    st.markdown(regime_rpt)
            except Exception as e: 
                st.error(str(e)[:50])

    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號",placeholder="如2330",key="sb_nw")
    if nw and nw.strip():
        sa=get_sym(nw.strip(),market)
        if sa not in st.session_state.watchlist:
            st.session_state.watchlist.append(sa)
            if st.session_state.logged_in: 
                db_add_wl(st.session_state.user_id,sa)
            st.rerun()
            
    for i,s in enumerate(st.session_state.watchlist):
        c1,c2=st.columns([4,1])
        c1.write(f"• {s}")
        if c2.button("❌",key=f"dw_{i}_{s}"):
            if st.session_state.logged_in: 
                db_del_wl(st.session_state.user_id,s)
            st.session_state.watchlist.pop(i)
            st.rerun()

    st.divider()
    st.header("📖 名詞解釋")
    for term,desc in GLOSSARY.items():
        with st.expander(term): 
            st.info(desc)

# ══════════════════════════════════════════════
# 12. 主頁面 (戰情室)
# ══════════════════════════════════════════════
st.title("📈 股市小白分析系統 Pro V5.3")
st.caption("防封鎖序列AI × 絕對新手白話文版 × 資金控管模組 × 🔴紅漲🟢跌")

mkt = fetch_market_overview()
if mkt:
    mcols = st.columns(len(mkt))
    for col,row in zip(mcols,mkt): 
        chg=row["漲跌%"]
        col.metric(row["名稱"],str(row["現值"]),f"{'▲' if chg>=0 else '▼'}{abs(chg):.2f}%",delta_color="inverse")

if st.session_state.recent_searches:
    st.markdown("**🕐 最近查詢: **")
    rc=st.columns(min(len(st.session_state.recent_searches),8))
    for i,rs in enumerate(st.session_state.recent_searches):
        if rc[i].button(rs,key=f"rc_{i}"): 
            st.session_state.quick_sym=rs.replace(".TW","")
            st.session_state.auto_analyze=True
            st.rerun()

regime_colors={"成長擴張(Risk-On)":"#cc2222","復甦反彈(Early Cycle)":"#aa3333","通膨衰退(Stagflation)":"#446644","衰退(Risk-Off)":"#228844","流動性危機":"#4422aa","未知":"#444444"}
rc=regime_colors.get(macro_regime,"#444444")
st.markdown(f'<div style="background:{rc};border-radius:8px;padding:8px 16px;margin:6px 0;text-align:center"><span style="color:white;font-weight:bold">🌍 當前宏觀大環境: {macro_regime}</span></div>',unsafe_allow_html=True)
st.divider()

TABS = st.tabs(["📊 個股戰情室","💼 我的資產庫","📊 選股+回測","🗺️ 市場總覽","🧠 交易心理診斷"])

with TABS[0]:
    st.markdown("### 🚀 快速選股")
    hot = TW_HOT if "台股" in market else US_HOT
    for cat,stocks in hot.items():
        st.caption(f"**{cat}**")
        qcols=st.columns(len(stocks))
        for col,(sym_,name_) in zip(qcols,stocks):
            if col.button(f"{sym_}\n{name_}",use_container_width=True,key=f"qs_{sym_}_{cat}"): 
                st.session_state.quick_sym=sym_
                st.session_state.auto_analyze=True
                st.rerun()

    st.divider()
    ic1,ic2 = st.columns([3,1])
    with ic1: 
        ticker_in = st.text_input("輸入股票代號",value=st.session_state.quick_sym or "",placeholder="台股如2330，美股如NVDA")
    with ic2: 
        st.write("")
        st.write("")
        go_btn = st.button("🔍 開始分析",use_container_width=True,type="primary")

    if "current_sym" not in st.session_state: 
        st.session_state.current_sym = ""
        
    if go_btn and ticker_in.strip(): 
        st.session_state.current_sym = ticker_in.strip()
    elif st.session_state.auto_analyze and st.session_state.quick_sym: 
        st.session_state.current_sym = st.session_state.quick_sym
        st.session_state.auto_analyze = False

    if st.session_state.current_sym:
        use_sym = st.session_state.current_sym
        sym = get_sym(use_sym, market)
        add_recent(sym)

        with st.spinner(f"抓取 {sym} 數據..."): 
            hist, info, err = fetch_data(sym, period)
            
        if err: 
            st.error(f"❌ {err}")
            st.stop()

        ind   = calc_indicators(hist)
        entry = calc_entry(ind, hist)
        score = calc_score(ind, info)
        co    = info.get("longName") or info.get("shortName") or sym

        hc,sc_col=st.columns([5,1])
        with hc: 
            st.subheader(f"📌 {co}({sym})")
        with sc_col:
            if sym not in st.session_state.watchlist:
                if st.button("⭐ 追蹤",use_container_width=True):
                    st.session_state.watchlist.append(sym)
                    if st.session_state.logged_in: 
                        db_add_wl(st.session_state.user_id,sym)
                    st.success("✅")
            else: 
                st.success("⭐ 追蹤中")

        st.markdown(f"**🏢 公司基本面:** 總市值 `{fmt_large(info.get('marketCap','N/A'))}` | 預估本益比 `{info.get('forwardPE','N/A')}` | 殖利率 `{info.get('dividendYield','N/A')}`")

        score_col, kpi_col = st.columns([1,2])
        with score_col:
            st.markdown(f'<div class="score-card"><div style="color:#64748b;font-size:11px">綜合健康評分</div><div class="big-score" style="color:{score["gc"]}">{score["total"]}</div><div style="color:#e2e8f0;font-size:13px">{score["grade"]}</div></div>',unsafe_allow_html=True)
        with kpi_col:
            st.markdown(f'<div class="status-card"><h3 style="margin:0;color:#e2e8f0">{ind["sc"]} {ind["status"]}</h3><p style="margin:5px 0 0;color:#94a3b8;font-size:13px">{ind["status_desc"]}</p></div>',unsafe_allow_html=True)
            ci="🔴" if ind["change_pct"]>=0 else "🟢"
            r1,r2,r3 = st.columns(3)
            r1.metric("💰 現價", ind["price"])
            r2.metric("今日", f"{ci}{ind['change_pct']}%", delta=str(ind["change_pct"]), delta_color="inverse")
            r3.metric("本月", f"{ind['change_1m']}%", delta=str(ind["change_1m"]), delta_color="inverse")

        st.divider()

        st.markdown("### ⏱️ 多週期技術面評估")
        c_dt, c_st, c_lt = st.columns(3)
        with c_dt:
            st.markdown(f"""
            <div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #f59e0b;height:100%;">
                <h4 style="margin-top:0;color:#f59e0b;">⚡ 當沖 (看今天)</h4>
                <div style="font-size:12px;color:#64748b;margin-bottom:8px;">關注: 有沒有爆量、有沒有踩穩均價</div>
                <div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['dt_status']}</div>
                <div style="font-size:13px;color:#94a3b8;">建議買點: <span style="color:#66cc66">{entry['agg_buy']}</span> | 快跑點: <span style="color:#ff6666">{entry['sl_tight']}</span></div>
            </div>""", unsafe_allow_html=True)
        with c_st:
            st.markdown(f"""
            <div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #3b82f6;height:100%;">
                <h4 style="margin-top:0;color:#3b82f6;">📈 波段 (抱幾週)</h4>
                <div style="font-size:12px;color:#64748b;margin-bottom:8px;">關注: 短期趨勢有沒有往上走</div>
                <div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['st_status']}</div>
                <div style="font-size:13px;color:#94a3b8;">建議買點: <span style="color:#66cc66">{entry['mod_buy']}</span> | 防守點: <span style="color:#ff6666">{entry['sl_normal']}</span></div>
            </div>""", unsafe_allow_html=True)
        with c_lt:
            st.markdown(f"""
            <div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #8b5cf6;height:100%;">
                <h4 style="margin-top:0;color:#8b5cf6;">💎 長線 (存很久)</h4>
                <div style="font-size:12px;color:#64748b;margin-bottom:8px;">關注: 長期大趨勢是不是健康的</div>
                <div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['lt_status']}</div>
                <div style="font-size:13px;color:#94a3b8;">便宜買點: <span style="color:#66cc66">{entry['con_buy']}</span> | 放棄點: <span style="color:#ff6666">{entry['sl_wide']}</span></div>
            </div>""", unsafe_allow_html=True)

        st.write("")

        with st.expander("💰 詳細操作策略與部位計算", expanded=False):
            e1,e2,e3 = st.columns(3)
            with e1: 
                st.markdown(f'<div class="entry-card"><div style="color:#66cc66;font-weight:bold">🎯 買入區</div><div style="margin:8px 0;color:#e2e8f0;line-height:2">長線建倉: <b>{entry["con_buy"]}</b><br>波段進場: <b>{entry["mod_buy"]}</b><br>當沖買入: <b>{entry["agg_buy"]}</b></div></div>',unsafe_allow_html=True)
            with e2: 
                st.markdown(f'<div class="stop-card"><div style="color:#ff6666;font-weight:bold">🛡️ 停損區 (保命用)</div><div style="margin:8px 0;color:#e2e8f0;line-height:2">當沖快跑: <b>{entry["sl_tight"]}</b><br>波段防守: <b>{entry["sl_normal"]}</b><br>長線底線: <b>{entry["sl_wide"]}</b></div></div>',unsafe_allow_html=True)
            with e3: 
                st.markdown(f'<div class="target-card"><div style="color:#66aaff;font-weight:bold">🎯 停利區 (賺夠就跑)</div><div style="margin:8px 0;color:#e2e8f0;line-height:2">短期目標: <b>{entry["tp1"]}</b><br>中期目標: <b>{entry["tp2"]}</b><br>最終目標: <b>{entry["tp3"]}</b></div></div>',unsafe_allow_html=True)
            
            st.markdown("#### ⚖️ 部位規模資金控管 (計算該買幾股)")
            st.caption("根據您的總資金與能承受的單筆虧損，計算最安全的買入股數。")
            ps1, ps2, ps3 = st.columns(3)
            capital_in = ps1.number_input("您的總資金 (元)", value=100000, step=10000)
            risk_in = ps2.number_input("單筆交易願承受風險 (%)", value=2.0, step=0.5, help="不超過 2% 比較安全")
            
            risk_amt = capital_in * (risk_in / 100)
            risk_per_share = max(entry['mod_buy'] - entry['sl_normal'], 0.01)
            suggested_shares = risk_amt / risk_per_share
            total_invested = suggested_shares * entry['mod_buy']
            
            with ps3:
                st.info(f"建議買入股數:\n### **{int(suggested_shares):,.0f} 股**")
                st.caption(f"佔用資金約 {total_invested:,.0f} 元")

        st.divider()
        st.markdown("### 📈 技術分析圖表")
        show_mc = st.checkbox("🎲 開啟蒙地卡羅30日模擬")
        mc_data = monte_carlo_simulation(hist) if show_mc else None

        buy_markers = []
        if sym in st.session_state.portfolio:
            entries = st.session_state.portfolio[sym]
            if isinstance(entries, dict): 
                entries = [entries]
            elif isinstance(entries, str): 
                entries = []
            for pd2 in entries:
                if isinstance(pd2, dict) and pd2.get("buy_date"):
                    try:
                        bdate = pd.to_datetime(pd2["buy_date"])
                        if bdate.tz: 
                            bdate = bdate.tz_localize(None)
                        buy_markers.append({"date":bdate,"price":pd2.get("cost")})
                    except: 
                        pass

        st.plotly_chart(build_main_chart(hist,ind,entry,sym,mc_data,buy_markers if buy_markers else None),use_container_width=True)

        st.divider()
        st.markdown("### [AI] 多週期三方辯論分析")
        if not api_key: 
            st.warning("⚠️ 請先於左側輸入 Gemini API 金鑰啟用 AI 分析。")
        elif st.button("⚔️ 啟動三方辯論 (約需 60~90 秒，依序執行防封鎖)",type="primary"):
            with st.spinner("AI 代理人撰寫白話文報告中 (為避免被 Google 封鎖，我們一位一位來)..."):
                try:
                    bull_rpt,bear_rpt,judge_rpt = ai_three_agent_debate(ind,info,sym,api_key,entry,score,macro_regime)
                    debate_tab1,debate_tab2,debate_tab3 = st.tabs(["🔴 多頭看漲原因","🟢 空頭看跌原因","🟣 裁判最終判定"])
                    
                    with debate_tab1:
                        st.markdown('<div class="bull-card"><b>🔴 多頭代理人 (負責找買入理由)</b></div>',unsafe_allow_html=True)
                        secs = bull_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True): 
                                st.markdown(lines[1] if len(lines)>1 else "")

                    with debate_tab2:
                        st.markdown('<div class="bear-card"><b>🟢 空頭代理人 (負責找潛在風險)</b></div>',unsafe_allow_html=True)
                        secs = bear_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True): 
                                st.markdown(lines[1] if len(lines)>1 else "")

                    with debate_tab3:
                        st.markdown('<div class="judge-card"><b>🟣 投資裁判 (總結給你看)</b></div>',unsafe_allow_html=True)
                        secs = judge_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            if "判定" in lines[0] or "建議" in lines[0] or "防守" in lines[0] or "真心話" in lines[0]:
                                st.markdown(f'<div class="predict-card"><div style="color:#c084fc;font-size:14px;font-weight:bold">## {lines[0]}</div></div>',unsafe_allow_html=True)
                                st.markdown(lines[1] if len(lines)>1 else "")
                            else:
                                with st.expander(f"## {lines[0]}",expanded=True): 
                                    st.markdown(lines[1] if len(lines)>1 else "")
                except Exception as e: 
                    st.error(f"❌ 分析失敗: {str(e)}")

# ══════════════════════════════════════════════
# TAB 2: 我的資產庫
# ══════════════════════════════════════════════
with TABS[1]:
    asset_tab1,asset_tab2,asset_tab3 = st.tabs(["💼 持股損益","⭐ 自選股","📋 交易記錄"])

    with asset_tab1:
        st.markdown("### 💼 持股損益試算")
        p1,p2,p3,p4,p5 = st.columns(5)
        with p1: 
            ps_ = st.text_input("代號",placeholder="如2330",key="pf_s_")
        with p2: 
            pc_ = st.number_input("買入成本",0.0,step=0.5,key="pf_c_")
        with p3: 
            pn_ = st.number_input("持有股數",0.0,step=100.0,key="pf_n_")
        with p4: 
            pd_ = st.date_input("買入日期",key="pf_d_")
        with p5: 
            st.write("")
            st.write("")
            p_btn = st.button("📊 計算",use_container_width=True,type="primary",key="pf_calc")

        if "show_pf_calc" not in st.session_state: 
            st.session_state.show_pf_calc = False
            
        if p_btn: 
            st.session_state.show_pf_calc = True

        if st.session_state.show_pf_calc and ps_.strip() and pc_>0 and pn_>0:
            ps_sym=get_sym(ps_.strip(),market)
            ph_,pi_,pe_=fetch_data(ps_sym,"5d")
            
            if pe_: 
                st.error(f"❌ {pe_}")
            else:
                cp_=round(float(ph_["Close"].iloc[-1]),2)
                pnl=round((cp_-pc_)*pn_,2)
                pct_v=round((cp_-pc_)/max(pc_,0.01)*100,2)
                tc=round(pc_*pn_,0)
                cv=round(cp_*pn_,0)
                hd=(date.today()-pd_).days
                ann=round(pct_v/max(hd,1)*365,2)
                
                st.subheader(f"📌 {ps_sym}")
                mc1,mc2,mc3,mc4,mc5=st.columns(5)
                mc1.metric("💰 現價",cp_)
                mc2.metric("📊 總成本",f"{tc:,.0f}")
                mc3.metric("💎 現值",f"{cv:,.0f}")
                mc4.metric("損益",f"{pnl:+,.0f}",delta=f"{pct_v:+.2f}%",delta_color="inverse")
                mc5.metric("年化",f"{ann:+.1f}%",delta=str(ann),delta_color="inverse")

                if api_key:
                    if st.button("[AI] 交易覆盤教練 (幫你抓蟲)",key="review_btn",type="primary"):
                        _h2,_,_=fetch_data(ps_sym,"6mo")
                        if _h2 is not None:
                            try:
                                _h2_idx = _h2.copy()
                                _h2_idx.index = pd.to_datetime(_h2_idx.index)
                                if _h2_idx.index.tz: 
                                    _h2_idx.index = _h2_idx.index.tz_localize(None)
                                near = _h2_idx.index[_h2_idx.index.searchsorted(pd.to_datetime(str(pd_)))]
                                row_buy = _h2_idx.loc[near]
                                ind_at_buy_str = f"收盤: {row_buy['Close']:.2f}"
                            except: 
                                ind_at_buy_str = "無數據"
                                
                            with st.spinner("教練撰寫報告中..."):
                                try:
                                    rev=ai_entry_critique(ps_sym,ps_sym,pc_,str(pd_),ind_at_buy_str,cp_,api_key)
                                    secs=rev.split("\n## ")
                                    st.markdown(secs[0])
                                    for sec in secs[1:]:
                                        lines=sec.split("\n",1)
                                        with st.expander(f"## {lines[0]}",expanded=True): 
                                            st.markdown(lines[1] if len(lines)>1 else "")
                                except Exception as e: 
                                    st.error(str(e)[:80])

                c1_s,c2_s=st.columns(2)
                with c1_s:
                    if st.button("💾 存入持股",key="save_pf"):
                        if ps_sym in st.session_state.portfolio:
                            entries = st.session_state.portfolio[ps_sym]
                            if isinstance(entries, dict): 
                                entries = [entries]
                            old_shares = sum(e.get("shares", 0) for e in entries)
                            old_cost_total = sum(e.get("cost", 0) * e.get("shares", 0) for e in entries)
                            total_shares = old_shares + pn_
                            avg_cost = (old_cost_total + (pc_ * pn_)) / total_shares if total_shares > 0 else 0
                            st.session_state.portfolio[ps_sym] = entries + [{"cost": pc_, "shares": pn_, "note": "", "buy_date": str(pd_)}]
                        else: 
                            st.session_state.portfolio[ps_sym] = [{"cost": pc_, "shares": pn_, "note": "", "buy_date": str(pd_)}]
                            
                        db_save_port(st.session_state.user_id, ps_sym, pc_, pn_, "", str(pd_))
                        st.success("✅ 已儲存")
                with c2_s:
                    if ps_sym in st.session_state.portfolio:
                        if st.button("🗑️ 移除此檔",key="del_pf"):
                            db_del_port(st.session_state.user_id,ps_sym)
                            del st.session_state.portfolio[ps_sym]
                            st.session_state.show_pf_calc = False
                            st.rerun()

        if st.session_state.portfolio:
            st.divider()
            st.markdown("### 📋 持股組合總覽")
            sector_map = {}
            pr_rows = []
            tc_all = 0
            cv_all = 0
            
            for sym, entries in st.session_state.portfolio.items():
                if isinstance(entries, dict): 
                    entries = [entries]
                total_s = sum(e.get("shares", 0) for e in entries)
                total_c = sum(e.get("cost", 0) * e.get("shares", 0) for e in entries)
                avg_c = round(total_c / total_s, 2) if total_s > 0 else 0
                try:
                    hh2 = yf.Ticker(sym).history(period="5d")
                    if "Close" in hh2.columns:
                        hh2_clean = hh2["Close"].dropna()
                        if not hh2_clean.empty:
                            cp2 = round(float(hh2_clean.iloc[-1]), 2)
                            pnl_pct = round((cp2 - avg_c) / max(avg_c, 0.01) * 100, 2)
                            v2 = round(cp2 * total_s, 0)
                            c2 = round(total_c, 0)
                            try: 
                                sec = yf.Ticker(sym).info.get("sector", "其他") or "其他"
                            except: 
                                sec = "其他"
                            sector_map[sym] = sec
                            pr_rows.append({"代號": sym, "均價": avg_c, "現價": cp2, "損益%": f"{pnl_pct:+.2f}%", "總損益": f"{v2-c2:+,.0f}", "總股數": total_s, "板塊": sec})
                            tc_all += c2
                            cv_all += v2
                except: 
                    pass
            
            if pr_rows:
                st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)
                tp = cv_all - tc_all
                tpct = round(tp / max(tc_all, 1) * 100, 2)
                st.metric("📊 組合總損益", f"{tp:+,.0f}元", delta=f"{tpct:+.2f}%", delta_color="inverse")
                
                if api_key:
                    if st.button("🏦 AI 投資長健檢你的股票池", type="primary"):
                        port_str = "\n".join([f"- {r['代號']}: 成本{r['均價']} 現價{r['現價']} 損益{r['損益%']}" for r in pr_rows])
                        with st.spinner("AI 投資長查帳中..."):
                            try:
                                cio_rpt = ai_portfolio_cio(port_str, str(sector_map), api_key)
                                secs = cio_rpt.split("\n## ")
                                st.markdown(secs[0])
                                for sec in secs[1:]:
                                    lines = sec.split("\n", 1)
                                    with st.expander(f"## {lines[0]}", expanded=True): 
                                        st.markdown(lines[1] if len(lines) > 1 else "")
                            except Exception as e: 
                                st.error(str(e)[:80])

            st.divider()
            st.markdown("#### 🗑️ 刪除特定買入分筆記錄")
            del_c1, del_c2 = st.columns([2, 2])
            with del_c1: 
                target_sym = st.selectbox("1. 選擇股票", options=list(st.session_state.portfolio.keys()))
            with del_c2:
                if target_sym:
                    entries = st.session_state.portfolio[target_sym]
                    if isinstance(entries, dict): 
                        entries = [entries] 
                    entry_options = {f"價 {e.get('cost','?')} | {e.get('shares','?')}股 | 日期 {e.get('buy_date','')}": e for e in entries}
                    selected_label = st.selectbox("2. 選擇分筆記錄", options=list(entry_options.keys()))
                    to_delete = entry_options[selected_label]
                    
            if target_sym and st.button("❌ 確認刪除"):
                if st.session_state.logged_in and "db_id" in to_delete: 
                    db_del_port_by_id(st.session_state.user_id, to_delete["db_id"])
                    
                if isinstance(st.session_state.portfolio[target_sym], list):
                    st.session_state.portfolio[target_sym].remove(to_delete)
                    if not st.session_state.portfolio[target_sym]: 
                        del st.session_state.portfolio[target_sym]
                else: 
                    del st.session_state.portfolio[target_sym] 
                    
                st.success("✅ 已刪除")
                st.rerun()

    with asset_tab2:
        st.markdown("### ⭐ 自選股即時監控")
        if not st.session_state.watchlist: 
            st.info("無追蹤清單")
        else:
            with st.spinner("批量抓取股價..."): 
                quotes=fetch_batch_quotes(tuple(st.session_state.watchlist))
            wrows=[]
            for s in st.session_state.watchlist:
                p_,ch_=quotes.get(s,(None,None))
                wrows.append({"代號":s,"現價":p_ or "N/A","今日":f"{'🔴+' if (ch_ or 0)>=0 else '🟢'}{ch_:.2f}%" if ch_ is not None else "-"})
                
            st.dataframe(pd.DataFrame(wrows),use_container_width=True,hide_index=True)
            bcols=st.columns(min(len(st.session_state.watchlist),6))
            
            for i,s in enumerate(st.session_state.watchlist[:6]):
                if bcols[i].button(f"📊{s}",key=f"wa_{i}"): 
                    st.session_state.quick_sym=s.replace(".TW","")
                    st.session_state.auto_analyze=True
                    st.rerun()

    with asset_tab3:
        st.markdown("### 📋 已平倉交易")
        with st.expander("➕ 新增交易"):
            t1,t2,t3,t4 = st.columns(4)
            with t1: t_sym=st.text_input("代號",key="th_sym")
            with t2: t_ep=st.number_input("買入價",0.0,step=0.5,key="th_ep")
            with t3: t_xp=st.number_input("賣出價",0.0,step=0.5,key="th_xp")
            with t4: t_sh=st.number_input("股數",0.0,step=100.0,key="th_sh")
            
            t5,t6,t7=st.columns(3)
            with t5: t_ed=st.date_input("買入日",key="th_ed")
            with t6: t_xd=st.date_input("賣出日",key="th_xd")
            with t7: t_note=st.text_input("備注",key="th_note")
            
            if st.button("💾 記錄此交易",key="add_trade_btn"):
                if t_sym.strip() and t_ep>0 and t_xp>0 and t_sh>0:
                    ts_sym=get_sym(t_sym.strip(),market)
                    pnl_a=round((t_xp-t_ep)*t_sh,2)
                    pnl_p=round((t_xp-t_ep)/max(t_ep,0.01)*100,2)
                    
                    db_add_trade(st.session_state.user_id if st.session_state.logged_in else "local", ts_sym,"LONG",t_ep,t_xp,t_sh,str(t_ed),str(t_xd),t_note)
                    st.session_state.trade_history.append({"symbol":ts_sym,"direction":"LONG","entry_price":t_ep,"exit_price":t_xp,"shares":t_sh,"entry_date":str(t_ed),"exit_date":str(t_xd),"pnl_amount":pnl_a,"pnl_pct":pnl_p,"note":t_note})
                    st.success("✅ 記錄成功")

        trades = st.session_state.trade_history
        if trades:
            tr_df=pd.DataFrame([{"代號":t.get("symbol",""),"買入價":t.get("entry_price",0),"賣出價":t.get("exit_price",0),"損益":f"{(t.get('pnl_amount') or 0):+,.0f}","損益%":f"{(t.get('pnl_pct') or 0):+.2f}%"} for t in trades])
            st.dataframe(tr_df,use_container_width=True,hide_index=True)
            win_t=sum(1 for t in trades if (t.get("pnl_pct") or 0)>0)
            st.metric("📊 累積損益",f"{sum((t.get('pnl_amount') or 0) for t in trades):+,.0f}元",delta=f"勝率{round(win_t/max(len(trades),1)*100,1)}%",delta_color="inverse")

# ══════════════════════════════════════════════
# TAB 3: 選股 + 回測
# ══════════════════════════════════════════════
with TABS[2]:
    scr_tab, dca_tab = st.tabs(["🔎 技術選股","⏳ 定期定額回測"])
    
    with scr_tab:
        col1,col2 = st.columns(2)
        with col1: 
            scr_rsi_lt = st.number_input("RSI <",0.0,100.0,35.0,step=5.0)
            scr_macd = st.checkbox("MACD > 0")
            scr_ma20 = st.checkbox("站上月線")
        with col2: 
            scr_rsi_gt = st.number_input("RSI >",0.0,100.0,0.0,step=5.0)
            scr_vol = st.checkbox("放量>1.5")
            scr_bb_lo = st.checkbox("布林<25%")
            
        if st.button("🔍 掃描熱門股",type="primary",use_container_width=True):
            all_syms = []
            for v in (TW_HOT if "台股" in market else US_HOT).values():
                for s,_ in v:
                    all_syms.append(get_sym(s,market))
                    
            cond = {}
            if scr_rsi_lt>0: 
                cond["rsi_lt"] = scr_rsi_lt
            if scr_rsi_gt>0: 
                cond["rsi_gt"] = scr_rsi_gt
            if scr_macd: 
                cond["macd_cross_up"] = True
            if scr_ma20: 
                cond["above_ma20"] = True
            if scr_vol: 
                cond["vol_spike"] = True
            if scr_bb_lo: 
                cond["bb_near_lower"] = True
                
            with st.spinner("掃描中..."): 
                results = run_screener(all_syms,cond)
            if results: 
                st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
            else: 
                st.info("無結果")

    with dca_tab:
        d1,d2,d3,d4=st.columns(4)
        with d1: 
            dca_sym=st.text_input("代號",placeholder="如0050",key="dca_s")
        with d2: 
            dca_amt=st.number_input("月投入",1000.0,1000000.0,10000.0,step=1000.0)
        with d3: 
            dca_yr =st.selectbox("年限",[3,5,10,15,20],index=1)
        with d4: 
            st.write("")
            st.write("")
            dca_btn=st.button("⏳ 回測",type="primary")
            
        if dca_btn and dca_sym.strip():
            with st.spinner("模擬與比對大盤基準中..."): 
                df_dca,stats,err=run_dca(get_sym(dca_sym.strip(),market),dca_amt,dca_yr,market)
            if df_dca is None: 
                st.error(err)
            else:
                st.markdown("#### 🏆 定期定額 vs 大盤基準 (Sharpe Ratio)")
                st.caption("夏普值(Sharpe Ratio)代表承擔每1%風險所能獲得的超額報酬。一般認為 > 1 為佳。")
                cols = st.columns(4)
                for idx, (k,v) in enumerate(stats.items()): 
                    cols[idx % 4].metric(k,v)
                st.plotly_chart(build_dca_chart(df_dca,dca_sym),use_container_width=True)

# ══════════════════════════════════════════════
# TAB 4: 市場總覽
# ══════════════════════════════════════════════
with TABS[3]:
    if st.button("🔄 載入板塊熱力圖",type="primary"):
        with st.spinner("抓取板塊數據..."): 
            df_hm = fetch_heatmap_data(market)
        if not df_hm.empty: 
            st.plotly_chart(build_heatmap_chart(df_hm,market),use_container_width=True)
            
    st.divider()
    st.markdown("### 📊 主要指數")
    
    for row in fetch_market_overview():
        c=TW_UP if row["漲跌%"]>=0 else TW_DOWN
        st.markdown(f'<div style="background:#1e1e2e;border-radius:8px;padding:10px 16px;margin:3px 0;border-left:4px solid {c};display:flex;justify-content:space-between"><span style="color:#e2e8f0">{row["名稱"]}</span><span style="color:{c};font-weight:bold">{row["現值"]} {"▲" if row["漲跌%"]>=0 else "▼"}{abs(row["漲跌%"]):.2f}%</span></div>',unsafe_allow_html=True)

# ══════════════════════════════════════════════
# TAB 5: 行為偏誤診斷
# ══════════════════════════════════════════════
with TABS[4]:
    trades = st.session_state.trade_history
    if len(trades)<3: 
        st.warning("⚠️ 需要至少3筆已平倉記錄才能進行行為分析。")
    else:
        bias = analyze_behavioral_bias(trades)
        if bias:
            b1,b2,b3,b4 = st.columns(4)
            b1.metric("勝率",f"{bias['win_rate']}%")
            b2.metric("平均獲利",f"+{bias['avg_win_pct']:.2f}%")
            b3.metric("平均虧損",f"-{bias['avg_loss_pct']:.2f}%")
            b4.metric("盈虧比",f"{round(bias['avg_win_pct']/max(bias['avg_loss_pct'],0.01),2)}x")
            
            b5,b6,b7 = st.columns(3)
            b5.metric("持有獲利天數",f"{bias['avg_win_days']:.0f}天")
            b6.metric("持有虧損天數",f"{bias['avg_loss_days']:.0f}天",delta="⚠️ 異常" if bias['avg_loss_days']>bias['avg_win_days'] else "正常",delta_color="off")
            
            if bias["disposition_effect"]: 
                st.error("🚨 偵測到處置效應 (持有虧損股時間顯著長於獲利股)！請嚴格執行停損。")
            
            if api_key and st.button("🧠 AI 幫你抓投資壞習慣",type="primary"):
                with st.spinner("教練評估中..."):
                    try:
                        bias_rpt = ai_bias_warning(bias, "\n".join([f"- {t.get('symbol','')}: 損益{t.get('pnl_pct',0):+.1f}%" for t in trades[:10]]), api_key)
                        secs = bias_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            with st.expander(f"## {lines[0]}",expanded=True): 
                                st.markdown(lines[1] if len(lines)>1 else "")
                    except Exception as e: 
                        st.error(str(e)[:80])

st.divider()
st.caption("📈 股市小白分析系統 Pro V5.3 | 🔴紅漲🟢跌 | ⚠️ 內容僅供學習參考，不構成投資建議")