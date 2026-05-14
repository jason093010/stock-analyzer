# ╔═══════════════════════════════════════════════════════════════════╗
# ║  股市小白分析系統 Pro  V7.4  ─  富果API解碼修正版 (徹底修復渲染)  ║
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
import time
import hashlib
import base64
import json
import os
import requests
from datetime import datetime, date, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    from streamlit_cookies_controller import CookieController
    cookie_controller = CookieController()
except ImportError:
    cookie_controller = None

TW_TZ = timezone(timedelta(hours=8))

# ══════════════════════════════════════════════
# 0. 全域常數與 API 金鑰設定 (自動 Base64 解碼)
# ══════════════════════════════════════════════
_RAW_FUGLE = "ZWU4MDYwOTYtM2M0NC00YWNhLTkwYjMtOGEyMzYzOWE5NDQ0IGExOTkzODI1LWZhZjQtNGE1My1hYzNjLWY1MzEwMTEzNGFiYQ=="
try:
    _decoded = base64.b64decode(_RAW_FUGLE).decode('utf-8').split()
    FUGLE_API_KEY = _decoded[-1] # 取出真實的 UUID 金鑰
except:
    FUGLE_API_KEY = _RAW_FUGLE

# ══════════════════════════════════════════════
# 1. 頁面設定與 CSS
# ══════════════════════════════════════════════
st.set_page_config(page_title="股市小白分析系統 Pro V7.4", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

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
.tag-badge {display:inline-block; padding:4px 8px; margin:2px; border-radius:4px; font-size:12px; font-weight:bold; background:#3b82f6; color:white;}
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
except Exception: 
    pass

_DEFS = dict(
    user_id=None, username=None, logged_in=False, _pin="", api_key="", 
    watchlist=[], alerts={}, portfolio={}, trade_history=[], recent_searches=[], 
    quick_sym="", auto_analyze=False, macro_regime="未知", macro_auto_tried=False, cash_balance=100000.0
)

for k, v in _DEFS.items():
    if k not in st.session_state: st.session_state[k] = v

# ══════════════════════════════════════════════
# 3. 加密工具與資料庫函數
# ══════════════════════════════════════════════
_SALT = b"tw_stock_pro_v7_salt"

def _derive_key(pin: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(pin.encode()))

def encrypt_key(api_key: str, pin: str) -> str: 
    return Fernet(_derive_key(pin)).encrypt(api_key.encode()).decode()

def decrypt_key(token: str, pin: str) -> str:
    try: return Fernet(_derive_key(pin)).decrypt(token.encode()).decode()
    except: return ""

def make_uid(username: str, pin: str) -> str: 
    return hashlib.sha256(f"{username.lower().strip()}:{pin}".encode()).hexdigest()[:20]

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
            "user_id":uid,"symbol":sym,"direction":direction, "entry_price":entry_price,
            "exit_price":exit_price,"shares":shares,"entry_date":entry_date,
            "exit_date":exit_date, "pnl_amount":pnl_amt,"pnl_pct":pnl_pct,"note":note
        }).execute()
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

MACRO_REGIMES = ["未知","成長擴張(Risk-On)","通膨衰退(Stagflation)","衰退(Risk-Off)","復甦反彈(Early Cycle)","流動性危機"]

