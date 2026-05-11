# ╔══════════════════════════════════════════════════════════════╗
# ║         股市小白分析系統 Pro  ─  終極重構版                      ║
# ╚══════════════════════════════════════════════════════════════╝
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from google import genai
from google.genai import types as genai_types
import time, hashlib, base64, os
from datetime import datetime, date
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ══════════════════════════════════════════════════════
# 1. 頁面設定
# ══════════════════════════════════════════════════════
st.set_page_config(
    page_title="股市小白分析系統 Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════
# 2. Supabase（不動連線邏輯）
# ══════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════
# 3. CSS（深色統一主題）
# ══════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── 響應式 ── */
@media(max-width:768px){
  h1{font-size:1.1rem!important}
  h3{font-size:0.9rem!important}
  .stButton>button{font-size:11px!important;padding:4px 6px!important}
}
/* ── 卡片 ── */
.score-card{background:linear-gradient(135deg,#1e1e2e,#2a2a3e);
  border-radius:16px;padding:20px;text-align:center;
  border:1px solid #3a3a5e;margin-bottom:12px}
.big-score{font-size:3.2rem;font-weight:900;line-height:1.1}
.status-card{background:#1e1e2e;border-radius:12px;padding:16px;
  margin:8px 0;border-left:5px solid #7c3aed}
.entry-card{background:linear-gradient(135deg,#0d2b0d,#1a3a1a);
  border-radius:12px;padding:14px;margin:6px 0;border:1px solid #2a5a2a}
.stop-card{background:#2a0d0d;border-radius:12px;padding:14px;
  margin:6px 0;border:1px solid #5a1a1a}
.target-card{background:#0d1a2b;border-radius:12px;padding:14px;
  margin:6px 0;border:1px solid #1a3a5a}
.predict-card{background:linear-gradient(135deg,#1a0d2b,#2b1a3a);
  border-radius:14px;padding:18px;margin:10px 0;border:2px solid #6b2fba}
.kpi-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.kpi-box{background:#1e1e2e;border-radius:10px;padding:10px 16px;
  flex:1;min-width:100px;text-align:center;border:1px solid #2a2a3e}
.kpi-label{color:#64748b;font-size:11px}
.kpi-value{color:#e2e8f0;font-size:1.1rem;font-weight:700}
.confirm-warn{background:#3a1a00;border-radius:8px;padding:10px;
  border:1px solid #aa4400;margin:6px 0}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 4. Session State
# ══════════════════════════════════════════════════════
_DEFAULTS = dict(
    user_id=None, username=None, logged_in=False,
    api_key="", watchlist=[], alerts={}, portfolio={},
    recent_searches=[], quick_sym="", auto_analyze=False,
    confirm_clear_watch=False, confirm_clear_port=False,
)
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════
# 5. 加密工具（Fernet + PBKDF2）
# ══════════════════════════════════════════════════════
_SALT = b"stock_analyzer_salt_v1"  # 固定 salt（生產環境建議用 secrets 存隨機 salt）

def _derive_key(pin: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=390000)
    return base64.urlsafe_b64encode(kdf.derive(pin.encode()))

def encrypt_api_key(api_key: str, pin: str) -> str:
    f = Fernet(_derive_key(pin))
    return f.encrypt(api_key.encode()).decode()

def decrypt_api_key(token: str, pin: str) -> str:
    try:
        f = Fernet(_derive_key(pin))
        return f.decrypt(token.encode()).decode()
    except Exception:
        return ""

# ══════════════════════════════════════════════════════
# 6. 資料庫函數
# ══════════════════════════════════════════════════════
def make_uid(username: str, pin: str) -> str:
    return hashlib.sha256(f"{username.lower().strip()}:{pin}".encode()).hexdigest()[:20]

def db_verify_user(username: str, pin: str):
    """回傳 (ok, uid, encrypted_api_key_or_None)"""
    if not HAS_DB:
        return True, make_uid(username, pin), None
    try:
        uid = make_uid(username, pin)
        r = _supabase.table("users").select("id,encrypted_api_key") \
            .eq("username", username.lower().strip()) \
            .eq("password_hash", uid).execute()
        if r.data:
            return True, uid, r.data[0].get("encrypted_api_key")
        return False, None, None
    except Exception:
        return False, None, None

def db_create_user(username: str, pin: str):
    """回傳 (ok, uid, message)"""
    if not HAS_DB:
        return True, make_uid(username, pin), "本機模式（資料不會永久保存）"
    try:
        uid = make_uid(username, pin)
        ex = _supabase.table("users").select("id") \
            .eq("username", username.lower().strip()).execute()
        if ex.data:
            return False, None, "帳號已存在，請直接登入"
        _supabase.table("users").insert({
            "username": username.lower().strip(),
            "password_hash": uid,
        }).execute()
        return True, uid, "帳號建立成功！"
    except Exception as e:
        return False, None, f"建立失敗：{str(e)[:60]}"

def db_save_encrypted_key(username: str, pin: str, api_key: str):
    if not HAS_DB or not api_key: return
    try:
        token = encrypt_api_key(api_key, pin)
        _supabase.table("users").update({"encrypted_api_key": token}) \
            .eq("username", username.lower().strip()).execute()
    except Exception: pass

def db_load_watchlist(uid: str) -> list:
    if not HAS_DB: return []
    try:
        r = _supabase.table("watchlists").select("symbol").eq("user_id", uid).execute()
        return [x["symbol"] for x in r.data]
    except: return []

def db_add_watch(uid: str, sym: str):
    if not HAS_DB: return
    try:
        ex = _supabase.table("watchlists").select("id") \
            .eq("user_id", uid).eq("symbol", sym).execute()
        if not ex.data:
            _supabase.table("watchlists").insert({"user_id": uid, "symbol": sym}).execute()
    except: pass

def db_del_watch(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("watchlists").delete() \
        .eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

def db_load_alerts(uid: str) -> dict:
    if not HAS_DB: return {}
    try:
        r = _supabase.table("alerts").select("*").eq("user_id", uid).execute()
        return {x["symbol"]: {"above": x.get("above_price"), "below": x.get("below_price")}
                for x in r.data}
    except: return {}

def db_save_alert(uid: str, sym: str, above, below):
    if not HAS_DB: return
    try:
        ex = _supabase.table("alerts").select("id") \
            .eq("user_id", uid).eq("symbol", sym).execute()
        d = {"user_id": uid, "symbol": sym,
             "above_price": above or None, "below_price": below or None}
        if ex.data:
            _supabase.table("alerts").update(d) \
                .eq("user_id", uid).eq("symbol", sym).execute()
        else:
            _supabase.table("alerts").insert(d).execute()
    except: pass

def db_del_alert(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("alerts").delete() \
        .eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

def db_load_portfolio(uid: str) -> dict:
    if not HAS_DB: return {}
    try:
        r = _supabase.table("portfolio").select("*").eq("user_id", uid).execute()
        return {x["symbol"]: {
            "cost": x["cost_price"], "shares": x["shares"],
            "note": x.get("note", ""), "buy_date": x.get("buy_date", ""),
        } for x in r.data}
    except: return {}

def db_save_portfolio(uid, sym, cost, shares, note="", buy_date=""):
    if not HAS_DB: return
    try:
        ex = _supabase.table("portfolio").select("id") \
            .eq("user_id", uid).eq("symbol", sym).execute()
        d = {"user_id": uid, "symbol": sym, "cost_price": cost,
             "shares": shares, "note": note, "buy_date": buy_date}
        if ex.data:
            _supabase.table("portfolio").update(d) \
                .eq("user_id", uid).eq("symbol", sym).execute()
        else:
            _supabase.table("portfolio").insert(d).execute()
    except: pass

def db_del_portfolio(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("portfolio").delete() \
        .eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

# ══════════════════════════════════════════════════════
# 7. 靜態資料
# ══════════════════════════════════════════════════════
TW_HOT = {
    "半導體": [("2330","台積電"),("2454","聯發科"),("2303","聯電"),("3711","日月光")],
    "ETF":    [("0050","台灣50"),("0056","高股息"),("00878","永續高息"),("00929","科技優息")],
    "金融":   [("2882","國泰金"),("2881","富邦金"),("2891","中信金"),("2884","玉山金")],
    "傳產":   [("1301","台塑"),("2002","中鋼"),("2412","中華電"),("1216","統一")],
}
US_HOT = {
    "科技":   [("AAPL","蘋果"),("MSFT","微軟"),("NVDA","輝達"),("GOOGL","Google")],
    "AI/半導": [("AMD","超微"),("TSM","台積電ADR"),("SMCI","超微電腦"),("PLTR","Palantir")],
    "ETF":    [("SPY","S&P500"),("QQQ","那斯達克"),("VT","全球"),("ARKK","方舟")],
    "其他":   [("TSLA","特斯拉"),("AMZN","亞馬遜"),("META","Meta"),("NFLX","Netflix")],
}

GLOSSARY = {
    "RSI": "相對強弱指標，0~100。>70超買（漲太快），<30超賣（跌太多），50附近多空平衡。",
    "MACD": "動能指標。柱狀圖由負轉正=動能轉強；由正轉負=動能轉弱。",
    "布林通道": "股價正常波動範圍。上軌=過熱，下軌=超賣，通道收窄=大行情即將爆發。",
    "ATR": "平均真實波幅，衡量每天正常波動多少錢。ATR大=風險高，ATR小=比較穩。",
    "Stochastic KD": "衡量現價在近期高低點的位置。K>80超買，K<20超賣。",
    "OBV 能量潮": "把成交量方向累計。OBV上升=資金流入（買氣強）；下降=資金流出（賣壓重）。",
    "VWAP": "成交量加權均價，機構法人的重要參考。現價>VWAP=多方強勢。",
    "費波那契": "黃金比例的支撐壓力位。0.382和0.618是最重要的關鍵位置。",
    "本益比 PE": "花多少錢買1元獲利。PE=20代表要20年回本，越低可能越便宜。",
    "ROE": "股東權益報酬率，公司用你的錢賺錢的效率，越高越好。",
    "Beta": "與大盤連動程度。>1表示漲跌比大盤更劇烈。",
    "停損": "股價跌到某個價位就認賠出場，保護本金最重要的工具。",
    "風報比": "預期獲利÷預期虧損。至少要2:1以上才值得考慮。",
    "MDD 最大回撤": "從最高點到最低點的最大跌幅，衡量最壞的情況你會虧多少。",
    "定期定額 DCA": "每個月固定投入固定金額，不管股價高低都買，攤平成本的策略。",
    "VIX 恐慌指數": ">30=市場非常恐慌（可能是抄底機會）；<15=市場過於樂觀（要小心）。",
}

# ══════════════════════════════════════════════════════
# 8. 工具函數
# ══════════════════════════════════════════════════════
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

def fmt_num(v, suffix=""):
    if isinstance(v, (int, float)):
        if abs(v) >= 1e12: return f"{v/1e12:.2f}兆{suffix}"
        if abs(v) >= 1e8:  return f"{v/1e8:.1f}億{suffix}"
        if abs(v) >= 1e4:  return f"{v/1e4:.1f}萬{suffix}"
        return f"{v:,.2f}{suffix}"
    return str(v)

# ══════════════════════════════════════════════════════
# 9. 數據抓取（快取）
# ══════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data(symbol: str, period: str):
    for i in range(3):
        try:
            t = yf.Ticker(symbol)
            h = t.history(period=period)
            info = t.info
            if h.empty: return None, None, "查無此代號，請確認輸入"
            return h, info, None
        except Exception as e:
            if i == 2: return None, None, f"抓取失敗：{str(e)[:60]}"
            time.sleep(1)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_only(symbol: str) -> float:
    try:
        h = yf.Ticker(symbol).history(period="2d")
        if not h.empty: return round(float(h["Close"].iloc[-1]), 2)
    except: pass
    return 0.0

@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_overview():
    indices = {
        "台灣加權": "^TWII", "S&P 500": "^GSPC",
        "那斯達克": "^IXIC", "VIX 恐慌": "^VIX",
        "費城半導": "^SOX", "美元指數": "DX-Y.NYB",
    }
    rows = []
    for name, sym in indices.items():
        try:
            h = yf.Ticker(sym).history(period="2d")
            if not h.empty and len(h) >= 2:
                p   = round(float(h["Close"].iloc[-1]), 2)
                chg = round((float(h["Close"].iloc[-1]) - float(h["Close"].iloc[-2])) /
                            max(float(h["Close"].iloc[-2]), 0.01) * 100, 2)
                rows.append({"名稱": name, "現值": p, "漲跌%": chg})
        except: pass
    return rows

# ══════════════════════════════════════════════════════
# 10. 技術指標計算（15 項 + NaN 防護）
# ══════════════════════════════════════════════════════
def calc_indicators(hist: pd.DataFrame) -> dict:
    c = hist["Close"].squeeze().astype(float)
    h = hist["High"].squeeze().astype(float)
    l = hist["Low"].squeeze().astype(float)
    v = hist["Volume"].squeeze().astype(float)
    n = len(c)

    def _last(s):
        try:
            val = float(s.iloc[-1])
            return val if val == val else 0.0
        except: return 0.0

    # 均線
    ma5   = c.rolling(5).mean()
    ma20  = c.rolling(20).mean()
    ma60  = c.rolling(min(60, n)).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()

    # MACD
    macd     = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    macd_h   = macd - macd_sig

    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = (100 - 100 / (1 + gain / loss.replace(0, 1e-10))).clip(0, 100)

    # Stochastic RSI
    r_min = rsi.rolling(14).min()
    r_max = rsi.rolling(14).max()
    stk   = (100 * (rsi - r_min) / (r_max - r_min + 1e-10)).clip(0, 100)
    std   = stk.rolling(3).mean()

    # Bollinger Bands
    bb_m = c.rolling(20).mean()
    bb_s = c.rolling(20).std()
    bb_u = bb_m + 2 * bb_s
    bb_l = bb_m - 2 * bb_s
    bb_pct   = ((c - bb_l) / (bb_u - bb_l + 1e-10) * 100).clip(0, 100)
    bb_width = ((bb_u - bb_l) / (bb_m + 1e-10) * 100)

    # ATR
    prev_c = c.shift(1)
    tr  = pd.concat([(h-l), (h-prev_c).abs(), (l-prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # OBV
    obv = (v * ((c.diff() > 0).astype(float) * 2 - 1)).fillna(0).cumsum()

    # Williams %R
    hh  = h.rolling(14).max()
    ll_ = l.rolling(14).min()
    wr  = (-100 * (hh - c) / (hh - ll_ + 1e-10)).clip(-100, 0)

    # VWAP
    tp   = (h + l + c) / 3
    vwap = (tp * v).rolling(20).sum() / (v.rolling(20).sum() + 1e-10)

    price   = round(_last(c), 2)
    atr_val = round(_last(atr), 4)
    if atr_val == 0: atr_val = round(price * 0.02, 2)

    def chg(ref_idx):
        if n > ref_idx:
            r = safe_f(c.iloc[-(ref_idx+1)])
            return round((price - r) / max(r, 0.01) * 100, 2)
        return 0.0

    ind = {
        "price": price, "change_pct": chg(1), "change_5d": chg(5), "change_1m": chg(21),
        "ma5": round(_last(ma5), 2), "ma20": round(_last(ma20), 2),
        "ma60": round(_last(ma60), 2), "vwap": round(_last(vwap), 2),
        "rsi": round(_last(rsi), 1), "stoch_k": round(_last(stk), 1),
        "stoch_d": round(_last(std), 1), "williams_r": round(_last(wr), 1),
        "macd": round(_last(macd), 4), "macd_sig": round(_last(macd_sig), 4),
        "macd_hist": round(_last(macd_h), 4),
        "atr": atr_val,
        "bb_upper": round(_last(bb_u), 2), "bb_mid": round(_last(bb_m), 2),
        "bb_lower": round(_last(bb_l), 2), "bb_pct": round(_last(bb_pct), 1),
        "bb_width": round(_last(bb_width), 1),
        "volume": int(_last(v)), "vol_ma20": int(_last(v.rolling(20).mean())),
        "obv": round(_last(obv), 0),
        "high_52w": round(float(c.rolling(min(252,n)).max().iloc[-1]), 2),
        "low_52w":  round(float(c.rolling(min(252,n)).min().iloc[-1]), 2),
        # series for chart
        "_c":c,"_h":h,"_l":l,"_v":v,
        "_rsi":rsi,"_stk":stk,"_macd":macd,"_macd_sig":macd_sig,"_macd_h":macd_h,
        "_bb_u":bb_u,"_bb_l":bb_l,"_bb_m":bb_m,
        "_ma5":ma5,"_ma20":ma20,"_ma60":ma60,"_obv":obv,
    }

    vr = ind["volume"] / max(ind["vol_ma20"], 1)
    ind["vol_ratio"] = round(vr, 2)
    if vr >= 2.5:   ind["vol_desc"] = f"🔥 爆量 {vr:.1f}倍均量，市場極度關注"
    elif vr >= 1.5: ind["vol_desc"] = f"📢 放量 {vr:.1f}倍，積極參與"
    elif vr >= 0.8: ind["vol_desc"] = f"📊 正常量 {vr:.1f}倍"
    else:           ind["vol_desc"] = f"😴 縮量 {vr:.1f}倍，訊號可信度低"

    pos = (price - ind["low_52w"]) / max(ind["high_52w"] - ind["low_52w"], 0.01) * 100
    ind["position_52w"] = round(pos, 1)

    r_val = ind["rsi"]; k_val = ind["stoch_k"]; m_val = ind["macd_hist"]
    if ind["ma5"] > ind["ma20"] > ind["ma60"] and r_val > 55 and m_val > 0:
        ind["status"] = "強勢多頭 📈"; ind["sc"] = "🟢"
        ind["status_desc"] = "均線多頭排列＋RSI偏強＋MACD正值，三重確認多頭。"
    elif ind["ma5"] < ind["ma20"] < ind["ma60"] and r_val < 45 and m_val < 0:
        ind["status"] = "強勢空頭 📉"; ind["sc"] = "🔴"
        ind["status_desc"] = "均線空頭排列＋RSI偏弱＋MACD負值，三重確認空頭。"
    elif r_val <= 30 and k_val < 20:
        ind["status"] = "雙重超賣，留意反彈 🟡"; ind["sc"] = "🟡"
        ind["status_desc"] = "RSI與Stochastic雙雙超賣，反彈機率升高，需量能確認。"
    elif r_val >= 70 and k_val > 80:
        ind["status"] = "雙重超買，注意回調 🟡"; ind["sc"] = "🟡"
        ind["status_desc"] = "RSI與Stochastic雙雙超買，短線獲利了結壓力大。"
    elif abs(ind["ma5"] - ind["ma20"]) / max(price, 0.01) < 0.015:
        ind["status"] = "均線糾結蓄勢 ⚪"; ind["sc"] = "⚪"
        ind["status_desc"] = "均線纏繞，等待突破方向，大行情可能即將爆發。"
    elif ind["ma5"] > ind["ma20"] and r_val > 50:
        ind["status"] = "短線偏多 🔵"; ind["sc"] = "🔵"
        ind["status_desc"] = "短均線在長均線上方，RSI偏強，短線多方略佔優勢。"
    else:
        ind["status"] = "弱勢盤整 🟠"; ind["sc"] = "🟠"
        ind["status_desc"] = "走勢疲軟，方向不明，建議觀望。"

    if r_val >= 80:   ind["rsi_desc"] = f"⚠️ RSI {r_val}，嚴重超買"
    elif r_val >= 70: ind["rsi_desc"] = f"⚠️ RSI {r_val}，超買區"
    elif r_val <= 20: ind["rsi_desc"] = f"💡 RSI {r_val}，嚴重超賣，留意反彈"
    elif r_val <= 30: ind["rsi_desc"] = f"💡 RSI {r_val}，超賣區"
    elif r_val >= 55: ind["rsi_desc"] = f"✅ RSI {r_val}，多方偏強"
    elif r_val <= 45: ind["rsi_desc"] = f"⚠️ RSI {r_val}，空方偏強"
    else:             ind["rsi_desc"] = f"➡️ RSI {r_val}，多空均衡"

    return ind

# ══════════════════════════════════════════════════════
# 11. 評分
# ══════════════════════════════════════════════════════
def calc_score(ind: dict, info: dict) -> dict:
    trend = min(30, (8 if ind["ma5"]>ind["ma20"] else 0) +
                    (8 if ind["ma20"]>ind["ma60"] else 0) +
                    (7 if ind["price"]>ind["ma20"] else 0) +
                    (7 if ind["macd_hist"]>0 else 0))
    r = ind["rsi"]; k = ind["stoch_k"]; wr = ind["williams_r"]
    mom = min(25, (10 if 50<=r<=70 else 8 if r<30 else 5 if 40<=r<50 else 3) +
                  (8 if 40<=k<=80 else 5 if k<20 else 0) +
                  (7 if wr>-50 else 0))
    vr = ind["vol_ratio"]
    vol = min(20, 20 if vr>=1.5 and ind["change_pct"]>0 else
                  15 if vr>=1.2 and ind["change_pct"]>0 else
                  10 if 0.8<=vr<=1.5 else 5)
    pos = ind["position_52w"]
    psc = min(15, 15 if 30<=pos<=70 else 12 if pos<20 else 10 if pos<30 or pos<80 else 4)
    bsc = min(10, 10 if 20<=ind["bb_pct"]<=80 else 7 if ind["bb_pct"]<20 else 3)
    total = trend + mom + vol + psc + bsc
    if total >= 80:   grade, gc = "A（優秀）", "#00cc66"
    elif total >= 65: grade, gc = "B（良好）", "#66cc00"
    elif total >= 50: grade, gc = "C（普通）", "#ffaa00"
    elif total >= 35: grade, gc = "D（偏弱）", "#ff6600"
    else:             grade, gc = "E（警示）", "#ff3333"
    return {"total": total, "grade": grade, "gc": gc,
            "trend": trend, "mom": mom, "vol": vol, "pos": psc, "bb": bsc}

# ══════════════════════════════════════════════════════
# 12. 入場策略
# ══════════════════════════════════════════════════════
def calc_entry(ind: dict, hist: pd.DataFrame) -> dict:
    c = ind["_c"]; h = ind["_h"]; l = ind["_l"]
    price = ind["price"]
    atr   = max(ind["atr"], price * 0.005)
    n     = len(c); w = min(60, n)

    ph = round(float(h.iloc[-w:].max()), 2)
    pl = round(float(l.iloc[-w:].min()), 2)
    fr = max(ph - pl, atr)

    fibs = {k: round(ph - v * fr, 2) for k, v in
            [("0.236",0.236),("0.382",0.382),("0.500",0.500),("0.618",0.618),("0.786",0.786)]}

    sup1 = round(float(l.iloc[-20:].min()), 2)
    sup2 = round(float(l.iloc[-w:].min()), 2)
    res1 = round(float(h.iloc[-20:].max()), 2)
    res2 = round(float(h.iloc[-w:].max()), 2)

    con_buy  = round(min(sup1, fibs["0.382"]), 2)
    mod_buy  = round((sup1 + ind["ma20"]) / 2, 2)
    agg_buy  = round(price * 0.995, 2)
    sl_tight  = round(price - 1.5 * atr, 2)
    sl_normal = round(price - 2.5 * atr, 2)
    sl_wide   = round(max(sup2 * 0.97, price - 4 * atr), 2)
    tp1 = round(price + 2 * atr, 2)
    tp2 = round(price + 4 * atr, 2)
    tp3 = round(max(res2 * 1.02, price + 6 * atr), 2)
    rr  = round((tp1 - mod_buy) / max(mod_buy - sl_normal, 0.01), 2)

    return dict(fibs=fibs, sup1=sup1, sup2=sup2, res1=res1, res2=res2,
                con_buy=con_buy, mod_buy=mod_buy, agg_buy=agg_buy,
                sl_tight=sl_tight, sl_normal=sl_normal, sl_wide=sl_wide,
                tp1=tp1, tp2=tp2, tp3=tp3, rr=rr, ph=ph, pl=pl,
                atr=atr, lot_cost=round(mod_buy * 1000, 0))

# ══════════════════════════════════════════════════════
# 13. Gemini AI（自動切換模型）
# ══════════════════════════════════════════════════════
def call_ai(api_key: str, prompt: str, use_search: bool = False) -> str:
    client = genai.Client(api_key=api_key)
    models = [
        ("gemini-2.5-flash",      "Gemini 2.5 Flash"),
        ("gemini-2.0-flash",      "Gemini 2.0 Flash"),
        ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite"),
    ]
    last_err = None
    for mid, mname in models:
        try:
            if use_search:
                cfg = genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.2,
                )
                resp = client.models.generate_content(model=mid, contents=prompt, config=cfg)
            else:
                resp = client.models.generate_content(model=mid, contents=prompt)
            tag = "＋🔍即時搜尋" if use_search else ""
            ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
            return f"> 🤖 {mname}{tag}　｜　生成時間：{ts}\n\n{resp.text}"
        except Exception as e:
            err = str(e)
            if any(k in err for k in ["quota","429","RESOURCE_EXHAUSTED","404","not found"]):
                last_err = err[:80]; continue
            raise
    raise Exception(f"所有模型均無法使用：{last_err}")

# ══════════════════════════════════════════════════════
# 14. AI Prompts（去蕪存菁版）
# ══════════════════════════════════════════════════════
def ai_full_report(ind, info, sym, api_key, entry, score) -> str:
    co  = info.get("longName") or info.get("shortName") or sym
    sec = info.get("sector","未知")
    atr = entry["atr"]

    # 明日 ATR 預算
    bull_hi = round(ind["price"] + 1.5 * atr, 2)
    bull_lo = round(ind["price"] - 0.5 * atr, 2)
    bear_hi = round(ind["price"] + 0.5 * atr, 2)
    bear_lo = round(ind["price"] - 1.5 * atr, 2)
    neut_hi = round(ind["price"] + 1.0 * atr, 2)
    neut_lo = round(ind["price"] - 1.0 * atr, 2)
    max_up  = round(ind["price"] + 3.0 * atr, 2)
    max_dn  = round(ind["price"] - 3.0 * atr, 2)

    def pct(v): return f"{v*100:.1f}%" if isinstance(v,float) else str(v)

    prompt = f"""# 任務
你是頂級量化分析師兼新手教師。**先即時搜尋**「{co}（{sym}）」最新資訊，再輸出報告。

## 搜尋清單（必須全部搜尋）
- {co} 過去7天新聞、財報、法說會
- {sec} 產業最新動態、供應鏈
- 聯準會/各國央行最新動態、利率預期
- 美元指數DXY、VIX恐慌指數現值
- 川普最新政策聲明（貿易/關稅/科技）
- 今晚至明日預定公布的重要經濟數據（CPI/非農/FOMC等）
- 費城半導體指數、台指期現況

## 輸入數據
**基本面**｜PE={info.get('trailingPE','N/A')} 預估PE={info.get('forwardPE','N/A')} PB={info.get('priceToBook','N/A')} EPS={info.get('trailingEps','N/A')} ROE={pct(info.get('returnOnEquity',0))} 毛利率={pct(info.get('grossMargins',0))} 股息率={pct(info.get('dividendYield',0))} Beta={info.get('beta','N/A')} 分析師目標價={info.get('targetMeanPrice','N/A')} 評級={info.get('recommendationKey','N/A')}
**技術面**｜現價={ind['price']} 今={ind['change_pct']}% 5日={ind['change_5d']}% 月={ind['change_1m']}%
MA5={ind['ma5']} MA20={ind['ma20']} MA60={ind['ma60']} VWAP={ind['vwap']}
RSI={ind['rsi']} StochK={ind['stoch_k']} D={ind['stoch_d']} Williams%R={ind['williams_r']}
MACD={ind['macd']} Sig={ind['macd_sig']} Hist={ind['macd_hist']}
布林U={ind['bb_upper']} M={ind['bb_mid']} L={ind['bb_lower']} 位置={ind['bb_pct']:.0f}% 寬度={ind['bb_width']}%
ATR={atr} OBV={'↑買氣' if ind['obv']>0 else '↓賣壓'} {ind['vol_desc']}
52W高={ind['high_52w']} 低={ind['low_52w']} 位置={ind['position_52w']}%
狀態={ind['status']} 評分={score['total']}/100（{score['grade']}）
**入場**｜支撐1={entry['sup1']} 支撐2={entry['sup2']} 壓力1={entry['res1']} 壓力2={entry['res2']}
穩健買={entry['mod_buy']} 停損={entry['sl_normal']} T1={entry['tp1']} T2={entry['tp2']} 風報比={entry['rr']}:1
**ATR明日震幅預算**｜樂觀:{bull_lo}～{bull_hi} 悲觀:{bear_lo}～{bear_hi} 中性:{neut_lo}～{neut_hi} 上限:{max_dn}～{max_up}

## 輸出格式規則（嚴格遵守）
- 禁止開場白、禁止說「好的我來分析」、禁止廢話
- 使用**條列式Bullet**、**粗體數據**、短句
- 術語第一次出現加（白話解釋）
- 禁止「一定」「保證」「必漲」「必跌」「穩賺」
- 明日預測不得超過3倍ATR（除非有重大消息）
- 所有入場建議加「⚠️ 僅供參考，不構成投資建議」
- 繁體中文輸出

---

## 🌍 宏觀環境（搜尋後填入）
- **聯準會**：（利率預期、最新聲明）→ 對{co}影響：強/中/弱
- **川普政策**：（最新聲明）→ 對{sec}影響：（說明）
- **今晚重要數據**：（公布時間、市場預期、可能衝擊方向）
- **VIX**：（現值，是恐慌還是樂觀？）
- **費城半導/台指期**：（現況、對{sym}的連動）

## 📰 公司最新情報（搜尋後填入）
（條列3~5則，每則格式：✅/❌/➡️ **標題** → 影響：⬆️/⬇️/↔️ 程度：高/中/低）

## 📊 技術指標解讀
- **趨勢**：MA5{'>''' if ind['ma5']>ind['ma20'] else '<'}MA20，均線{'多頭排列' if ind['ma5']>ind['ma20']>ind['ma60'] else '空頭排列' if ind['ma5']<ind['ma20']<ind['ma60'] else '混亂'}→（說明含義）
- **動能**：RSI={ind['rsi']}（{ind['rsi_desc']}）、StochK={ind['stoch_k']}（{'超買' if ind['stoch_k']>80 else '超賣' if ind['stoch_k']<20 else '中性'}）→ 兩者{'共振' if (ind['rsi']>70)==(ind['stoch_k']>80) or (ind['rsi']<30)==(ind['stoch_k']<20) else '分歧'}
- **MACD**：Hist={ind['macd_hist']}（{'正值，動能增強' if ind['macd_hist']>0 else '負值，動能減弱'}）→ 柱體{'擴大' if abs(ind['macd_hist'])>0.01 else '縮小'}代表（說明）
- **布林**：現價在通道{ind['bb_pct']:.0f}%，{'接近上軌過熱' if ind['bb_pct']>80 else '接近下軌超賣' if ind['bb_pct']<20 else '通道中段'}，ATR={atr}（每日正常波動約{atr}元）
- **量能**：{ind['vol_desc']}，OBV{'↑資金持續流入' if ind['obv']>0 else '↓資金持續流出'}

## 💰 入場策略（⚠️ 僅供參考，不構成投資建議）
| 策略 | 進場價 | 停損 | 目標T1 | 目標T2 | 風報比 |
|------|--------|------|--------|--------|--------|
| 保守 | {entry['con_buy']} | {entry['sl_wide']} | {entry['tp1']} | {entry['tp2']} | - |
| 穩健 | {entry['mod_buy']} | {entry['sl_normal']} | {entry['tp1']} | {entry['tp2']} | {entry['rr']}:1 |
| 積極 | {entry['agg_buy']} | {entry['sl_tight']} | {entry['tp1']} | {entry['tp2']} | - |

- **台股一張參考成本**：約 {entry['lot_cost']:,.0f} 元（穩健買入×1000股）
- **倉位建議**：評分{score['total']}分，建議新手用總資金的{'10~15%' if score['total']>=65 else '5~10%' if score['total']>=50 else '5%以下或觀望'}

## 🔮 明日走勢沙盤推演

> **ATR={atr}｜嚴格約束：預測範圍 {max_dn}～{max_up}（±3倍ATR上限）**

**📌 預期方向**：（偏多/偏空/震盪，必須說明技術面訊號與新聞情緒是共振還是分歧）

**📐 三情境震幅（基於ATR計算，不得超出±3倍ATR）**：
- 🟢 **樂觀**（多方主導）：**{bull_lo}～{bull_hi}**（條件：需守住{entry['sup1']}且突破{entry['res1']}）
- 🔴 **悲觀**（空方主導）：**{bear_lo}～{bear_hi}**（條件：跌破{entry['sup1']}且量縮）
- ⚪ **中性**（區間整理）：**{neut_lo}～{neut_hi}**（條件：量能不足，方向未明）
- **最可能情境**：（說明理由，結合技術面＋即時新聞）

**⚔️ 關鍵多空交戰點**：
- 🛡️ **多方必守**：**{entry['sup1']}**（跌破=空方取得優勢，下一支撐在{entry['sup2']})
- 🚀 **空方必突**：**{entry['res1']}**（帶量突破=多方確認，下一壓力在{entry['res2']})
- ⚡ **明日盤中觀察重點**：（最重要的1~2個具體指標或價位，出現什麼代表方向確立）

**🌀 潛在變數（今晚至明日）**：
- 📅 預定數據：（名稱、時間、影響方向）
- 📢 公司事件：（財報/法說/公告？）
- 😱 黑天鵝風險：（最可能讓預測失效的事件，機率高/中/低）

**🎯 預測信心等級**：⬛⬛⬛⬜⬜（說明：技術面清晰度×新聞面確定性×宏觀環境穩定性）

## 🎯 短中期研判
- **短期（1~2週）**：（結合技術+新聞，說明關鍵觀察點）
- **中期（1~3月）**：（結合基本面+產業趨勢）

## ⚠️ 主要風險（條列5點，技術+基本面+新聞面）

## 📌 小白一句話總結
（用生活化比喻，說明這支股票目前狀態＋評分{score['total']}分代表什麼，是否值得繼續關注）"""

    return call_ai(api_key, prompt, use_search=True)


def ai_news_only(company, sym, sector, api_key) -> str:
    prompt = f"""即時搜尋「{company}（{sym}）」所有最新資訊後輸出。

搜尋範圍：公司新聞/財報/公告、{sector}產業動態、宏觀政策（聯準會/川普/各國央行）、競爭對手、分析師評級、社群情緒。

## 📰 公司最新消息（過去14天）
（條列，格式：✅/❌/➡️ **標題** → 影響：⬆️/⬇️/↔️ 程度：高/中/低）

## 🌍 宏觀環境對此股影響
（聯準會/川普/匯率/VIX → 各自對{company}的影響強弱）

## 🏭 產業鏈動態
（供需、競爭對手、上下游）

## 💬 分析師與市場情緒
（最新評級調整、目標價、社群討論熱度）

## ⚡ 黑天鵝風險清單

## 🎯 新聞面綜合評估
- 整體氣氛：正面/負面/中立
- 影響力：強/中/弱
- 信心水準：高/中/低

## ⚠️ 新手看新聞常犯的3個錯誤（針對此股）

禁止開場白廢話。禁止「一定」「保證」「必漲」「必跌」。繁體中文。"""
    return call_ai(api_key, prompt, use_search=True)


def ai_chip_report(company, sym, info, api_key) -> str:
    def pct(v): return f"{v*100:.1f}%" if isinstance(v, float) else str(v)
    prompt = f"""即時搜尋「{company}（{sym}）」最新財務數據與分析師評價後輸出。

數據：PE={info.get('trailingPE','N/A')} 預估PE={info.get('forwardPE','N/A')} PB={info.get('priceToBook','N/A')}
ROE={pct(info.get('returnOnEquity',0))} 毛利率={pct(info.get('grossMargins',0))} 淨利率={pct(info.get('profitMargins',0))}
Beta={info.get('beta','N/A')} 評級={info.get('recommendationKey','N/A')} 目標價={info.get('targetMeanPrice','N/A')}
負債權益比={info.get('debtToEquity','N/A')} 流動比率={info.get('currentRatio','N/A')}

## 💰 基本面白話解讀
（每個數據：**數值** → 代表什麼？跟產業平均比是貴還是便宜？）

## 🌐 分析師最新共識
（目標價範圍、評級分佈、最近有調升/調降？）

## 📊 與主要競爭對手比較
（搜尋同產業對手，製作簡單比較，誰的基本面更好？）

## 🏦 法人籌碼解讀
（機構持股比例、最近加減碼動向、對散戶的參考意義）

## ⚠️ 新手看基本面常犯的3個錯誤

禁止開場白廢話。禁止「一定」「保證」「必漲」「必跌」。繁體中文。"""
    return call_ai(api_key, prompt, use_search=True)


def ai_trade_review(sym, co, cost, current_price, shares, buy_date, ind, entry, api_key) -> str:
    pnl_pct = round((current_price - cost) / max(cost, 0.01) * 100, 2)
    prompt = f"""你是客觀的交易覆盤教練。分析以下持股並給出具體建議。

持股資訊：{co}（{sym}）｜買入成本：{cost}｜現價：{current_price}｜損益：{pnl_pct:+.2f}%
買入日期：{buy_date}｜持有股數：{shares}

技術面現況：{ind['status']}｜RSI={ind['rsi']}｜MACD Hist={ind['macd_hist']}
支撐={entry['sup1']}｜壓力={entry['res1']}｜ATR={entry['atr']}
標準停損={entry['sl_normal']}｜T1={entry['tp1']}｜T2={entry['tp2']}

## 📊 買點覆盤
- 以當時技術面判斷，這個買點合理嗎？（評估：買在支撐/壓力/中間？RSI當時可能在哪個區間？）

## 🎯 現況處置建議（三選一，必須明確）
**A. 繼續持有** 或 **B. 移動停利** 或 **C. 停損出場**

給出明確建議並說明3個客觀理由（技術面為主）。

## 📐 具體操作建議（⚠️ 僅供參考，不構成投資建議）
- 若選A：關鍵支撐守住才繼續，跌破{entry['sl_normal']}執行停損
- 若選B：移動停利至{entry['tp1']}附近，守住繼續看T2={entry['tp2']}
- 若選C：說明停損執行方式與後續觀察點

## ⚠️ 新手持股常犯的2個心理誤區（針對目前盈虧狀況）

禁止開場白廢話。禁止「一定」「保證」「必漲」「必跌」。繁體中文。"""
    return call_ai(api_key, prompt, use_search=False)

# ══════════════════════════════════════════════════════
# 15. 圖表
# ══════════════════════════════════════════════════════
DARK = "plotly_dark"

def build_main_chart(hist, ind, entry, sym):
    idx = hist.index
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.50, 0.18, 0.17, 0.15],
        subplot_titles=["K線+均線+布林", "成交量", "RSI+Stochastic", "MACD"],
        vertical_spacing=0.04,
    )
    # K線
    fig.add_trace(go.Candlestick(
        x=idx, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name="K線",
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
    ), row=1, col=1)
    # 均線
    for key, color, nm in [("_ma5","#FFA726","MA5"),("_ma20","#42A5F5","MA20"),("_ma60","#AB47BC","MA60")]:
        fig.add_trace(go.Scatter(x=idx, y=ind[key],
            line=dict(color=color, width=1.3), name=nm), row=1, col=1)
    # 布林
    fig.add_trace(go.Scatter(x=idx, y=ind["_bb_u"],
        line=dict(color="rgba(255,235,59,0.5)", width=1, dash="dot"), name="布林上"), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_bb_l"],
        line=dict(color="rgba(255,235,59,0.5)", width=1, dash="dot"), name="布林下",
        fill="tonexty", fillcolor="rgba(255,235,59,0.04)"), row=1, col=1)
    # 支撐壓力
    for y_val, color, label in [
        (entry["sup1"], "rgba(38,166,154,0.8)", f"支撐 {entry['sup1']}"),
        (entry["res1"], "rgba(239,83,80,0.8)",  f"壓力 {entry['res1']}"),
        (entry["mod_buy"], "rgba(100,220,100,0.8)", f"參考買入 {entry['mod_buy']}"),
    ]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=color,
                      annotation_text=label, annotation_font_size=10, row=1, col=1)
    # 成交量
    vc = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(hist["Close"], hist["Open"])]
    fig.add_trace(go.Bar(x=idx, y=ind["_v"], marker_color=vc, showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_v"].rolling(20).mean(),
        line=dict(color="#FFA726", width=1.2), showlegend=False, name="均量"), row=2, col=1)
    # RSI + Stochastic
    fig.add_trace(go.Scatter(x=idx, y=ind["_rsi"],
        line=dict(color="#FF7043", width=1.5), name="RSI", showlegend=False), row=3, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_stk"],
        line=dict(color="#66BB6A", width=1, dash="dot"), name="Stoch K", showlegend=False), row=3, col=1)
    for lv, lc in [(70,"rgba(239,83,80,0.4)"), (50,"rgba(150,150,150,0.3)"), (30,"rgba(38,166,154,0.4)")]:
        fig.add_hline(y=lv, line_dash="dash", line_color=lc, row=3, col=1)
    # MACD
    mc_c = ["#ef5350" if x >= 0 else "#26a69a" for x in ind["_macd_h"]]
    fig.add_trace(go.Bar(x=idx, y=ind["_macd_h"], marker_color=mc_c, showlegend=False), row=4, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_macd"],
        line=dict(color="#42A5F5", width=1), showlegend=False), row=4, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_macd_sig"],
        line=dict(color="#FF7043", width=1), showlegend=False), row=4, col=1)

    fig.update_layout(
        template=DARK, title=f"{sym} 技術分析", height=800,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, font_size=11),
        margin=dict(l=50, r=50, t=80, b=30),
    )
    return fig


def build_heatmap(market: str):
    hot = TW_HOT if "台股" in market else US_HOT
    rows = []
    for sector, stocks in hot.items():
        for sym_, name_ in stocks:
            try:
                full_sym = sym_ + ".TW" if "台股" in market and not sym_.endswith(".TW") else sym_
                h = yf.Ticker(full_sym).history(period="2d")
                if not h.empty and len(h) >= 2:
                    chg = round((float(h["Close"].iloc[-1]) - float(h["Close"].iloc[-2])) /
                                max(float(h["Close"].iloc[-2]), 0.01) * 100, 2)
                    info_ = yf.Ticker(full_sym).info
                    mc_   = info_.get("marketCap", 1e10) or 1e10
                    rows.append({"板塊": sector, "名稱": name_,
                                 "代號": sym_, "漲跌%": chg, "市值": mc_})
            except: pass
    if not rows: return None
    df = pd.DataFrame(rows)
    fig = px.treemap(
        df, path=["板塊","名稱"], values="市值",
        color="漲跌%", color_continuous_scale="RdYlGn",
        color_continuous_midpoint=0,
        custom_data=["代號","漲跌%"],
        title=f"{'台股' if '台股' in market else '美股'} 板塊熱力圖",
        template=DARK,
    )
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{customdata[1]:.2f}%",
                      textfont_size=13)
    fig.update_layout(height=550, margin=dict(l=20, r=20, t=60, b=20),
                      coloraxis_colorbar=dict(title="漲跌%"))
    return fig


def build_dca_chart(df_dca: pd.DataFrame, sym: str):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_dca.index, y=df_dca["累積投入"],
        fill="tozeroy", name="累積投入本金",
        line=dict(color="#42A5F5", width=2),
        fillcolor="rgba(66,165,245,0.15)"))
    fig.add_trace(go.Scatter(x=df_dca.index, y=df_dca["資產現值"],
        fill="tozeroy", name="資產現值",
        line=dict(color="#66BB6A", width=2),
        fillcolor="rgba(102,187,106,0.15)"))
    fig.update_layout(
        template=DARK, title=f"{sym} 定期定額回測",
        yaxis_title="金額（元）", height=450,
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=50, r=30, t=70, b=30),
    )
    return fig

# ══════════════════════════════════════════════════════
# 16. 定期定額回測
# ══════════════════════════════════════════════════════
def run_dca(symbol: str, monthly_amount: float, years: int):
    period = f"{years}y"
    hist, _, err = fetch_data(symbol, period)
    if err or hist is None: return None, err

    hist = hist.copy()
    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    # 每月第一個交易日
    hist["ym"] = hist.index.to_period("M")
    monthly = hist.groupby("ym").first()

    records = []
    total_invest = 0.0
    total_shares = 0.0

    for period_label, row in monthly.iterrows():
        price = float(row["Close"])
        if price <= 0: continue
        shares_bought = monthly_amount / price
        total_shares += shares_bought
        total_invest  += monthly_amount
        records.append({
            "date": period_label.to_timestamp(),
            "累積投入": total_invest,
            "資產現值": total_shares * price,
        })

    if not records: return None, "無足夠歷史數據"

    df = pd.DataFrame(records).set_index("date")
    final_val = df["資產現值"].iloc[-1]
    total_rtn = round((final_val - total_invest) / max(total_invest, 0.01) * 100, 2)

    # 最大回撤 MDD
    peak = df["資產現值"].cummax()
    dd   = (df["資產現值"] - peak) / (peak + 1e-10) * 100
    mdd  = round(dd.min(), 2)

    stats = {
        "總投入本金": round(total_invest, 0),
        "最終資產現值": round(final_val, 0),
        "累積報酬率": f"{total_rtn:+.2f}%",
        "年化報酬率": f"{round(total_rtn / max(years,1), 2):+.2f}%",
        "最大回撤 MDD": f"{mdd:.2f}%",
        "回測年限": f"{years} 年",
        "每月投入": f"{monthly_amount:,.0f} 元",
    }
    return df, stats, None

# ══════════════════════════════════════════════════════
# 17. 側邊欄
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定")

    # DB 狀態
    if HAS_DB:
        st.markdown("🟢 **雲端資料庫已連線**")
    else:
        st.markdown("🟡 **本機模式**（設定 Supabase Secrets 啟用雲端）")

    # 帳號登入
    st.divider()
    st.header("👤 個人帳號")
    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號", placeholder="英文+數字", key="sid_u",
                                  help="自訂帳號名稱，用英文或數字")
            upin  = st.text_input("密碼", type="password", key="sid_p",
                                  help="請記住密碼，系統無法找回")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔑 登入", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok, uid, enc_key = db_verify_user(uname.strip(), upin.strip())
                        if ok:
                            st.session_state.user_id   = uid
                            st.session_state.username  = uname.strip()
                            st.session_state._pin      = upin.strip()
                            st.session_state.logged_in = True
                            st.session_state.watchlist = db_load_watchlist(uid)
                            st.session_state.alerts    = db_load_alerts(uid)
                            st.session_state.portfolio = db_load_portfolio(uid)
                            # 自動解密 API Key
                            if enc_key:
                                decrypted = decrypt_api_key(enc_key, upin.strip())
                                if decrypted:
                                    st.session_state.api_key = decrypted
                            st.success(f"✅ 歡迎回來，{uname}！")
                            st.rerun()
                        else:
                            st.error("❌ 帳號或密碼錯誤")
            with col_b:
                if st.button("✨ 建立", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok, uid, msg = db_create_user(uname.strip(), upin.strip())
                        if ok:
                            st.session_state.user_id   = uid
                            st.session_state.username  = uname.strip()
                            st.session_state._pin      = upin.strip()
                            st.session_state.logged_in = True
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")
    else:
        st.success(f"👤 {st.session_state.username}")
        st.caption("✅ 雲端同步" if HAS_DB else "⚠️ 本機模式")
        if st.button("🚪 登出", use_container_width=True):
            for k in ["user_id","username","logged_in","api_key","_pin"]:
                st.session_state[k] = False if k=="logged_in" else "" if k in ["api_key","_pin"] else None
            st.session_state.watchlist  = []
            st.session_state.alerts     = {}
            st.session_state.portfolio  = {}
            st.rerun()

    # API Key（已登入且有快取則顯示已存入）
    st.divider()
    if st.session_state.logged_in and st.session_state.api_key:
        st.success("🔑 API 金鑰已自動帶入")
        if st.button("🔄 更換 API 金鑰"):
            st.session_state.api_key = ""
            st.rerun()
        api_key = st.session_state.api_key
    else:
        api_key_input = st.text_input(
            "🔑 Gemini API 金鑰", type="password", placeholder="AIza...",
            help="前往 aistudio.google.com 取得免費金鑰",
            value=st.session_state.api_key,
        )
        if api_key_input and api_key_input != st.session_state.api_key:
            st.session_state.api_key = api_key_input
            # 若已登入，加密存入 DB
            if st.session_state.logged_in and HAS_DB:
                db_save_encrypted_key(
                    st.session_state.username,
                    st.session_state.get("_pin",""),
                    api_key_input,
                )
                st.success("🔒 已加密儲存到你的帳號")
        api_key = st.session_state.api_key
        if api_key: st.caption("金鑰只存在瀏覽器/帳號，不會外洩")

    # 分析設定
    st.divider()
    st.header("📊 分析設定")
    market = st.radio("股票市場", ["🇹🇼 台股", "🇺🇸 美股"],
                      help="選擇台股會自動加上 .TW 後綴")
    period = st.selectbox("分析區間", ["3mo","6mo","1y","2y"], index=1,
        format_func=lambda x: {"3mo":"3個月（短線）","6mo":"6個月（中線）","1y":"1年（長線）","2y":"2年（趨勢）"}[x],
        help="區間越長，均線越平滑，適合判斷中長線趨勢")
    st.caption("⏱️ 數據每 5 分鐘更新一次")

    # 自選股
    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號", placeholder="如 2330 或 AAPL", key="nw_sb",
                       help="輸入股票代號後按 Enter 新增")
    if nw and nw.strip():
        sa = get_sym(nw.strip(), market)
        if sa not in st.session_state.watchlist:
            st.session_state.watchlist.append(sa)
            if st.session_state.logged_in: db_add_watch(st.session_state.user_id, sa)
            st.rerun()
    for i, s in enumerate(st.session_state.watchlist):
        c1, c2 = st.columns([4,1])
        c1.write(f"• {s}")
        if c2.button("❌", key=f"dw_{i}_{s}", help="移除此自選股"):
            if st.session_state.logged_in: db_del_watch(st.session_state.user_id, s)
            st.session_state.watchlist.pop(i)
            st.rerun()

    # 警報
    st.divider()
    st.header("🔔 價格警報")
    al_s = st.text_input("代號", key="al_s", help="設定到達特定價格時提醒你")
    al_u = st.number_input("↑ 漲破提醒", 0.0, step=0.5, key="al_u",
                           help="股價漲到這個價位，分析頁會出現紅色警報")
    al_d = st.number_input("↓ 跌破提醒", 0.0, step=0.5, key="al_d",
                           help="股價跌到這個價位，分析頁會出現警報")
    if st.button("✅ 設定警報", use_container_width=True):
        if al_s.strip():
            sa2 = get_sym(al_s.strip(), market)
            st.session_state.alerts[sa2] = {"above": al_u or None, "below": al_d or None}
            if st.session_state.logged_in: db_save_alert(st.session_state.user_id, sa2, al_u, al_d)
            st.success("✅ 已設定")
    for sa3, av in list(st.session_state.alerts.items()):
        pts = []
        if av.get("above"): pts.append(f"↑{av['above']}")
        if av.get("below"): pts.append(f"↓{av['below']}")
        c1a, c2a = st.columns([4,1])
        c1a.caption(f"• {sa3}: {' / '.join(pts)}")
        if c2a.button("❌", key=f"dal_{sa3}"):
            if st.session_state.logged_in: db_del_alert(st.session_state.user_id, sa3)
            del st.session_state.alerts[sa3]; st.rerun()

    # 名詞解釋
    st.divider()
    st.header("📖 名詞解釋")
    for term, desc in GLOSSARY.items():
        with st.expander(term): st.info(desc)

# ══════════════════════════════════════════════════════
# 18. 主頁面
# ══════════════════════════════════════════════════════
st.title("📈 股市小白分析系統 Pro")
st.caption("AI即時搜尋 × 15項指標 × ATR明日沙盤 × 帳號記憶 × DCA回測")

# 大盤概況
mkt_data = fetch_market_overview()
if mkt_data:
    mkt_cols = st.columns(len(mkt_data))
    for col, row in zip(mkt_cols, mkt_data):
        chg = row["漲跌%"]
        col.metric(row["名稱"], str(row["現值"]),
                   f"{'▲' if chg>=0 else '▼'}{abs(chg):.2f}%",
                   delta_color="normal" if chg>=0 else "inverse")

# 最近查詢
if st.session_state.recent_searches:
    st.markdown("**🕐 最近查詢：**")
    rc = st.columns(min(len(st.session_state.recent_searches), 8))
    for i, rs in enumerate(st.session_state.recent_searches):
        if rc[i].button(rs, key=f"rc_{i}_{rs}"):
            st.session_state.quick_sym = rs.replace(".TW","")
            st.session_state.auto_analyze = True
            st.rerun()

st.divider()
TABS = st.tabs(["📊 個股戰情室", "💼 我的資產庫", "🗺️ 市場總覽", "⏳ 存股回測"])

# ══════════════════════════════════════════════════════
# TAB 1：個股戰情室（分析 + 新聞 + 籌碼 All-in-One）
# ══════════════════════════════════════════════════════
with TABS[0]:
    # 快速選股
    st.markdown("### 🚀 快速選股")
    hot = TW_HOT if "台股" in market else US_HOT
    for cat, stocks in hot.items():
        st.caption(f"**{cat}**")
        qcols = st.columns(len(stocks))
        for col, (sym_, name_) in zip(qcols, stocks):
            if col.button(f"{sym_}\n{name_}", use_container_width=True, key=f"qs_{sym_}_{cat}"):
                st.session_state.quick_sym = sym_
                st.session_state.auto_analyze = True
                st.rerun()

    st.divider()
    inp_col, btn_col = st.columns([3,1])
    with inp_col:
        dv = st.session_state.quick_sym or ""
        ticker_in = st.text_input("輸入股票代號",
            value=dv,
            placeholder="台股如 2330，美股如 NVDA",
            help="台股輸入4碼數字，美股輸入英文代號，系統自動處理格式",
            key="t1_ticker")
    with btn_col:
        st.write(""); st.write("")
        go_btn = st.button("🔍 開始分析", use_container_width=True, type="primary")

    should_run = go_btn or (st.session_state.auto_analyze and st.session_state.quick_sym)
    if st.session_state.auto_analyze: st.session_state.auto_analyze = False

    if should_run and (ticker_in or st.session_state.quick_sym).strip():
        use_sym = ticker_in.strip() or st.session_state.quick_sym
        if not api_key:
            st.warning("⚠️ 請先在左側輸入 Gemini API 金鑰")
            st.stop()

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
            a = st.session_state.alerts[sym]
            if a.get("above") and ind["price"] >= a["above"]:
                st.error(f"🔔 警報！{sym} 漲破 {a['above']}，現價 {ind['price']}")
            if a.get("below") and ind["price"] <= a["below"]:
                st.error(f"🔔 警報！{sym} 跌破 {a['below']}，現價 {ind['price']}")

        # 標題列
        h_col, star_col = st.columns([5,1])
        with h_col:
            st.subheader(f"📌 {co}（{sym}）")
            st.caption(f"數據時間：{ts}｜區間：{period}｜⏱️每5分鐘更新")
        with star_col:
            if sym not in st.session_state.watchlist:
                if st.button("⭐ 加入自選", use_container_width=True):
                    st.session_state.watchlist.append(sym)
                    if st.session_state.logged_in: db_add_watch(st.session_state.user_id, sym)
                    st.success("✅")
            else:
                st.success("⭐ 已追蹤")

        # 評分 + 狀態列
        sc_col, st_col = st.columns([1,2])
        with sc_col:
            st.markdown(f"""
            <div class="score-card">
                <div style="color:#64748b;font-size:11px">綜合健康評分</div>
                <div class="big-score" style="color:{score['gc']}">{score['total']}</div>
                <div style="color:#e2e8f0;font-size:13px">{score['grade']}</div>
            </div>""", unsafe_allow_html=True)
            st.progress(score["trend"]/30, text=f"趨勢 {score['trend']}/30")
            st.progress(score["mom"]/25,   text=f"動能 {score['mom']}/25")
            st.progress(score["vol"]/20,   text=f"量能 {score['vol']}/20")
            st.progress(score["pos"]/15,   text=f"位置 {score['pos']}/15")
            st.progress(score["bb"]/10,    text=f"布林 {score['bb']}/10")
        with st_col:
            st.markdown(f"""
            <div class="status-card">
                <h3 style="margin:0;color:#e2e8f0">{ind['sc']} {ind['status']}</h3>
                <p style="margin:6px 0 0;color:#94a3b8;font-size:13px">{ind['status_desc']}</p>
            </div>""", unsafe_allow_html=True)
            ci = "🔴" if ind["change_pct"]>=0 else "🟢"
            r1,r2,r3 = st.columns(3)
            r1.metric("💰 現價",  ind["price"])
            r2.metric("今日",     f"{ci}{ind['change_pct']}%")
            r3.metric("月漲跌",   f"{ind['change_1m']}%")
            r4,r5,r6 = st.columns(3)
            r4.metric("📏 RSI",  ind["rsi"],  help="0~100，>70超買，<30超賣")
            r5.metric("📦 量比", f"{ind['vol_ratio']}x", help="今日成交量/20日均量，>1.5代表放量")
            r6.metric("📐 ATR",  ind["atr"],  help="平均真實波幅，每天正常波動多少錢")

        st.divider()

        # 指標白話解讀
        with st.expander("🔍 各指標白話解讀", expanded=True):
            ia, ib, ic_ = st.columns(3)
            with ia:
                st.info(f"**📏 RSI（{ind['rsi']}）**\n\n{ind['rsi_desc']}")
                sk = ind["stoch_k"]
                st.info(f"**📊 Stochastic K（{sk}）**\n\n{'⚠️ >80 超買' if sk>80 else '💡 <20 超賣，留意反彈' if sk<20 else '➡️ 中性區間'}")
            with ib:
                st.info(f"**📦 成交量**\n\n{ind['vol_desc']}")
                bp = ind["bb_pct"]
                st.info(f"**📐 布林通道（{bp:.0f}%）**\n\n{'⚠️ 接近上軌，過熱警戒' if bp>80 else '💡 接近下軌，超賣' if bp<20 else '✅ 通道中段，波動正常'}")
            with ic_:
                st.info(f"**📅 52週位置（{ind['position_52w']}%）**\n\n{'接近高點，相對貴' if ind['position_52w']>80 else '接近低點，相對便宜' if ind['position_52w']<20 else '中間區域'}")
                mh = ind["macd_hist"]
                st.info(f"**📡 MACD（{mh:.4f}）**\n\n{'📈 正值，動能增強' if mh>0 else '📉 負值，動能減弱'}")

        st.divider()

        # 入場策略
        with st.expander("💰 入場策略參考（⚠️ 僅供參考，不構成投資建議）", expanded=True):
            e1, e2, e3 = st.columns(3)
            with e1:
                st.markdown(f"""<div class="entry-card">
                    <div style="color:#66cc66;font-weight:bold">🎯 參考買入區</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        保守：<b>{entry['con_buy']}</b><br>
                        穩健：<b>{entry['mod_buy']}</b><br>
                        積極：<b>{entry['agg_buy']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">台股一張≈ {entry['lot_cost']:,.0f} 元</div>
                </div>""", unsafe_allow_html=True)
            with e2:
                st.markdown(f"""<div class="stop-card">
                    <div style="color:#ff6666;font-weight:bold">🛡️ 停損參考</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        緊（短線）：<b>{entry['sl_tight']}</b><br>
                        標準：<b>{entry['sl_normal']}</b><br>
                        寬（長線）：<b>{entry['sl_wide']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">跌破即出場，保護本金</div>
                </div>""", unsafe_allow_html=True)
            with e3:
                st.markdown(f"""<div class="target-card">
                    <div style="color:#66aaff;font-weight:bold">🎯 目標價</div>
                    <div style="margin:8px 0;color:#e2e8f0;line-height:2">
                        T1（短）：<b>{entry['tp1']}</b><br>
                        T2（中）：<b>{entry['tp2']}</b><br>
                        T3（壓力）：<b>{entry['tp3']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">風報比：{entry['rr']}:1</div>
                </div>""", unsafe_allow_html=True)

            with st.expander("📐 Fibonacci 關鍵支撐壓力"):
                fib_df = pd.DataFrame([
                    {"位置":"0.382（強支撐）★", "價位":entry["fibs"]["0.382"], "說明":"最常見強支撐，技術派入場常用"},
                    {"位置":"0.500（中間位）",  "價位":entry["fibs"]["0.500"], "說明":"心理關鍵位，多空攻防"},
                    {"位置":"0.618（黃金比例）★","價位":entry["fibs"]["0.618"],"說明":"最重要的黃金分割位"},
                    {"位置":"近期支撐1",         "價位":entry["sup1"],          "說明":"近20日最低點"},
                    {"位置":"近期壓力1",         "價位":entry["res1"],          "說明":"近20日最高點"},
                ])
                st.dataframe(fib_df, use_container_width=True, hide_index=True)

        st.divider()

        # 圖表
        st.markdown("### 📈 技術分析圖表")
        st.caption("滑鼠滾輪縮放・拖曳移動・支撐壓力線自動標注")
        st.plotly_chart(build_main_chart(hist, ind, entry, sym), use_container_width=True)

        st.divider()

        # AI 報告（三合一：技術+新聞+籌碼）
        st.markdown("### 🤖 AI 深度戰情報告")
        sub_t = st.tabs(["📋 綜合報告（技術+新聞+明日預測）", "📰 即時新聞", "🏦 基本面籌碼"])

        with sub_t[0]:
            st.caption("Gemini AI 即時搜尋全網 × 15項指標 × ATR明日沙盤推演")
            with st.spinner("🔍 AI 即時搜尋並深度分析中（30~60 秒）..."):
                try:
                    rpt = ai_full_report(ind, info, sym, api_key, entry, score)
                    # 分段顯示
                    sections = rpt.split("\n## ")
                    st.markdown(sections[0])
                    for sec in sections[1:]:
                        lines = sec.split("\n", 1)
                        title = f"## {lines[0]}"
                        content = lines[1] if len(lines)>1 else ""
                        if "🔮" in title:
                            st.markdown(f"""<div class="predict-card">
                                <div style="color:#c084fc;font-size:15px;font-weight:bold">{title}</div>
                            </div>""", unsafe_allow_html=True)
                            st.markdown(content)
                        else:
                            with st.expander(title, expanded=("📌" in title)):
                                st.markdown(content)
                except Exception as e:
                    st.error(f"❌ AI 分析失敗：{str(e)}")

        with sub_t[1]:
            st.caption("AI 即時搜尋最新財經新聞、產業動態、宏觀政策")
            if st.button("📰 搜尋最新新聞", key="news_btn", type="primary"):
                with st.spinner("🔍 搜尋中（30~60 秒）..."):
                    try:
                        news_rpt = ai_news_only(co, sym, info.get("sector",""), api_key)
                        secs = news_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            with st.expander(f"## {lines[0]}", expanded=True):
                                st.markdown(lines[1] if len(lines)>1 else "")
                    except Exception as e:
                        st.error(f"❌ {str(e)}")

        with sub_t[2]:
            # 顯示基本面數據
            st.markdown("#### 核心財務指標")
            def pct_fmt(v): return f"{v*100:.1f}%" if isinstance(v,float) else str(v)
            metrics_ = [
                ("市值", fmt_num(info.get("marketCap","N/A"))),
                ("本益比 PE", info.get("trailingPE","N/A")),
                ("預估 PE", info.get("forwardPE","N/A")),
                ("股價淨值比 PB", info.get("priceToBook","N/A")),
                ("EPS 每股盈餘", info.get("trailingEps","N/A")),
                ("ROE 股東報酬", pct_fmt(info.get("returnOnEquity",0))),
                ("毛利率", pct_fmt(info.get("grossMargins",0))),
                ("淨利率", pct_fmt(info.get("profitMargins",0))),
                ("股息殖利率", pct_fmt(info.get("dividendYield",0))),
                ("Beta 係數", info.get("beta","N/A")),
                ("分析師目標價", info.get("targetMeanPrice","N/A")),
                ("分析師評級", info.get("recommendationKey","N/A")),
            ]
            gcols = st.columns(3)
            for i, (k_, v_) in enumerate(metrics_):
                if v_ not in [None,"N/A","0.0%"]:
                    gcols[i%3].metric(k_, v_)

            try:
                to_ = yf.Ticker(sym)
                ih_ = to_.institutional_holders
                if ih_ is not None and not ih_.empty:
                    st.markdown("#### 主要機構持股 Top10")
                    st.dataframe(ih_.head(10), use_container_width=True, hide_index=True)
            except: pass

            if st.button("🤖 AI 籌碼基本面解讀", key="chip_ai_btn"):
                with st.spinner("AI 分析中..."):
                    try:
                        chip_rpt = ai_chip_report(co, sym, info, api_key)
                        secs = chip_rpt.split("\n## ")
                        st.markdown(secs[0])
                        for sec in secs[1:]:
                            lines = sec.split("\n",1)
                            with st.expander(f"## {lines[0]}", expanded=True):
                                st.markdown(lines[1] if len(lines)>1 else "")
                    except Exception as e:
                        st.error(f"❌ {str(e)}")

        st.divider()
        st.warning("⚠️ 本系統所有分析與入場建議**僅供學習參考**，不構成任何投資建議。股市有風險，請自行判斷。")

        with st.expander("🔧 完整原始指標數據"):
            raw_df = pd.DataFrame({
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
            st.dataframe(raw_df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════
# TAB 2：我的資產庫（自選股 + 持股損益 + AI覆盤）
# ══════════════════════════════════════════════════════
with TABS[1]:
    if not st.session_state.logged_in:
        st.info("💡 **登入帳號**後，自選股與持股記錄永久保存在雲端，換電腦也不會消失。")

    port_tab, watch_tab = st.tabs(["💼 持股損益", "⭐ 自選股清單"])

    # ── 持股損益 ──
    with port_tab:
        st.markdown("### 💼 持股損益試算")
        p1,p2,p3,p4,p5 = st.columns(5)
        with p1: ps_ = st.text_input("代號", placeholder="如 2330", key="pf_s",
                                      help="輸入你買入的股票代號")
        with p2: pc_ = st.number_input("買入成本（每股）", 0.0, step=0.5, key="pf_c",
                                        help="你當初買入時每股付的價格")
        with p3: pn_ = st.number_input("持有股數", 0.0, step=100.0, key="pf_n",
                                        help="台股一張=1000股")
        with p4: pd_ = st.date_input("買入日期", key="pf_d",
                                      help="買入日期用於計算持有天數與年化報酬")
        with p5:
            st.write(""); st.write("")
            p_btn = st.button("📊 計算", use_container_width=True, type="primary")

        if p_btn and ps_.strip() and pc_>0 and pn_>0:
            ps_sym = get_sym(ps_.strip(), market)
            with st.spinner("取得現價..."):
                ph_, pi_, pe_ = fetch_data(ps_sym, "5d")
            if pe_: st.error(f"❌ {pe_}")
            else:
                cp_ = round(float(ph_["Close"].iloc[-1]), 2)
                pnl = round((cp_-pc_)*pn_, 2)
                pct_v = round((cp_-pc_)/max(pc_,0.01)*100, 2)
                tc  = round(pc_*pn_, 0)
                cv  = round(cp_*pn_, 0)
                hd  = (date.today()-pd_).days
                ann = round(pct_v/max(hd,1)*365, 2)
                co_n = (pi_ or {}).get("longName") or ps_sym

                st.subheader(f"📌 {co_n}（{ps_sym}）")
                mc1,mc2,mc3,mc4,mc5 = st.columns(5)
                mc1.metric("💰 現價",    cp_)
                mc2.metric("📊 總成本",  f"{tc:,.0f}")
                mc3.metric("💎 現值",    f"{cv:,.0f}")
                mc4.metric("損益",       f"{pnl:+,.0f}", delta=f"{pct_v:+.2f}%")
                mc5.metric("年化報酬",   f"{ann:+.1f}%")

                clr = "#0d2b0d" if pnl>=0 else "#2b0d0d"
                bdr = "#2a5a2a" if pnl>=0 else "#5a2a2a"
                st.markdown(f"""
                <div style="background:{clr};border-radius:12px;padding:16px;margin:10px 0;border:1px solid {bdr}">
                    <h3 style="margin:0;color:{'#66ff66' if pnl>=0 else '#ff6666'}">
                        {'📈 獲利中' if pnl>=0 else '📉 虧損中'}　{abs(pnl):,.0f} 元（{pct_v:+.2f}%）
                    </h3>
                    <p style="color:#94a3b8;margin:6px 0 0;line-height:1.8">
                        成本：{pc_}×{pn_:.0f}股＝{tc:,.0f}元　現值：{cp_}×{pn_:.0f}股＝{cv:,.0f}元<br>
                        每股{'獲利' if pnl>=0 else '虧損'}：{cp_-pc_:+.2f}元　持有{hd}天　年化：{ann:+.1f}%　
                        台股約{pn_/1000:.1f}張
                    </p>
                </div>""", unsafe_allow_html=True)

                # AI 覆盤教練
                st.markdown("#### 🤖 AI 交易覆盤教練")
                if api_key:
                    if st.button("🤖 請 AI 評估這筆交易", key="review_btn", type="primary"):
                        _hist_rev, _, _ = fetch_data(ps_sym, "6mo")
                        if _hist_rev is not None:
                            _ind_rev   = calc_indicators(_hist_rev)
                            _entry_rev = calc_entry(_ind_rev, _hist_rev)
                            with st.spinner("AI 評估中..."):
                                try:
                                    rev_rpt = ai_trade_review(
                                        ps_sym, co_n, pc_, cp_, pn_, str(pd_),
                                        _ind_rev, _entry_rev, api_key)
                                    secs = rev_rpt.split("\n## ")
                                    st.markdown(secs[0])
                                    for sec in secs[1:]:
                                        lines = sec.split("\n",1)
                                        with st.expander(f"## {lines[0]}", expanded=True):
                                            st.markdown(lines[1] if len(lines)>1 else "")
                                except Exception as e:
                                    st.error(f"❌ {str(e)}")
                else:
                    st.info("💡 輸入 API 金鑰後可使用 AI 覆盤功能")

                if st.session_state.logged_in:
                    if st.button("💾 儲存到持股記錄"):
                        db_save_portfolio(st.session_state.user_id, ps_sym,
                                          pc_, pn_, "", str(pd_))
                        st.session_state.portfolio[ps_sym] = {
                            "cost":pc_,"shares":pn_,"note":"","buy_date":str(pd_)}
                        st.success("✅ 已儲存")

        # 持股總覽
        if st.session_state.portfolio:
            st.divider()
            st.markdown("### 📋 我的持股總覽")
            pr_rows = []
            tc_all = 0; cv_all = 0
            for ps2, pd2 in st.session_state.portfolio.items():
                try:
                    hh2 = yf.Ticker(ps2).history(period="2d")
                    if not hh2.empty:
                        cp2 = round(float(hh2["Close"].iloc[-1]), 2)
                        p2  = round((cp2-pd2["cost"])/max(pd2["cost"],0.01)*100, 2)
                        c2  = round(pd2["cost"]*pd2["shares"], 0)
                        v2  = round(cp2*pd2["shares"], 0)
                        hd2 = ""
                        if pd2.get("buy_date"):
                            try: hd2 = f"{(date.today()-date.fromisoformat(pd2['buy_date'])).days}天"
                            except: pass
                        pr_rows.append({"代號":ps2,"成本":pd2["cost"],"現價":cp2,
                                        "損益%":f"{p2:+.2f}%","總損益":f"{v2-c2:+,.0f}",
                                        "股數":pd2["shares"],"持有":hd2})
                        tc_all+=c2; cv_all+=v2
                except: pass
            if pr_rows:
                st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)
                total_pnl = cv_all - tc_all
                total_pct = round(total_pnl/max(tc_all,1)*100, 2)
                st.metric("📊 組合總損益", f"{total_pnl:+,.0f} 元", delta=f"{total_pct:+.2f}%")

            # 雙重確認清空
            if not st.session_state.confirm_clear_port:
                if st.button("🗑️ 清空持股記錄", help="點擊後需再次確認"):
                    st.session_state.confirm_clear_port = True
                    st.rerun()
            else:
                st.markdown('<div class="confirm-warn">⚠️ 確定要清空所有持股記錄嗎？此動作無法復原！</div>', unsafe_allow_html=True)
                cc1, cc2 = st.columns(2)
                if cc1.button("✅ 確定清空", type="primary"):
                    if st.session_state.logged_in:
                        for s in list(st.session_state.portfolio.keys()):
                            db_del_portfolio(st.session_state.user_id, s)
                    st.session_state.portfolio = {}
                    st.session_state.confirm_clear_port = False
                    st.rerun()
                if cc2.button("❌ 取消"):
                    st.session_state.confirm_clear_port = False
                    st.rerun()

    # ── 自選股清單 ──
    with watch_tab:
        st.markdown("### ⭐ 自選股即時監控")
        if not st.session_state.watchlist:
            st.info("📝 自選股是空的，在左側欄位新增，或分析股票後點「加入自選」")
        else:
            with st.spinner("載入即時股價..."):
                wrows = []
                for s in st.session_state.watchlist:
                    try:
                        hh = yf.Ticker(s).history(period="5d")
                        if not hh.empty and len(hh)>=2:
                            p   = round(float(hh["Close"].iloc[-1]), 2)
                            chg = round((float(hh["Close"].iloc[-1])-float(hh["Close"].iloc[-2]))/
                                        max(float(hh["Close"].iloc[-2]),0.01)*100, 2)
                            wrows.append({"代號":s,"現價":p,
                                          "今日":f"{'🔴+' if chg>=0 else '🟢'}{chg}%",
                                          "警報":"🔔" if s in st.session_state.alerts else ""})
                        else: wrows.append({"代號":s,"現價":"N/A","今日":"-","警報":""})
                    except: wrows.append({"代號":s,"現價":"N/A","今日":"-","警報":""})
            st.dataframe(pd.DataFrame(wrows), use_container_width=True, hide_index=True)

            # 快速分析按鈕
            st.markdown("**快速分析：**")
            bcols = st.columns(min(len(st.session_state.watchlist),6))
            for i, s in enumerate(st.session_state.watchlist[:6]):
                if bcols[i].button(f"📊 {s}", key=f"wa_{i}", use_container_width=True):
                    st.session_state.quick_sym = s.replace(".TW","")
                    st.session_state.auto_analyze = True
                    st.rerun()

            # 雙重確認清空
            if not st.session_state.confirm_clear_watch:
                if st.button("🗑️ 清空自選股", help="點擊後需再次確認"):
                    st.session_state.confirm_clear_watch = True
                    st.rerun()
            else:
                st.markdown('<div class="confirm-warn">⚠️ 確定要清空所有自選股嗎？</div>', unsafe_allow_html=True)
                cc1, cc2 = st.columns(2)
                if cc1.button("✅ 確定清空", key="cw_ok", type="primary"):
                    if st.session_state.logged_in:
                        for s in st.session_state.watchlist: db_del_watch(st.session_state.user_id, s)
                    st.session_state.watchlist = []
                    st.session_state.confirm_clear_watch = False
                    st.rerun()
                if cc2.button("❌ 取消", key="cw_cancel"):
                    st.session_state.confirm_clear_watch = False
                    st.rerun()

# ══════════════════════════════════════════════════════
# TAB 3：市場熱力圖
# ══════════════════════════════════════════════════════
with TABS[2]:
    st.markdown("### 🗺️ 板塊熱力圖")
    st.caption("方塊大小=市值，顏色=今日漲跌（🟢綠=漲、🔴紅=跌）")
    st.info("💡 一眼看出今天哪個板塊最強、哪個板塊最弱")

    if st.button("🔄 載入熱力圖", type="primary", use_container_width=False,
                 help="載入需要約30~60秒，請耐心等候"):
        with st.spinner("載入各板塊即時數據..."):
            fig_hm = build_heatmap(market)
        if fig_hm:
            st.plotly_chart(fig_hm, use_container_width=True)
            st.caption("* 部分數據可能因 Yahoo Finance 限制而缺失")
        else:
            st.warning("數據載入失敗，請稍後再試")

    st.divider()
    # 大盤詳細
    st.markdown("### 📊 全球主要指數詳情")
    mkt_all = fetch_market_overview()
    if mkt_all:
        for row in mkt_all:
            chg = row["漲跌%"]
            icon = "▲" if chg>=0 else "▼"
            color = "#66cc66" if chg>=0 else "#ff6666"
            st.markdown(f"""
            <div style="background:#1e1e2e;border-radius:8px;padding:10px 16px;
                margin:4px 0;border-left:4px solid {color};display:flex;justify-content:space-between">
                <span style="color:#e2e8f0">{row['名稱']}</span>
                <span style="color:{color};font-weight:bold">{row['現值']} {icon} {abs(chg):.2f}%</span>
            </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# TAB 4：存股回測（DCA Backtester）
# ══════════════════════════════════════════════════════
with TABS[3]:
    st.markdown("### ⏳ 定期定額回測（DCA Backtester）")
    st.info("""
    💡 **定期定額（DCA）** 是什麼？
    每個月固定投入固定金額，不管股價高低都買，長期攤平成本的策略。
    本工具用真實歷史數據，模擬如果你過去N年每月定期定額，現在的結果如何。
    """)

    d1,d2,d3,d4 = st.columns(4)
    with d1: dca_sym = st.text_input("股票代號", placeholder="如 0050 或 SPY", key="dca_sym",
                                      help="建議用 ETF（如 0050、SPY）進行回測，波動較小")
    with d2: dca_amt = st.number_input("每月投入金額（元）",
                                        min_value=1000.0, max_value=1000000.0,
                                        value=10000.0, step=1000.0, key="dca_amt",
                                        help="每個月固定投入多少錢，建議設定在月收入的10~20%")
    with d3: dca_yr  = st.selectbox("回測年限", [3,5,10,15,20], index=1, key="dca_yr",
                                     format_func=lambda x: f"{x} 年",
                                     help="回測年限越長，數據越可靠。至少建議5年以上")
    with d4:
        st.write(""); st.write("")
        dca_btn = st.button("⏳ 開始回測", use_container_width=True, type="primary")

    if dca_btn and dca_sym.strip():
        dca_full = get_sym(dca_sym.strip(), market)
        with st.spinner(f"模擬 {dca_full} 過去 {dca_yr} 年定期定額..."):
            result = run_dca(dca_full, dca_amt, dca_yr)

        if result[0] is None:
            st.error(f"❌ 回測失敗：{result[1]}")
        else:
            df_dca, stats, _ = result

            st.markdown(f"### 📊 {dca_full} 定期定額回測結果（{dca_yr}年）")

            # 統計卡片
            stat_cols = st.columns(len(stats))
            colors_ = {"累積報酬率":"#66cc66" if "+" in str(stats.get("累積報酬率","")) else "#ff6666",
                       "年化報酬率":"#66cc66" if "+" in str(stats.get("年化報酬率","")) else "#ff6666"}
            for col, (k, v) in zip(stat_cols, stats.items()):
                col.metric(k, v)

            # 圖表
            fig_dca = build_dca_chart(df_dca, dca_full)
            st.plotly_chart(fig_dca, use_container_width=True)

            # 白話解讀
            final_v = df_dca["資產現值"].iloc[-1]
            total_i = df_dca["累積投入"].iloc[-1]
            profit  = final_v - total_i
            color_p = "#66cc66" if profit>=0 else "#ff6666"
            st.markdown(f"""
            <div style="background:#1e1e2e;border-radius:12px;padding:18px;margin:12px 0;border:1px solid #2a2a3e">
                <h4 style="color:#e2e8f0;margin:0">📖 白話解讀</h4>
                <p style="color:#94a3b8;margin:10px 0 0;line-height:1.8">
                    如果你從 <b>{dca_yr} 年前</b>開始，每個月固定投入 <b>{dca_amt:,.0f} 元</b> 到 {dca_full}，<br>
                    總共投入了 <b>{total_i:,.0f} 元</b>，今天你的資產現值是 <b>{final_v:,.0f} 元</b>，<br>
                    <span style="color:{color_p};font-weight:bold;font-size:1.1rem">
                        {'獲利' if profit>=0 else '虧損'} {abs(profit):,.0f} 元（{stats['累積報酬率']}）
                    </span><br><br>
                    最大回撤 <b>{stats['最大回撤 MDD']}</b>：代表在這段期間，你的資產最多曾經縮水這麼多。
                    這是衡量「最壞的情況」，用於評估你能不能承受這個心理壓力繼續持有。
                </p>
            </div>""", unsafe_allow_html=True)

            st.info("""
            **💡 定期定額的核心優點：**
            - 🕐 不需要猜測市場高低點，省去擇時煩惱
            - 📉 股價下跌時自動買到更多股數（攤平成本）
            - 🧠 克服情緒化交易，強迫儲蓄紀律
            - ⚠️ 回測結果為歷史模擬，不代表未來表現
            """)

# ══════════════════════════════════════════════════════
# 頁尾
# ══════════════════════════════════════════════════════
st.divider()
st.caption(
    "📈 股市小白分析系統 Pro ｜ "
    "AI即時搜尋 × 15項技術指標 × ATR明日沙盤 × 帳號雲端記憶 × DCA回測 ｜ "
    "⚠️ 本系統所有內容僅供學習與參考，不構成任何投資建議"
)