def get_sym(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW") and not raw.endswith(".TWO"): 
        return raw + ".TW"
    return raw

def safe_f(val, default=0.0) -> float:
    try: v = float(val); return v if v == v else default
    except: return default

def add_recent(sym: str):
    r = st.session_state.recent_searches
    if sym in r: r.remove(sym)
    r.insert(0, sym)
    st.session_state.recent_searches = r[:8]

# ══════════════════════════════════════════════
# 5. 數據抓取模組 (富果 Fugle 優先 > FinMind > yfinance)
# ══════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def fetch_data(symbol: str, period: str):
    err_msg = ""
    is_tw = symbol.endswith(".TW") or symbol.endswith(".TWO") or symbol.isdigit()
    tw_sym = symbol.replace(".TW", "").replace(".TWO", "")

    # 1. 富果 Fugle API (台股優先，包含歷史 K 線與即時報價)
    if is_tw and FUGLE_API_KEY:
        try:
            days_map = {"3mo": 90, "6mo": 180, "1y": 365, "2y": 730}
            days = days_map.get(period, 180)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            headers = {"X-API-KEY": FUGLE_API_KEY}
            params = {
                "timeframe": "D",
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d")
            }
            
            # A. 獲取歷史 K 線
            url = f"https://openapi.fugle.tw/marketdata/v1.0/stock/historical/candles/{tw_sym}"
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and data["data"]:
                    df = pd.DataFrame(data["data"])
                    df = df.rename(columns={"date":"Date", "open":"Open", "high":"High", "low":"Low", "close":"Close", "volume":"Volume"})
                    df["Date"] = pd.to_datetime(df["Date"])
                    df = df.set_index("Date").sort_index()
                    
                    # B. 獲取盤中即時報價，並更新至 DataFrame 尾端
                    quote_url = f"https://openapi.fugle.tw/marketdata/v1.0/stock/intraday/quote/{tw_sym}"
                    q_resp = requests.get(quote_url, headers=headers, timeout=5)
                    if q_resp.status_code == 200:
                        q_data = q_resp.json()
                        today_str = q_data.get("date")
                        if today_str:
                            today_dt = pd.to_datetime(today_str)
                            c_price = q_data.get("closePrice", q_data.get("previousClose", 0))
                            o_price = q_data.get("openPrice", c_price)
                            h_price = q_data.get("highPrice", c_price)
                            l_price = q_data.get("lowPrice", c_price)
                            vol = q_data.get("total", {}).get("tradeVolume", 0)
                            
                            if c_price > 0:
                                df.loc[today_dt] = {"Open": o_price, "High": h_price, "Low": l_price, "Close": c_price, "Volume": vol}
                    
                    if not df.empty:
                        # C. 嘗試取得標的資訊 (產業分類等)
                        info = {'longName': symbol, 'sector': '台股', 'raw_yield': 0.0, 'fetch_time': datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"), 'source': 'Fugle 富果 (含即時)'}
                        try:
                            ticker_url = f"https://openapi.fugle.tw/marketdata/v1.0/stock/intraday/ticker/{tw_sym}"
                            t_resp = requests.get(ticker_url, headers=headers, timeout=5)
                            if t_resp.status_code == 200:
                                t_data = t_resp.json()
                                info['longName'] = t_data.get("name", symbol)
                                info['sector'] = t_data.get("industry", "台股")
                        except: pass
                        
                        return df, info, None
            elif resp.status_code == 401:
                print(f"[{tw_sym}] Fugle API 認證失敗，可能金鑰失效。")
        except Exception as e:
            err_msg += f"Fugle API 失效: {str(e)[:50]} | "

    # 2. FinMind API (台股備援)
    if is_tw:
        try:
            from FinMind.data import DataLoader
            dl = DataLoader()
            days = {"3mo": 90, "6mo": 180, "1y": 365, "2y": 730}.get(period, 180)
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            fm_data = dl.taiwan_stock_daily(stock_id=tw_sym, start_date=start_date)
            if not fm_data.empty:
                fm_data = fm_data.rename(columns={"date": "Date", "open": "Open", "max": "High", "min": "Low", "close": "Close", "Trading_Volume": "Volume"})
                fm_data["Date"] = pd.to_datetime(fm_data["Date"])
                fm_data = fm_data.set_index("Date")
                info = {'longName': symbol, 'sector': '台股', 'raw_yield': 0.0, 'fetch_time': datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"), 'source': 'FinMind (備援)'}
                return fm_data, info, None
        except Exception as fm_e:
            err_msg += f"FinMind 失效: {str(fm_e)[:50]} | "

    # 3. Yahoo Finance (美股主力 / 台股最後備援)
    try:
        h = yf.download(symbol, period=period, progress=False)
        if h is not None and not h.empty:
            if isinstance(h.columns, pd.MultiIndex): h.columns = [col[0] for col in h.columns]
            if "Close" in h.columns: h = h.dropna(subset=["Close"])
            if not h.empty:
                info = {}
                try:
                    t = yf.Ticker(symbol)
                    info['longName'] = t.info.get('longName', symbol)
                    info['sector'] = t.info.get('sector', '其他')
                    dy = t.info.get('dividendYield', 'N/A')
                    info['raw_yield'] = dy if isinstance(dy, float) else 0.0
                except: 
                    info = {'longName': symbol, 'sector': '其他', 'raw_yield': 0.0}
                info['fetch_time'] = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
                info['source'] = 'Yahoo Finance'
                return h, info, None
    except Exception as yf_e:
        err_msg += f"YF 失效: {str(yf_e)[:50]}"

    return None, None, f"抓取失敗: {err_msg}"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_news(symbol: str):
    try:
        t = yf.Ticker(symbol)
        news = t.news
        if not news: return []
        return [{"title": n.get("title",""), "publisher": n.get("publisher","")} for n in news[:30]]
    except: return []

@st.cache_data(ttl=120, show_spinner=False)
def fetch_market_overview():
    syms = {"台灣加權":"^TWII","S&P 500":"^GSPC","那斯達克":"^IXIC","VIX恐慌":"^VIX","費城半導":"^SOX","美元指數":"DX-Y.NYB"}
    tickers = list(syms.values())
    rows = []
    try:
        data = yf.download(tickers, period="5d", group_by="ticker", progress=False)
        for name, sym in syms.items():
            try:
                df = data[sym] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
                if "Close" in df.columns:
                    df_clean = df["Close"].dropna()
                    if len(df_clean) >= 2:
                        c1 = float(df_clean.iloc[-2])
                        c2 = float(df_clean.iloc[-1])
                        rows.append({"名稱":name, "現值":round(c2, 2), "漲跌%":round((c2 - c1) / max(c1, 0.01) * 100, 2)})
            except: continue
    except: pass
    return sorted(rows, key=lambda x: list(syms.keys()).index(x["名稱"])) if rows else []

@st.cache_data(ttl=600, show_spinner=False)
def fetch_heatmap_data(market: str) -> pd.DataFrame:
    hot = TW_HOT if "台股" in market else US_HOT
    tickers, sym_map, rows = [], {}, []
    for sector, stocks in hot.items():
        for sym_, name_ in stocks:
            full = sym_+".TW" if "台股" in market and not sym_.endswith(".TW") else sym_
            tickers.append(full)
            sym_map[full] = (sector, name_)
    if not tickers: return pd.DataFrame()
    try:
        data = yf.download(tickers, period="5d", group_by="ticker", progress=False)
        for full in tickers:
            try:
                df = data[full] if len(tickers)>1 else data
                if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
                if "Close" in df.columns:
                    df_clean = df["Close"].dropna()
                    if len(df_clean) >= 2:
                        c1, c2 = float(df_clean.iloc[-2]), float(df_clean.iloc[-1])
                        if c1 > 0:
                            sector, name = sym_map[full]
                            rows.append({"板塊": sector, "名稱": name, "代號": full.replace(".TW",""), "漲跌%": round((c2 - c1) / c1 * 100, 2), "市值": 1e9})
            except: continue
    except: pass
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════
# 6. 多週期量化指標計算
# ══════════════════════════════════════════════
def calc_indicators(hist: pd.DataFrame) -> dict:
    c, h, l, v = hist["Close"].astype(float), hist["High"].astype(float), hist["Low"].astype(float), hist["Volume"].astype(float)
    n = len(c)

    def _last(s):
        try: val = float(s.iloc[-1]); return val if val==val else 0.0
        except: return 0.0

    ma5, ma20, ma60 = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(min(60,n)).mean()
    ema12, ema26 = c.ewm(span=12,adjust=False).mean(), c.ewm(span=26,adjust=False).mean()
    macd = ema12-ema26
    macd_s = macd.ewm(span=9,adjust=False).mean()
    macd_h = macd-macd_s

    d = c.diff()
    gain, loss = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
    rsi = (100-100/(1+gain/loss.replace(0,1e-10))).clip(0,100)

    r_min, r_max = rsi.rolling(14).min(), rsi.rolling(14).max()
    stk = (100*(rsi-r_min)/(r_max-r_min+1e-10)).clip(0,100)
    std_ = stk.rolling(3).mean()

    bb_m, bb_s = c.rolling(20).mean(), c.rolling(20).std()
    bb_u, bb_l = bb_m+2*bb_s, bb_m-2*bb_s
    bb_pct = ((c-bb_l)/(bb_u-bb_l+1e-10)*100).clip(0,100)
    bb_w = ((bb_u-bb_l)/(bb_m+1e-10)*100)

    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    obv = (v*((c.diff()>0).astype(float)*2-1)).fillna(0).cumsum()
    hh, ll_ = h.rolling(14).max(), l.rolling(14).min()
    wr = (-100*(hh-c)/(hh-ll_+1e-10)).clip(-100,0)
    vwap = ((h+l+c)/3*v).rolling(20).sum()/(v.rolling(20).sum()+1e-10)

    price, atr_v = round(_last(c),2), round(_last(atr),4)
    if atr_v==0: atr_v = round(price*0.02,2)

    def chg(k):
        if n>k: ref = safe_f(c.iloc[-(k+1)]); return round((price-ref)/max(ref,0.01)*100,2)
        return 0.0

    ind = {
        "price": price, "change_pct": chg(1), "change_5d": chg(5), "change_1m": chg(21),
        "ma5": round(_last(ma5),2), "ma20": round(_last(ma20),2), "ma60": round(_last(ma60),2),
        "vwap": round(_last(vwap),2), "rsi": round(_last(rsi),1), "stoch_k": round(_last(stk),1),
        "stoch_d": round(_last(std_),1), "williams_r": round(_last(wr),1),
        "macd": round(_last(macd),4), "macd_sig": round(_last(macd_s),4), "macd_hist": round(_last(macd_h),4),
        "atr": atr_v, "bb_upper": round(_last(bb_u),2), "bb_mid": round(_last(bb_m),2), "bb_lower": round(_last(bb_l),2),
        "bb_pct": round(_last(bb_pct),1), "bb_width": round(_last(bb_w),1),
        "volume": int(_last(v)), "vol_ma20": int(_last(v.rolling(20).mean())), "obv": round(_last(obv),0),
        "high_52w": round(float(c.rolling(min(252,n)).max().iloc[-1]),2), "low_52w": round(float(c.rolling(min(252,n)).min().iloc[-1]),2),
        "_c": c, "_h": h, "_l": l, "_v": v, "_rsi": rsi, "_stk": stk, 
        "_macd": macd, "_macd_sig": macd_s, "_macd_h": macd_h,
        "_bb_u": bb_u, "_bb_l": bb_l, "_bb_m": bb_m, "_ma5": ma5, "_ma20": ma20, "_ma60": ma60, "_obv": obv, "_hist": hist,
    }

    vr = ind["volume"] / max(ind["vol_ma20"], 1)
    ind["vol_ratio"] = round(vr, 2)
    if vr >= 2.5: ind["vol_desc"] = f"🔥爆量{vr:.1f}倍均量"
    elif vr >= 1.5: ind["vol_desc"] = f"📢放量{vr:.1f}倍"
    elif vr >= 0.8: ind["vol_desc"] = f"📊正常量{vr:.1f}倍"
    else: ind["vol_desc"] = f"😴縮量{vr:.1f}倍"

    pos = (price - ind["low_52w"]) / max(ind["high_52w"] - ind["low_52w"], 0.01) * 100
    ind["position_52w"] = round(pos, 1)
    
    ind["dt_status"] = "強勢 (站上VWAP且放量)" if price > ind["vwap"] and vr > 1.2 else "弱勢 (VWAP壓制)" if price < ind["vwap"] else "震盪 (貼近VWAP)"
    ind["st_status"] = "偏多 (站上月線且RSI>50)" if ind["ma5"] > ind["ma20"] and ind["rsi"] > 50 else "偏空 (跌破月線且RSI<50)" if ind["ma5"] < ind["ma20"] and ind["rsi"] < 50 else "盤整 (均線糾結或指標分歧)"
    ind["lt_status"] = "多頭格局 (季線之上且強勢)" if price > ind["ma60"] and pos > 50 else "空頭/超賣 (季線之下且弱勢)" if price < ind["ma60"] and pos < 30 else "中性格局 (季線震盪)"

    rv, kv, mv = ind["rsi"], ind["stoch_k"], ind["macd_hist"]
    if ind["ma5"] > ind["ma20"] > ind["ma60"] and rv > 55 and mv > 0: 
        ind["status"], ind["sc"], ind["status_desc"] = "強勢多頭 📈", "🔴", "均線多頭排列，上漲動能強"
    elif ind["ma5"] < ind["ma20"] < ind["ma60"] and rv < 45 and mv < 0: 
        ind["status"], ind["sc"], ind["status_desc"] = "強勢空頭 📉", "🟢", "均線空頭排列，下跌壓力大"
    elif rv <= 30 and kv < 20: 
        ind["status"], ind["sc"], ind["status_desc"] = "雙重超賣 🟡", "🟡", "跌很多了，隨時可能出現反彈"
    elif rv >= 70 and kv > 80: 
        ind["status"], ind["sc"], ind["status_desc"] = "雙重超買 🟡", "🟡", "漲太多了，短期可能有獲利了結賣壓"
    elif abs(ind["ma5"] - ind["ma20"]) / max(price, 0.01) < 0.015: 
        ind["status"], ind["sc"], ind["status_desc"] = "盤整蓄勢 ⚪", "⚪", "價格上下震盪，等待出明確方向"
    elif ind["ma5"] > ind["ma20"] and rv > 50: 
        ind["status"], ind["sc"], ind["status_desc"] = "短線偏多 🔵", "🔵", "短期趨勢向上，多方稍微佔優勢"
    else: 
        ind["status"], ind["sc"], ind["status_desc"] = "方向不明 🟠", "🟠", "走勢疲軟，建議新手先觀望"

    return ind

def calc_score(ind: dict, info: dict) -> dict:
    trend = min(30, (8 if ind["ma5"] > ind["ma20"] else 0) + (8 if ind["ma20"] > ind["ma60"] else 0) + (7 if ind["price"] > ind["ma20"] else 0) + (7 if ind["macd_hist"] > 0 else 0))
    rv, kv, wrv = ind["rsi"], ind["stoch_k"], ind["williams_r"]
    mom = min(25, (10 if 50 <= rv <= 70 else 8 if rv < 30 else 5 if 40 <= rv < 50 else 3) + (8 if 40 <= kv <= 80 else 5 if kv < 20 else 0) + (7 if wrv > -50 else 0))
    vr = ind["vol_ratio"]
    vol = min(20, 20 if vr >= 1.5 and ind["change_pct"] > 0 else 15 if vr >= 1.2 and ind["change_pct"] > 0 else 10 if 0.8 <= vr <= 1.5 else 5)
    pos = ind["position_52w"]
    psc = min(15, 15 if 30 <= pos <= 70 else 12 if pos < 20 else 10 if pos < 30 or pos < 80 else 4)
    bsc = min(10, 10 if 20 <= ind["bb_pct"] <= 80 else 7 if ind["bb_pct"] < 20 else 3)
    total = trend + mom + vol + psc + bsc
    
    if total >= 80: grade, gc = "A(優秀)", "#ff4444"
    elif total >= 65: grade, gc = "B(良好)", "#ff8800"
    elif total >= 50: grade, gc = "C(普通)", "#ffcc00"
    elif total >= 35: grade, gc = "D(偏弱)", "#88cc44"
    else: grade, gc = "E(警示)", "#22aa44"
    return {"total":total,"grade":grade,"gc":gc,"trend":trend,"mom":mom,"vol":vol,"pos":psc,"bb":bsc}

def calc_entry(ind: dict, hist: pd.DataFrame) -> dict:
    c, h, l, price = ind["_c"], ind["_h"], ind["_l"], ind["price"]
    atr = max(ind["atr"], price * 0.005)
    w = min(60, len(c))
    ph, pl = round(float(h.iloc[-w:].max()), 2), round(float(l.iloc[-w:].min()), 2)
    fr = max(ph - pl, atr)
    fibs = {k:round(ph - v * fr, 2) for k,v in [("0.236",0.236),("0.382",0.382),("0.500",0.500),("0.618",0.618),("0.786",0.786)]}
    sup1, sup2 = round(float(l.iloc[-20:].min()), 2), round(float(l.iloc[-w:].min()), 2)
    res1, res2 = round(float(h.iloc[-20:].max()), 2), round(float(h.iloc[-w:].max()), 2)
    
    agg_buy = round(price * 0.995, 2)                 
    mod_buy = round((sup1 + ind["ma20"]) / 2, 2)        
    con_buy = round(min(sup1, fibs["0.382"]), 2)     
    sl_tight = round(price - 1.5 * atr, 2)              
    sl_normal = round(price - 2.5 * atr, 2)             
    sl_wide = round(max(sup2 * 0.97, price - 4 * atr), 2)  
    tp1, tp2, tp3 = round(price + 2 * atr, 2), round(price + 4 * atr, 2), round(max(res2 * 1.02, price + 6 * atr), 2)
    rr = round((tp1 - mod_buy) / max(mod_buy - sl_normal, 0.01), 2)
    
    return dict(fibs=fibs, sup1=sup1, sup2=sup2, res1=res1, res2=res2, con_buy=con_buy, mod_buy=mod_buy, agg_buy=agg_buy, sl_tight=sl_tight, sl_normal=sl_normal, sl_wide=sl_wide, tp1=tp1, tp2=tp2, tp3=tp3, rr=rr, ph=ph, pl=pl, atr=atr, lot_cost=round(mod_buy*1000,0))

def monte_carlo_simulation(hist: pd.DataFrame, days: int = 30, simulations: int = 2000) -> dict:
    close = hist["Close"].astype(float)
    log_returns = np.log(close / close.shift(1)).dropna()
    mu, sigma, last_price = float(log_returns.mean()), float(log_returns.std()), float(close.iloc[-1])
    dt = 1
    np.random.seed(42)
    rand_matrix = np.random.standard_normal((simulations, days))
    price_matrix = np.zeros((simulations, days))
    price_matrix[:, 0] = last_price * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, 0])
    for t in range(1, days): price_matrix[:, t] = price_matrix[:, t-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rand_matrix[:, t])
    percentiles = {"p02": np.percentile(price_matrix, 2.5, axis=0), "p16": np.percentile(price_matrix, 16, axis=0), "p50": np.percentile(price_matrix, 50, axis=0), "p84": np.percentile(price_matrix, 84, axis=0), "p97": np.percentile(price_matrix, 97.5, axis=0)}
    future_dates = [hist.index[-1] + timedelta(days=i+1) for i in range(days)]
    return {"dates": future_dates, "pcts": percentiles, "last": last_price, "mu": mu, "sigma": sigma, "matrix_sample": price_matrix[:50]}

def run_screener(symbols: list, conditions: dict) -> list:
    results = []
    def _check(sym):
        try:
            h, info, err = fetch_data(sym, "3mo")
            if err or h is None: return None
            ind = calc_indicators(h)
            ok = True
            if conditions.get("rsi_lt") and ind["rsi"] >= conditions["rsi_lt"]: ok = False
            if conditions.get("rsi_gt") and ind["rsi"] <= conditions["rsi_gt"]: ok = False
            if conditions.get("macd_cross_up") and ind["macd_hist"] <= 0: ok = False
            if conditions.get("above_ma20") and ind["price"] <= ind["ma20"]: ok = False
            if conditions.get("vol_spike") and ind["vol_ratio"] < 1.5: ok = False
            if conditions.get("bb_near_lower") and ind["bb_pct"] > 25: ok = False
            if ok: return {"代號":sym,"現價":ind["price"],"RSI":ind["rsi"],"MACD_H":ind["macd_hist"],"量比":ind["vol_ratio"],"狀態":ind["status"],"評分":calc_score(ind,info)["total"]}
        except: pass
        return None
        
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(_check,s) for s in symbols]
        for f in as_completed(futs):
            r = f.result()
            if r: results.append(r)
    return sorted(results, key=lambda x: x["評分"], reverse=True)

def run_dca(symbol: str, monthly_amount: float, years: int, market: str):
    bm_sym = "^TWII" if "台股" in market else "^GSPC"
    hist, _, err = fetch_data(symbol, f"{years}y")
    if err or hist is None: return None, None, err
        
    hist = hist.copy()
    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz: hist.index = hist.index.tz_localize(None)
    hist["ym"] = hist.index.to_period("M")
    monthly = hist.groupby("ym").first()
    
    recs = []
    total_inv, total_sh = 0.0, 0.0
    for period_lbl, row in monthly.iterrows():
        price = float(row["Close"])
        if price <= 0: continue
        total_sh += monthly_amount / price
        total_inv += monthly_amount
        recs.append({"date":period_lbl.to_timestamp(), "累積投入":total_inv, "資產現值":total_sh * price})
        
    if not recs: return None, None, "無足夠歷史數據"
        
    df = pd.DataFrame(recs).set_index("date")
    fv = df["資產現值"].iloc[-1]
    rtn = round((fv - total_inv) / max(total_inv, 0.01) * 100, 2)
    peak = df["資產現值"].cummax()
    mdd = round(((df["資產現值"] - peak) / (peak + 1e-10) * 100).min(), 2)
    
    bm_hist, _, _ = fetch_data(bm_sym, f"{years}y")
    bm_rtn_str, sharpe_str = "N/A", "N/A"
    
    if bm_hist is not None and not bm_hist.empty:
        try:
            bm_clean = bm_hist["Close"].dropna()
            if len(bm_clean) > 0:
                bm_start, bm_end = float(bm_clean.iloc[0]), float(bm_clean.iloc[-1])
                bm_rtn_str = f"{((bm_end - bm_start) / bm_start) * 100:+.2f}%"
            daily_returns = hist["Close"].pct_change().dropna()
            ann_vol = daily_returns.std() * np.sqrt(252) * 100
            if ann_vol > 0: sharpe_str = f"{(rtn / max(years, 1) - 2.0) / ann_vol:.2f}"
        except: pass
            
    stats = {"總投入本金": round(total_inv, 0), "最終資產現值": round(fv, 0), "累積報酬率": f"{rtn:+.2f}%", "大盤同期報酬": bm_rtn_str, "年化報酬率": f"{rtn/max(years,1):+.2f}%", "最大回撤MDD": f"{mdd:.2f}%", "夏普值": sharpe_str}
    return df, stats, None

def analyze_behavioral_bias(trades: list) -> dict:
    if len(trades) < 3: return {}
    wins  = [t for t in trades if (t.get("pnl_pct") or 0) > 0]
    loses = [t for t in trades if (t.get("pnl_pct") or 0) <= 0]
    if not wins or not loses: return {}
        
    def hold_days(t):
        try: return (date.fromisoformat(t.get("exit_date","")) - date.fromisoformat(t.get("entry_date",""))).days
        except: return 0
            
    avg_win_pct = sum(t.get("pnl_pct",0) for t in wins) / len(wins)
    avg_loss_pct = sum(abs(t.get("pnl_pct",0)) for t in loses) / len(loses)
    avg_win_days = sum(hold_days(t) for t in wins) / len(wins)
    avg_loss_days = sum(hold_days(t) for t in loses) / len(loses)
    disposition = avg_loss_days > avg_win_days * 1.3 and avg_loss_pct > avg_win_pct
    
    return {"win_count": len(wins), "lose_count": len(loses), "avg_win_pct": round(avg_win_pct, 2), "avg_loss_pct": round(avg_loss_pct, 2), "avg_win_days": round(avg_win_days, 1), "avg_loss_days": round(avg_loss_days, 1), "disposition_effect": disposition, "win_rate": round(len(wins) / len(trades) * 100, 1)}

def backtest_ma_crossover(hist: pd.DataFrame, short_w=5, long_w=20):
    df = hist.copy()
    df['SMA_S'] = df['Close'].rolling(short_w).mean()
    df['SMA_L'] = df['Close'].rolling(long_w).mean()
    df['Signal'] = np.where(df['SMA_S'] > df['SMA_L'], 1, 0)
    df['Position'] = df['Signal'].diff()
    
    trades = []
    buy_price = 0
    for date_val, row in df[df['Position'] != 0].dropna().iterrows():
        if row['Position'] == 1: buy_price = row['Close']
        elif row['Position'] == -1 and buy_price != 0:
            trades.append((row['Close'] - buy_price) / buy_price * 100)
            buy_price = 0
            
    win_rate = sum(1 for t in trades if t > 0) / len(trades) if trades else 0
    return win_rate, sum(trades) if trades else 0, len(trades)

# ══════════════════════════════════════════════
# 9. AI 生成模組 (Gemini)
# ══════════════════════════════════════════════
def call_ai(api_key: str, prompt: str, use_search: bool = False, json_mode: bool = False) -> str:
    client = genai.Client(api_key=api_key)
    models = [("gemini-2.5-flash","Gemini 2.5 Flash"),("gemini-2.0-flash","Gemini 2.0 Flash")]
    last_err = None
    for mid, mname in models:
        try:
            cfg_args = {"temperature": 0.2}
            if use_search: cfg_args["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
            if json_mode: cfg_args["response_mime_type"] = "application/json"
            
            cfg = genai_types.GenerateContentConfig(**cfg_args)
            resp = client.models.generate_content(model=mid,contents=prompt,config=cfg)
            if json_mode: return resp.text
            return f"> [AI] {mname} | {datetime.now(TW_TZ).strftime('%H:%M:%S')}\n\n{resp.text}"
        except Exception as e:
            last_err=str(e)
            continue
    raise Exception(f"AI 無法使用: {last_err}")

@st.cache_data(ttl=10800, show_spinner=False)
def ai_macro_regime(api_key: str) -> str:
    prompt = """You are an elite Macroeconomist. Analyze the current global macroeconomic regime based on this week's data.
Choose EXACTLY ONE from the following list and output that exact string: [未知, 成長擴張(Risk-On), 通膨衰退(Stagflation), 衰退(Risk-Off), 復甦反彈(Early Cycle), 流動性危機].
You MUST format your output exactly as shown below:
**制度: ** [Exact string from the list above]
**理由: ** [Under 30 words explaining FED policy or inflation in Traditional Chinese.]"""
    return call_ai(api_key, prompt, use_search=True)

@st.cache_data(ttl=10800, show_spinner=False)
def ai_classify_news_tags(news_titles: list, api_key: str) -> dict:
    if not news_titles: return {}
    titles_str = "\n".join([f"{i+1}. {t['title']}" for i, t in enumerate(news_titles)])
    prompt = f"""
    You are an objective financial news classifier for Taiwan stock market.
    Assign EXACTLY ONE specific industry tag to each news title.
    Allowed Tags: ["半導體", "IC設計", "AI伺服器", "航運", "金融", "重電", "營建", "生技", "消費電子", "總經", "其他"]
    News Titles:
    {titles_str}
    
    Output strictly in JSON format where key is the index string (e.g. "1") and value is the Tag.
    """
    try:
        raw = call_ai(api_key, prompt, use_search=False, json_mode=True)
        return json.loads(raw)
    except: return {}

@st.cache_data(ttl=10800, show_spinner=False)
def ai_news_sentiment(news_str: str, sym: str, api_key: str) -> str:
    prompt = f"""You are a financial news summarizer for beginners. Stock: {sym}\nNews:\n{news_str}\n
    [FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. Output in Traditional Chinese (zh-TW).
    ## 📰 AI 新聞情緒解讀
    - **整體氣氛**: (Bullish 偏多 / Bearish 偏空 / Neutral 觀望? Why?)
    - **關鍵大事**: (1 short bullet point summarizing the most important event)"""
    return call_ai(api_key, prompt, use_search=False)

@st.cache_data(ttl=10800, show_spinner=False)
def ai_stock_pk(sym1: str, sym2: str, api_key: str) -> str:
    prompt = f"""You are an investment advisor. Compare stock {sym1} and stock {sym2}. Use real-time search.
[FORMAT REQUIREMENT]: BE EXTREMELY CONCISE. Use short bullet points. Output in Traditional Chinese (zh-TW).
## 🥊 {sym1} vs {sym2} 世紀大對決
- **⚡ 短線爆發力**: (Winner + 1 simple reason based on momentum)
- **💎 長線存股力**: (Winner + 1 simple reason based on fundamentals or yield)
- **💰 裁判最終建議**: (Which one should the beginner pick right now and why? 1 sentence)"""
    return call_ai(api_key, prompt, use_search=True)

@st.cache_data(ttl=10800, show_spinner=False)
def ai_three_agent_debate_cached(base_data: str, api_key: str) -> tuple:
    bull_prompt = f"Construct strongest bullish argument for {base_data}. Traditional Chinese. Format: ## 🔴 為什麼看漲？\n- ..."
    bear_prompt = f"Expose all bearish risks for {base_data}. Traditional Chinese. Format: ## 🟢 為什麼看跌？\n- ..."
    judge_prompt= f"Adjudicate objectively for {base_data}. Traditional Chinese. Format: ## 🟣 裁判最終判定\n- ..."
    return call_ai(api_key, bull_prompt, use_search=True), call_ai(api_key, bear_prompt, use_search=True), call_ai(api_key, judge_prompt, use_search=False)

@st.cache_data(ttl=10800, show_spinner=False)
def ai_portfolio_cio(portfolio_data: str, sector_data: str, api_key: str) -> str:
    prompt = f"You are a strict CIO auditing portfolio:\n{portfolio_data}\nSector: {sector_data}\nTraditional Chinese. Format: ## 🏦 健檢\n- ...\n## ⚔️ 汰弱留強\n- ..."
    return call_ai(api_key, prompt, use_search=True)

@st.cache_data(ttl=10800, show_spinner=False)
def ai_bias_warning(bias_data: dict, trades_summary: str, api_key: str) -> str:
    prompt = f"Diagnose biases. Win rate: {bias_data.get('win_rate')}%, Disposition: {bias_data.get('disposition_effect')}. Trades: {trades_summary}. Traditional Chinese. Format: ## 🧠 診斷\n- ..."
    return call_ai(api_key, prompt, use_search=False)

# ══════════════════════════════════════════════
# 10. 圖表建構 (台灣色系: 紅漲綠跌)
# ══════════════════════════════════════════════
DARK, TW_UP, TW_DOWN = "plotly_dark", "#ff3333", "#22cc44"

def build_main_chart(hist, ind, entry, sym, mc_data=None, buy_markers=None):
    idx = hist.index
    rows, heights, titles = 4, [0.50, 0.18, 0.17, 0.15], ["K線+均線+布林","成交量","RSI+StochK","MACD"]
    if mc_data: rows, heights, titles = 5, [0.42, 0.18, 0.15, 0.13, 0.12], titles + ["蒙地卡羅模擬"]
        
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
        fd, p = mc_data["dates"], mc_data["pcts"]
        fig.add_trace(go.Scatter(x=fd,y=p["p97"],line=dict(color="rgba(255,200,50,0.3)",width=1),showlegend=False),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p02"],line=dict(color="rgba(255,200,50,0.3)",width=1),showlegend=False,fill="tonexty",fillcolor="rgba(255,200,50,0.08)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p84"],line=dict(color="rgba(100,180,255,0.5)",width=1),showlegend=False),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p16"],line=dict(color="rgba(100,180,255,0.5)",width=1),showlegend=False,fill="tonexty",fillcolor="rgba(100,180,255,0.12)"),row=mc_row,col=1)
        fig.add_trace(go.Scatter(x=fd,y=p["p50"],line=dict(color="#FFD700",width=2),name="中位數"),row=mc_row,col=1)

    fig.update_layout(template=DARK,title=f"{sym} 技術分析(🔴漲 🟢跌)",height=900 if mc_data else 780,xaxis_rangeslider_visible=False,legend=dict(orientation="h",y=1.02,font_size=11),margin=dict(l=50,r=50,t=80,b=30))
    return fig

def build_heatmap_chart(df: pd.DataFrame, market: str):
    if df.empty: return None
    fig = px.treemap(df,path=["板塊","名稱"],values="市值",color="漲跌%",color_continuous_scale=[(0.0,TW_DOWN),(0.5,"#333333"),(1.0,TW_UP)],color_continuous_midpoint=0,custom_data=["代號","漲跌%"],title=f"{'台股' if '台股' in market else '美股'} 板塊熱力圖",template=DARK)
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{customdata[1]:.2f}%",textfont_size=13)
    fig.update_layout(height=550,margin=dict(l=10,r=10,t=60,b=10),coloraxis_colorbar=dict(title="漲跌%"))
    return fig

def build_portfolio_sunburst(portfolio: dict, sector_map: dict, cash_balance: float) -> go.Figure:
    rows = []
    for sym,data in portfolio.items(): 
        if isinstance(data, list):
             for entry in data: rows.append({"板塊":sector_map.get(sym,"其他"),"代號":sym,"市值":entry["cost"]*entry["shares"]})
        else: rows.append({"板塊":sector_map.get(sym,"其他"),"代號":sym,"市值":data["cost"]*data["shares"]})
    rows.append({"板塊":"現金", "代號":"閒置現金", "市值":cash_balance})
    if not rows: return None
    fig = px.sunburst(pd.DataFrame(rows),path=["板塊","代號"],values="市值",title="資產配置旭日圖(含現金)",template=DARK,color_discrete_sequence=px.colors.qualitative.Set3)
    fig.update_layout(height=450,margin=dict(l=10,r=10,t=60,b=10))
    return fig

def build_dca_chart(df_dca: pd.DataFrame, sym: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["累積投入"],fill="tozeroy",name="累積投入本金",line=dict(color="#42A5F5",width=2),fillcolor="rgba(66,165,245,0.15)"))
    fig.add_trace(go.Scatter(x=df_dca.index,y=df_dca["資產現值"],fill="tozeroy",name="資產現值",line=dict(color=TW_UP,width=2),fillcolor="rgba(255,51,51,0.15)"))
    fig.update_layout(template=DARK,title=f"{sym} 定期定額回測",yaxis_title="金額(元)",height=420,legend=dict(orientation="h",y=1.02),margin=dict(l=50,r=30,t=60,b=30))
    return fig

# ══════════════════════════════════════════════
# 11. 側邊欄 
# ══════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定 (個人自用版)")
    st.caption("🟢 雲端已連線" if HAS_DB else "🟡 本機模式")

    st.divider()
    if not st.session_state.logged_in and cookie_controller is not None:
        saved_u = cookie_controller.get("tw_stock_u")
        saved_p = cookie_controller.get("tw_stock_p")
        if saved_u and saved_p:
            ok, uid, enc = db_verify_user(saved_u, saved_p)
            if ok:
                st.session_state.update(user_id=uid, username=saved_u, _pin=saved_p, logged_in=True)
                st.session_state.watchlist = db_load_wl(uid)
                st.session_state.portfolio = db_load_port(uid)
                st.session_state.trade_history = db_load_trades(uid)
                if enc:
                    dec = decrypt_key(enc, saved_p)
                    if dec: st.session_state.api_key = dec

    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號", key="sb_u")
            upin  = st.text_input("密碼", type="password", key="sb_p")
            if st.button("🔑 登入 / ✨ 建立", use_container_width=True) and uname and upin:
                ok, uid, enc = db_verify_user(uname.strip(), upin.strip())
                if not ok: ok, uid, msg = db_create_user(uname.strip(), upin.strip())
                if ok:
                    st.session_state.update(user_id=uid, username=uname.strip(), _pin=upin.strip(), logged_in=True)
                    st.session_state.watchlist = db_load_wl(uid)
                    st.session_state.portfolio = db_load_port(uid)
                    st.session_state.trade_history = db_load_trades(uid)
                    if cookie_controller is not None:
                        cookie_controller.set("tw_stock_u", uname.strip(), max_age=30*86400)
                        cookie_controller.set("tw_stock_p", upin.strip(), max_age=30*86400)
                    st.rerun()
    else:
        st.success(f"👤 {st.session_state.username}")
        if st.button("🚪 登出", use_container_width=True):
            st.session_state.logged_in = False
            if cookie_controller is not None: 
                cookie_controller.remove("tw_stock_u")
                cookie_controller.remove("tw_stock_p")
            st.rerun()

    st.divider()
    api_key_in = st.text_input("🔑 Gemini API 金鑰", type="password", value=st.session_state.api_key)
    if api_key_in and api_key_in != st.session_state.api_key:
        st.session_state.api_key = api_key_in.strip()
        if st.session_state.logged_in and HAS_DB: db_save_enc_key(st.session_state.username, st.session_state._pin, api_key_in)
    api_key = st.session_state.api_key

    st.divider()
    market = st.radio("市場",["🇹🇼 台股","🇺🇸 美股"])
    period = st.selectbox("分析區間",["3mo","6mo","1y","2y"],index=1)

    st.divider()
    st.header("🌍 宏觀制度設定")
    if api_key and st.session_state.macro_regime == MACRO_REGIMES[0] and not st.session_state.macro_auto_tried:
        st.session_state.macro_auto_tried = True
        with st.spinner("自動偵測宏觀制度中..."):
            try:
                regime_rpt = ai_macro_regime(api_key)
                for r in MACRO_REGIMES[1:]:
                    if r in regime_rpt: st.session_state.macro_regime = r; break
            except: pass
    macro_regime = st.selectbox("當前宏觀制度", MACRO_REGIMES, index=MACRO_REGIMES.index(st.session_state.macro_regime))
    st.session_state.macro_regime = macro_regime

    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號",placeholder="如2330")
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
            st.session_state.watchlist.pop(i)
            st.rerun()

# ══════════════════════════════════════════════
# 12. 主頁面 (戰情室)
# ══════════════════════════════════════════════
st.title("📈 股市小白分析系統 Pro V7.4")
st.caption("富果 Fugle 即時串接 × FinMind 上櫃備援 × 高級動態排行榜")

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
            st.session_state.quick_sym=rs.replace(".TW","").replace(".TWO","")
            st.session_state.auto_analyze=True
            st.rerun()

st.divider()

TABS = st.tabs(["📊 個股戰情室", "🏆 AI 排行榜", "🥊 雙股 PK", "💼 我的資產庫", "📊 選股+回測", "🗺️ 市場總覽", "🧠 交易心理診斷"])

# ==========================================
# 分頁 1: 個股戰情室
# ==========================================
with TABS[0]:
    ic1,ic2 = st.columns([3,1])
    with ic1: ticker_in = st.text_input("輸入股票代號",value=st.session_state.quick_sym or "")
    with ic2: 
        st.write(""); st.write(""); go_btn = st.button("🔍 開始分析",use_container_width=True,type="primary")

    if go_btn and ticker_in.strip(): st.session_state.current_sym = ticker_in.strip()
    elif st.session_state.auto_analyze and st.session_state.quick_sym: 
        st.session_state.current_sym = st.session_state.quick_sym
        st.session_state.auto_analyze = False

    if st.session_state.get("current_sym"):
        sym = get_sym(st.session_state.current_sym, market)
        add_recent(sym)

        with st.spinner(f"抓取 {sym} 數據..."): 
            hist, info, err = fetch_data(sym, period)
            
        if err or hist is None: 
            st.error(f"❌ {err}")
        else:
            ind   = calc_indicators(hist)
            entry = calc_entry(ind, hist)
            score = calc_score(ind, info)
            co    = info.get("longName") or sym

            st.subheader(f"📌 {co}({sym})")
            st.caption(f"資料來源: `{info.get('source', '未知')}` | 更新時間: {info.get('fetch_time', '未知')}")
            
            if api_key:
                with st.expander("📰 最新市場新聞與 AI 深度解讀", expanded=False):
                    news_data = fetch_news(sym)
                    if not news_data:
                        st.info("目前沒有相關新聞。")
                    else:
                        if st.button("🤖 AI 深度解讀新聞 (情緒 + 產業分類)"):
                            with st.spinner("AI 分析中..."):
                                news_str = "\n".join([f"- {n['title']}" for n in news_data])
                                tags = ai_classify_news_tags(news_data, api_key)
                                
                                for i, n in enumerate(news_data):
                                    tag = tags.get(str(i+1), "其他")
                                    st.markdown(f"• <span class='tag-badge'>{tag}</span> {n['title']}", unsafe_allow_html=True)
                                
                                st.divider()
                                rpt = ai_news_sentiment(news_str, sym, api_key)
                                st.markdown(f"<div style='background:#1e1e2e;padding:15px;border-left:4px solid #3b82f6;'>{rpt}</div>", unsafe_allow_html=True)
                        else:
                            for n in news_data: st.write(f"• {n['title']}")

            score_col, kpi_col = st.columns([1,2])
            with score_col:
                st.markdown(f'<div class="score-card"><div style="color:#64748b;font-size:11px">健康評分</div><div class="big-score" style="color:{score["gc"]}">{score["total"]}</div><div style="color:#e2e8f0;font-size:13px">{score["grade"]}</div></div>',unsafe_allow_html=True)
            with kpi_col:
                st.markdown(f'<div class="status-card"><h3 style="margin:0;color:#e2e8f0">{ind["sc"]} {ind["status"]}</h3><p style="margin:5px 0 0;color:#94a3b8;font-size:13px">{ind["status_desc"]}</p></div>',unsafe_allow_html=True)
                r1,r2,r3 = st.columns(3)
                r1.metric("💰 現價", ind["price"])
                r2.metric("今日", f"{ind['change_pct']}%", delta=str(ind["change_pct"]), delta_color="inverse")
                r3.metric("月線位置", ind["ma20"])

            st.divider()
            c_dt, c_st, c_lt = st.columns(3)
            with c_dt:
                st.markdown(f"""<div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #f59e0b;height:100%;">
                    <h4 style="margin-top:0;color:#f59e0b;">⚡ 當沖 (看今天)</h4><div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['dt_status']}</div>
                    <div style="font-size:13px;color:#94a3b8;">買點: <span style="color:#66cc66">{entry['agg_buy']}</span> | 快跑: <span style="color:#ff6666">{entry['sl_tight']}</span></div></div>""", unsafe_allow_html=True)
            with c_st:
                st.markdown(f"""<div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #3b82f6;height:100%;">
                    <h4 style="margin-top:0;color:#3b82f6;">📈 波段 (抱幾週)</h4><div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['st_status']}</div>
                    <div style="font-size:13px;color:#94a3b8;">買點: <span style="color:#66cc66">{entry['mod_buy']}</span> | 防守: <span style="color:#ff6666">{entry['sl_normal']}</span></div></div>""", unsafe_allow_html=True)
            with c_lt:
                st.markdown(f"""<div style="background:#1e1e2e;padding:16px;border-radius:12px;border:1px solid #3a3a5e;border-top:4px solid #8b5cf6;height:100%;">
                    <h4 style="margin-top:0;color:#8b5cf6;">💎 長線 (存很久)</h4><div style="font-size:15px;color:#e2e8f0;font-weight:bold;margin-bottom:12px;">{ind['lt_status']}</div>
                    <div style="font-size:13px;color:#94a3b8;">買點: <span style="color:#66cc66">{entry['con_buy']}</span> | 底線: <span style="color:#ff6666">{entry['sl_wide']}</span></div></div>""", unsafe_allow_html=True)

            st.divider()
            show_mc = st.checkbox("🎲 開啟蒙地卡羅30日模擬")
            mc_data = monte_carlo_simulation(hist) if show_mc else None
            
            buy_markers = []
            if sym in st.session_state.portfolio:
                entries = st.session_state.portfolio[sym]
                if isinstance(entries, dict): entries = [entries]
                for pd2 in entries:
                    if isinstance(pd2, dict) and pd2.get("buy_date"):
                        try:
                            bdate = pd.to_datetime(pd2["buy_date"])
                            if bdate.tz: bdate = bdate.tz_localize(None)
                            buy_markers.append({"date":bdate,"price":pd2.get("cost")})
                        except: pass

            st.plotly_chart(build_main_chart(hist,ind,entry,sym,mc_data,buy_markers if buy_markers else None),use_container_width=True)

            st.divider()
            st.markdown("### [AI] 多週期三方辯論分析")
            if not api_key: st.warning("⚠️ 請先設定 API 金鑰。")
            elif st.button("⚔️ 啟動 AI 辯論分析", type="primary"):
                with st.spinner("AI 分析中..."):
                    base_data_str = f"Symbol: {co} ({sym}) | Price: {ind['price']} | 1D: {ind['change_pct']}% | Score: {score['total']}\nStatus: {ind['status']}\nRSI={ind['rsi']} MACD={ind['macd_hist']} Vol={ind.get('vol_desc', 'N/A')}"
                    bull_rpt, bear_rpt, judge_rpt = ai_three_agent_debate_cached(base_data_str, api_key)
                    debate_tab1, debate_tab2, debate_tab3 = st.tabs(["🔴 多頭", "🟢 空頭", "🟣 裁判"])
                    with debate_tab1: st.markdown(bull_rpt)
                    with debate_tab2: st.markdown(bear_rpt)
                    with debate_tab3: st.markdown(judge_rpt)

# ==========================================
# 分頁 2: AI 評分排行榜 (徹底修復渲染亂碼)
# ==========================================
with TABS[1]:
    st.markdown("""
    <style>
    .lb-card { background-color: #1e1e2e; border: 1px solid #3a3a5e; border-radius: 12px; padding: 20px; margin-bottom: 16px; position: relative; overflow: hidden; }
    .lb-card::before { content: ''; position: absolute; bottom: 0; left: 0; width: 100%; height: 4px; background: linear-gradient(90deg, #ff4444, #ff0000); }
    .lb-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px; }
    .lb-title { font-size: 20px; font-weight: bold; color: #ffffff; display: flex; align-items: center; gap: 10px; margin:0;}
    .lb-status { font-size: 13px; color: #ff4444; background: rgba(255,68,68,0.1); padding: 4px 8px; border-radius: 4px; }
    .lb-score-container { text-align: right; }
    .lb-score { font-size: 42px; font-weight: 900; color: #ff4444; line-height: 1; }
    .lb-score-sub { font-size: 12px; color: #64748b; }
    .lb-bars { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .bar-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 13px; color: #94a3b8; }
    .bar-bg { width: 60%; height: 6px; background: #3a3a5e; border-radius: 3px; overflow: hidden; margin: 0 10px; }
    .bar-fill { height: 100%; background: #ff4444; border-radius: 3px; }
    .lb-reason { margin-top: 15px; padding-top: 15px; border-top: 1px dashed #3a3a5e; font-size: 13px; color: #a1a1aa; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("### 🏆 AI 綜合評分排行榜 (Top 10)")
    st.caption("🚀 整合技術面、量能與動能之全自動分類排行，為新手過濾市場雜訊。")
    
    lb_cat = st.radio("選擇分類", ["個股", "被動式ETF", "主動式ETF"], horizontal=True)
    
    if os.path.exists("leaderboard.json"):
        try:
            with open("leaderboard.json", "r", encoding="utf-8") as f:
                full_lb_data = json.load(f)
        except Exception:
            full_lb_data = {}
            
        if isinstance(full_lb_data, dict):
            cat_data = full_lb_data.get(lb_cat, [])
        else:
            cat_data = []
            st.warning("⚠️ 偵測到舊版排行榜格式。請在終端機執行 `python background_worker.py` 來更新資料庫。")
        
        if not cat_data and isinstance(full_lb_data, dict):
            st.info(f"尚無 {lb_cat} 的排行資料，請確認背景程式正在監控此分類。")
        else:
            for idx, item in enumerate(cat_data):
                medal = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f'<span style="color:#64748b;font-size:18px;">{idx+1}</span>'
                
                # 警告：此處字串絕對不可有任何「行首空白(Indentation)」，否則 Streamlit 會將其誤判為純文字代碼區塊！
                html_content = f"""<div class="lb-card">
<div class="lb-header">
<div class="lb-title">
{medal} {item.get('sym','')} {item.get('name','')} 
<span class="lb-status">📈 {item.get('status','')}</span>
</div>
<div class="lb-score-container">
<div class="lb-score">{item.get('score',0)}</div>
<div class="lb-score-sub">/ 100</div>
</div>
</div>
<div class="lb-bars">
<div>
<div class="bar-row"><span>當沖爆發力</span> <div class="bar-bg"><div class="bar-fill" style="width: {item.get('dt_score',0)}%;"></div></div> <span>{item.get('dt_score',0)}</span></div>
<div class="bar-row"><span>短線波段力</span> <div class="bar-bg"><div class="bar-fill" style="width: {item.get('st_score',0)}%;"></div></div> <span>{item.get('st_score',0)}</span></div>
</div>
<div>
<div class="bar-row"><span>長線存股力</span> <div class="bar-bg"><div class="bar-fill" style="width: {item.get('lt_score',0)}%;"></div></div> <span>{item.get('lt_score',0)}</span></div>
</div>
</div>
<div class="lb-reason">
💡 <b>入榜主要原因：</b> {item.get('reason','')} <span style="float:right;font-size:11px;color:#64748b;">更新時間：{item.get('update_time','')}</span>
</div>
</div>"""
                st.markdown(html_content, unsafe_allow_html=True)
    else:
        st.warning("⚠️ 尚未建立排行榜資料庫 (leaderboard.json)！請先在終端機執行 `python background_worker.py`。")

# ==========================================
# 分頁 3: 雙股 PK
# ==========================================
with TABS[2]:
    st.markdown("### 🥊 雙股 PK 擂台")
    pk_col1, pk_col2 = st.columns(2)
    with pk_col1: pk_sym1 = st.text_input("選手 A", placeholder="例如 2330")
    with pk_col2: pk_sym2 = st.text_input("選手 B", placeholder="例如 2454")
    if st.button("⚔️ AI 開打！", type="primary") and pk_sym1 and pk_sym2 and api_key:
        with st.spinner("🥊 PK 中..."):
            st.markdown(ai_stock_pk(get_sym(pk_sym1, market), get_sym(pk_sym2, market), api_key))

# ==========================================
# 分頁 4: 我的資產庫
# ==========================================
with TABS[3]:
    st.markdown("### 💵 帳戶現金管理")
    c_bal = st.number_input("目前閒置現金 (元)", value=float(st.session_state.cash_balance), step=10000.0)
    st.session_state.cash_balance = c_bal
    
    asset_tab1,asset_tab2 = st.tabs(["💼 持股庫存", "📋 已平倉交易"])

    with asset_tab1:
        st.markdown("#### ➕ 新增持股記錄")
        p1,p2,p3,p4,p5 = st.columns(5)
        with p1: ps_ = st.text_input("代號",key="pf_s_")
        with p2: pc_ = st.number_input("買入成本",0.0,step=0.5,key="pf_c_")
        with p3: pn_ = st.number_input("持有股數",0.0,step=100.0,key="pf_n_")
        with p4: pd_ = st.date_input("買入日期",key="pf_d_")
        with p5: 
            st.write(""); st.write(""); p_btn = st.button("💾 寫入資產庫",use_container_width=True,type="primary")

        if p_btn and ps_.strip() and pc_>0 and pn_>0:
            ps_sym = get_sym(ps_.strip(),market)
            if ps_sym in st.session_state.portfolio:
                entries = st.session_state.portfolio[ps_sym]
                if isinstance(entries, dict): entries = [entries]
                st.session_state.portfolio[ps_sym] = entries + [{"cost": pc_, "shares": pn_, "note": "", "buy_date": str(pd_)}]
            else: 
                st.session_state.portfolio[ps_sym] = [{"cost": pc_, "shares": pn_, "note": "", "buy_date": str(pd_)}]
                
            db_save_port(st.session_state.user_id, ps_sym, pc_, pn_, "", str(pd_))
            st.success("✅ 已寫入")
            st.rerun()

        if st.session_state.portfolio:
            st.divider()
            st.markdown("### 📋 庫存總覽")
            sector_map, pr_rows, tc_all, cv_all = {}, [], 0, 0
            
            for sym, entries in st.session_state.portfolio.items():
                if isinstance(entries, dict): entries = [entries]
                total_s = sum(e.get("shares", 0) for e in entries)
                total_c = sum(e.get("cost", 0) * e.get("shares", 0) for e in entries)
                avg_c = round(total_c / total_s, 2) if total_s > 0 else 0
                try:
                    hh2, info2, err2 = fetch_data(sym, "1mo")
                    if hh2 is not None and not hh2.empty:
                        cp2 = round(float(hh2["Close"].dropna().iloc[-1]), 2)
                        pnl_pct = round((cp2 - avg_c) / max(avg_c, 0.01) * 100, 2)
                        v2, c2 = round(cp2 * total_s, 0), round(total_c, 0)
                        sec = info2.get("sector", "其他") if info2 else "其他"
                        sector_map[sym] = sec
                        pr_rows.append({"代號": sym, "均價": avg_c, "現價": cp2, "損益%": f"{pnl_pct:+.2f}%", "總損益": f"{v2-c2:+,.0f}", "總股數": total_s, "板塊": sec})
                        tc_all += c2
                        cv_all += v2
                except: pass
            
            if pr_rows:
                st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)
                tp, tpct = cv_all - tc_all, round((cv_all - tc_all) / max(tc_all, 1) * 100, 2) if tc_all > 0 else 0
                
                sb_fig = build_portfolio_sunburst(st.session_state.portfolio, sector_map, st.session_state.cash_balance)
                s1, s2, s3 = st.columns(3)
                s1.metric("📊 庫存總損益", f"{tp:+,.0f}元", delta=f"{tpct:+.2f}%", delta_color="inverse")
                s2.metric("💎 庫存總現值", f"{cv_all:,.0f}元")
                s3.metric("💵 總資產 (含現金)", f"{(cv_all + st.session_state.cash_balance):,.0f}元")
                if sb_fig: st.plotly_chart(sb_fig, use_container_width=True)
                
                if api_key:
                    if st.button("🏦 AI 投資長健檢你的持股配置", type="primary"):
                        port_str = "\n".join([f"- {r['代號']}: 成本{r['均價']} 現價{r['現價']} 損益{r['損益%']}" for r in pr_rows])
                        with st.spinner("AI 投資長分析中..."):
                            cio_rpt = ai_portfolio_cio(port_str, str(sector_map), api_key)
                            st.markdown(cio_rpt)

            st.divider()
            st.markdown("#### 🗑️ 刪除 / 平倉 記錄")
            del_c1, del_c2 = st.columns([2, 2])
            with del_c1: 
                target_sym = st.selectbox("1. 選擇股票", options=list(st.session_state.portfolio.keys()))
                if target_sym:
                    entries = st.session_state.portfolio[target_sym]
                    if isinstance(entries, dict): entries = [entries] 
                    entry_options = {f"價 {e.get('cost','?')} | {e.get('shares','?')}股 | 日期 {e.get('buy_date','')}": e for e in entries}
                    selected_label = st.selectbox("2. 選擇分筆記錄", options=list(entry_options.keys()))
                    to_delete = entry_options[selected_label]
            with del_c2:
                if target_sym:
                    action = st.radio("3. 選擇動作", ["單純刪除", "平倉並轉入交易記錄"])
                    if "平倉" in action:
                        exit_price = st.number_input("輸入賣出價格", value=float(to_delete.get('cost',0)))
                        if st.button("✅ 確認平倉", type="primary"):
                            ts_sym, t_ep, t_xp, t_sh = target_sym, float(to_delete.get('cost',0)), exit_price, float(to_delete.get('shares',0))
                            t_ed, t_xd = to_delete.get('buy_date', str(date.today())), str(date.today())
                            pnl_a, pnl_p = round((t_xp-t_ep)*t_sh,2), round((t_xp-t_ep)/max(t_ep,0.01)*100,2)
                            db_add_trade(st.session_state.user_id, ts_sym,"LONG",t_ep,t_xp,t_sh,t_ed,t_xd,"一鍵平倉")
                            st.session_state.trade_history.append({"symbol":ts_sym,"direction":"LONG","entry_price":t_ep,"exit_price":t_xp,"shares":t_sh,"entry_date":t_ed,"exit_date":t_xd,"pnl_amount":pnl_a,"pnl_pct":pnl_p,"note":"一鍵平倉"})
                            st.session_state.cash_balance += (t_xp * t_sh)
                            if st.session_state.logged_in and "db_id" in to_delete: db_del_port_by_id(st.session_state.user_id, to_delete["db_id"])
                            st.session_state.portfolio[target_sym].remove(to_delete)
                            if not st.session_state.portfolio[target_sym]: del st.session_state.portfolio[target_sym]
                            st.success("✅ 已平倉！現金已加回！")
                            st.rerun()
                    else:
                        if st.button("❌ 確認刪除"):
                            if st.session_state.logged_in and "db_id" in to_delete: db_del_port_by_id(st.session_state.user_id, to_delete["db_id"])
                            st.session_state.portfolio[target_sym].remove(to_delete)
                            if not st.session_state.portfolio[target_sym]: del st.session_state.portfolio[target_sym]
                            st.rerun()

    with asset_tab2:
        st.markdown("### 📋 已平倉交易")
        trades = st.session_state.trade_history
        if trades:
            tr_df=pd.DataFrame([{"代號":t.get("symbol",""),"買入價":t.get("entry_price",0),"賣出價":t.get("exit_price",0),"損益":f"{(t.get('pnl_amount') or 0):+,.0f}","損益%":f"{(t.get('pnl_pct') or 0):+.2f}%"} for t in trades])
            st.dataframe(tr_df,use_container_width=True,hide_index=True)
            win_t=sum(1 for t in trades if (t.get("pnl_pct") or 0)>0)
            st.metric("📊 累積損益",f"{sum((t.get('pnl_amount') or 0) for t in trades):+,.0f}元",delta=f"勝率{round(win_t/max(len(trades),1)*100,1)}%",delta_color="inverse")

# ==========================================
# 分頁 5: 選股+回測
# ==========================================
with TABS[4]:
    scr_tab, dca_tab, bt_tab = st.tabs(["🔎 技術選股","⏳ 定期定額回測", "⚙️ MA交叉回測"])
    
    with scr_tab:
        col1,col2 = st.columns(2)
        with col1: 
            scr_rsi_lt = st.number_input("RSI <",0.0,100.0,35.0,step=5.0)
            scr_macd = st.checkbox("MACD > 0")
        with col2: 
            scr_ma20 = st.checkbox("站上月線")
            scr_vol = st.checkbox("放量>1.5")
            
        if st.button("🔍 掃描熱門股",type="primary"):
            all_syms = [get_sym(s,market) for v in (TW_HOT if "台股" in market else US_HOT).values() for s,_ in v]
            cond = {}
            if scr_rsi_lt>0: cond["rsi_lt"] = scr_rsi_lt
            if scr_macd: cond["macd_cross_up"] = True
            if scr_ma20: cond["above_ma20"] = True
            if scr_vol: cond["vol_spike"] = True
            with st.spinner("掃描中..."): results = run_screener(all_syms,cond)
            if results: st.dataframe(pd.DataFrame(results),use_container_width=True,hide_index=True)
            else: st.info("無結果")

    with dca_tab:
        d1,d2,d3,d4=st.columns(4)
        with d1: dca_sym=st.text_input("代號",placeholder="如0050",key="dca_s")
        with d2: dca_amt=st.number_input("月投入",1000.0,1000000.0,10000.0,step=1000.0)
        with d3: dca_yr =st.selectbox("年限",[3,5,10,15,20],index=1)
        with d4: 
            st.write(""); st.write(""); dca_btn=st.button("⏳ 回測",type="primary")
            
        if dca_btn and dca_sym.strip():
            with st.spinner("模擬中..."): df_dca,stats,err=run_dca(get_sym(dca_sym.strip(),market),dca_amt,dca_yr,market)
            if df_dca is None: st.error(err)
            else:
                cols = st.columns(4)
                for idx, (k,v) in enumerate(stats.items()): cols[idx % 4].metric(k,v)
                st.plotly_chart(build_dca_chart(df_dca,dca_sym),use_container_width=True)

    with bt_tab:
        bt_s1, bt_s2, bt_s3 = st.columns(3)
        with bt_s1: bt_sym = st.text_input("測試標的", placeholder="如2330", key="bt_sym_input")
        with bt_s2: bt_sw = st.number_input("短均線", value=5, min_value=2)
        with bt_s3: bt_lw = st.number_input("長均線", value=20, min_value=10)
        if st.button("🚀 開始回測歷史3年", type="primary") and bt_sym.strip():
            sym_t = get_sym(bt_sym.strip(), market)
            with st.spinner("計算中..."):
                h_bt, _, err = fetch_data(sym_t, "3y")
                if h_bt is not None:
                    wr, tr, tc = backtest_ma_crossover(h_bt, bt_sw, bt_lw)
                    st.success(f"✅ {sym_t} 過去 3 年回測完成")
                    btc1, btc2, btc3 = st.columns(3)
                    btc1.metric("總交易次數", f"{tc} 次")
                    btc2.metric("策略勝率", f"{wr*100:.1f}%")
                    btc3.metric("總報酬率", f"{tr:+.1f}%")

# ==========================================
# 分頁 6: 市場總覽
# ==========================================
with TABS[5]:
    if st.button("🔄 載入板塊熱力圖",type="primary"):
        with st.spinner("抓取板塊數據..."): df_hm = fetch_heatmap_data(market)
        if not df_hm.empty: st.plotly_chart(build_heatmap_chart(df_hm,market),use_container_width=True)

# ==========================================
# 分頁 7: 交易心理診斷
# ==========================================
with TABS[6]:
    trades = st.session_state.trade_history
    if len(trades)<3: st.warning("⚠️ 需要至少3筆已平倉記錄才能進行行為分析。")
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
            
            if bias["disposition_effect"]: st.error("🚨 偵測到處置效應 (持有虧損股時間顯著長於獲利股)！請嚴格執行停損。")
            
            if api_key and st.button("🧠 AI 幫你抓投資壞習慣",type="primary"):
                with st.spinner("AI 快速總結中..."):
                    bias_rpt = ai_bias_warning(bias, "\n".join([f"- {t.get('symbol','')}: 損益{t.get('pnl_pct',0):+.1f}%" for t in trades[:10]]), api_key)
                    st.markdown(bias_rpt)

st.divider()
st.caption("📈 股市小白分析系統 Pro V7.4 | 完全自用無限制版")