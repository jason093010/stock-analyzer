import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from google import genai
from google.genai import types as genai_types
import time
from datetime import datetime, date
import hashlib

# ═══════════════════════════════════════
# 頁面設定
# ═══════════════════════════════════════
st.set_page_config(
    page_title="股市小白分析系統 Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ═══════════════════════════════════════
# Supabase 初始化
# ═══════════════════════════════════════
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

# ═══════════════════════════════════════
# CSS
# ═══════════════════════════════════════
st.markdown("""
<style>
@media (max-width:768px){
    h1{font-size:1.1rem!important}
    h2{font-size:0.95rem!important}
    h3{font-size:0.85rem!important}
    .stButton>button{font-size:11px!important;padding:4px 6px!important}
}
.score-card{
    background:linear-gradient(135deg,#1e1e2e,#2a2a3e);
    border-radius:16px;padding:20px;text-align:center;
    border:1px solid #3a3a5e;margin-bottom:12px;
}
.big-score{font-size:3.5rem;font-weight:900;line-height:1.1}
.status-card{
    background:#1e1e2e;border-radius:12px;padding:16px;
    margin:8px 0;border-left:5px solid #7c3aed;
}
.entry-card{
    background:linear-gradient(135deg,#0d2b0d,#1a3a1a);
    border-radius:12px;padding:16px;margin:8px 0;
    border:1px solid #2a5a2a;
}
.stop-card{
    background:#2a0d0d;border-radius:12px;padding:16px;
    margin:8px 0;border:1px solid #5a1a1a;
}
.target-card{
    background:#0d1a2b;border-radius:12px;padding:16px;
    margin:8px 0;border:1px solid #1a3a5a;
}
.predict-card{
    background:linear-gradient(135deg,#1a0d2b,#2b1a3a);
    border-radius:14px;padding:20px;margin:12px 0;
    border:2px solid #6b2fba;
}
.news-card{
    background:#1e1e2e;border-radius:8px;padding:12px 16px;
    margin:6px 0;border-left:3px solid #42A5F5;
}
.market-card{
    background:#1e1e2e;border-radius:10px;padding:12px;
    text-align:center;border:1px solid #2a2a3e;
}
.recent-tag{
    display:inline-block;background:#2a2a3e;border-radius:20px;
    padding:3px 10px;margin:2px;font-size:12px;cursor:pointer;
    border:1px solid #3a3a5e;
}
.db-ok{color:#66ff66;font-size:11px}
.db-no{color:#ffaa00;font-size:11px}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════
_defaults = {
    "user_id": None, "username": None, "logged_in": False,
    "watchlist": [], "alerts": {}, "portfolio": {},
    "recent_searches": [], "quick_sym": "",
    "auto_analyze": False, "last_report_time": {},
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════════════════════
# 名詞解釋資料庫
# ═══════════════════════════════════════
GLOSSARY = {
    "多頭 📈": "市場看漲，大家都在買，股價往上走。\n就像牛用角往上頂，牛市=上漲市場。",
    "空頭 📉": "市場看跌，大家都在賣，股價往下走。\n就像熊用爪往下拍，熊市=下跌市場。",
    "超買 🔴": "股價漲太快太多，短期可能休息或回跌。\n就像人跑太快需要停下喘口氣。",
    "超賣 🟢": "股價跌太快太多，可能跌過頭，有機會反彈。\n就像橡皮筋拉太緊會彈回來。",
    "均線 MA": "把過去N天收盤價取平均畫成的線。\nMA5=5日 MA20=月線 MA60=季線\n股價在均線上方=強勢；在下方=弱勢。",
    "布林通道": "股價的「正常波動範圍」。\n上軌=過熱警戒 中軌=MA20 下軌=超賣警戒\n通道收窄=大行情即將來臨。",
    "RSI 強弱": "衡量漲跌力道，0~100。\n>70=超買（漲太快）<30=超賣（跌太多）50附近=多空平衡。",
    "Stochastic KD": "衡量現價在近期高低點中的位置。\nK>80=超買 K<20=超賣 KD黃金交叉=買訊。",
    "MACD 動能": "判斷動能加速或減速。\n柱狀圖由負轉正=動能轉強；由正轉負=動能轉弱。柱子越長力道越強。",
    "ATR 波幅": "每天平均波動多少金額。\nATR高=每天起伏大，風險高；ATR低=比較穩，適合新手。",
    "OBV 能量潮": "把成交量方向累計的指標。\nOBV上升=買氣強勁（資金流入）；OBV下降=賣壓沉重（資金流出）。",
    "Williams %R": "超買超賣確認指標。\n-20以上=超買（過熱）；-80以下=超賣（過冷）。",
    "VWAP": "成交量加權平均價，機構法人的重要參考基準。\n現價>VWAP=多方強勢；現價<VWAP=空方強勢。",
    "布林寬度": "布林通道的寬窄程度。越窄=越可能即將爆發大行情。",
    "費波那契": "根據黃金比例的支撐壓力參考位。\n0.382和0.618是最重要的關鍵位置，技術派常在此進出場。",
    "支撐": "股價跌到這裡會停下反彈，就像地板。",
    "壓力": "股價漲到這裡會遇到阻力，就像天花板。",
    "成交量": "今天買賣了幾張。\n量大+價漲=真漲；量小+價漲=假漲，不可靠；量大+價跌=有人出貨，要小心。",
    "本益比 PE": "花多少錢買1元獲利。PE=20代表20年回本，越低可能越便宜（需看產業平均）。",
    "股息殖利率": "每年配息÷股價。5%=每100元每年配5元，越高配息越豐厚。",
    "Beta 係數": "與大盤連動程度。Beta=1.5代表大盤漲1%它漲1.5%，跌的時候也更猛。",
    "ROE": "股東權益報酬率，公司用股東的錢賺了多少%，越高越好。",
    "停損": "當股價跌到某個價位就認賠賣出，保護本金最重要的工具。",
    "停利": "當股價漲到目標就獲利賣出，鎖住獲利不讓到手的錢飛走。",
    "風險報酬比": "預期獲利÷預期虧損。3:1=賺3元才冒1元風險，越高越划算，新手建議至少2:1以上。",
    "VIX 恐慌指數": "衡量市場恐慌程度。>30=市場非常恐慌（可能是抄底機會）；<15=市場過於樂觀（要小心）。",
    "聯準會 Fed": "美國的中央銀行，控制利率。升息=壓制股市；降息=刺激股市。",
}

# ═══════════════════════════════════════
# 熱門股清單
# ═══════════════════════════════════════
TW_HOT = {
    "科技": [("2330","台積電"),("2454","聯發科"),("2303","聯電"),("3711","日月光")],
    "ETF":  [("0050","台灣50"),("0056","高股息"),("00878","永續高息"),("00929","科技優息")],
    "金融": [("2882","國泰金"),("2881","富邦金"),("2891","中信金"),("2884","玉山金")],
    "傳產": [("1301","台塑"),("2002","中鋼"),("2412","中華電"),("1216","統一")],
}
US_HOT = {
    "科技": [("AAPL","蘋果"),("MSFT","微軟"),("NVDA","輝達"),("GOOGL","Google")],
    "AI":   [("AMD","超微"),("TSM","台積電ADR"),("SMCI","超微電腦"),("PLTR","Palantir")],
    "ETF":  [("SPY","S&P500"),("QQQ","那斯達克"),("VT","全球"),("ARKK","方舟")],
    "其他": [("TSLA","特斯拉"),("AMZN","亞馬遜"),("META","Meta"),("NFLX","Netflix")],
}

# ═══════════════════════════════════════
# 資料庫函數（Supabase）
# ═══════════════════════════════════════
def make_uid(username: str, pin: str) -> str:
    return hashlib.sha256(f"{username.lower().strip()}:{pin}".encode()).hexdigest()[:20]

def db_verify_user(username: str, pin: str) -> tuple:
    """驗證帳號密碼，回傳 (success, uid)"""
    if not HAS_DB:
        uid = make_uid(username, pin)
        return True, uid
    try:
        uid = make_uid(username, pin)
        r = _supabase.table("users").select("id").eq("username", username.lower().strip()).eq("password_hash", uid).execute()
        if r.data:
            return True, uid
        return False, None
    except:
        return False, None

def db_create_user(username: str, pin: str) -> tuple:
    """建立新帳號，回傳 (success, uid, message)"""
    if not HAS_DB:
        uid = make_uid(username, pin)
        return True, uid, "本機模式，重新整理後消失"
    try:
        uid = make_uid(username, pin)
        ex = _supabase.table("users").select("id").eq("username", username.lower().strip()).execute()
        if ex.data:
            return False, None, "帳號名稱已存在，請換一個"
        _supabase.table("users").insert({"username": username.lower().strip(), "password_hash": uid}).execute()
        return True, uid, "帳號建立成功！"
    except Exception as e:
        return False, None, f"建立失敗：{str(e)[:50]}"

def db_load_watchlist(uid: str) -> list:
    if not HAS_DB: return []
    try:
        r = _supabase.table("watchlists").select("symbol").eq("user_id", uid).execute()
        return [x["symbol"] for x in r.data]
    except: return []

def db_add_watch(uid: str, sym: str):
    if not HAS_DB: return
    try:
        ex = _supabase.table("watchlists").select("id").eq("user_id", uid).eq("symbol", sym).execute()
        if not ex.data:
            _supabase.table("watchlists").insert({"user_id": uid, "symbol": sym}).execute()
    except: pass

def db_del_watch(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("watchlists").delete().eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

def db_load_alerts(uid: str) -> dict:
    if not HAS_DB: return {}
    try:
        r = _supabase.table("alerts").select("*").eq("user_id", uid).execute()
        return {x["symbol"]: {"above": x.get("above_price"), "below": x.get("below_price")} for x in r.data}
    except: return {}

def db_save_alert(uid: str, sym: str, above, below):
    if not HAS_DB: return
    try:
        ex = _supabase.table("alerts").select("id").eq("user_id", uid).eq("symbol", sym).execute()
        d = {"user_id": uid, "symbol": sym, "above_price": above or None, "below_price": below or None}
        if ex.data: _supabase.table("alerts").update(d).eq("user_id", uid).eq("symbol", sym).execute()
        else: _supabase.table("alerts").insert(d).execute()
    except: pass

def db_del_alert(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("alerts").delete().eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

def db_load_portfolio(uid: str) -> dict:
    if not HAS_DB: return {}
    try:
        r = _supabase.table("portfolio").select("*").eq("user_id", uid).execute()
        return {
            x["symbol"]: {
                "cost": x["cost_price"], "shares": x["shares"],
                "note": x.get("note",""), "buy_date": x.get("buy_date","")
            } for x in r.data
        }
    except: return {}

def db_save_portfolio(uid: str, sym: str, cost: float, shares: float, note: str="", buy_date: str=""):
    if not HAS_DB: return
    try:
        ex = _supabase.table("portfolio").select("id").eq("user_id", uid).eq("symbol", sym).execute()
        d = {"user_id": uid, "symbol": sym, "cost_price": cost, "shares": shares, "note": note, "buy_date": buy_date}
        if ex.data: _supabase.table("portfolio").update(d).eq("user_id", uid).eq("symbol", sym).execute()
        else: _supabase.table("portfolio").insert(d).execute()
    except: pass

def db_del_portfolio(uid: str, sym: str):
    if not HAS_DB: return
    try: _supabase.table("portfolio").delete().eq("user_id", uid).eq("symbol", sym).execute()
    except: pass

# ═══════════════════════════════════════
# 輔助函數
# ═══════════════════════════════════════
def get_sym(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"):
        return raw + ".TW"
    return raw

def add_recent(sym: str):
    r = st.session_state.recent_searches
    if sym in r: r.remove(sym)
    r.insert(0, sym)
    st.session_state.recent_searches = r[:8]

def safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if not (v != v) else default  # NaN check
    except: return default

# ═══════════════════════════════════════
# 數據抓取（5分鐘快取）
# ═══════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data(symbol: str, period: str):
    for i in range(3):
        try:
            t = yf.Ticker(symbol)
            h = t.history(period=period)
            info = t.info
            if h.empty:
                return None, None, "查無此代號，請確認是否正確"
            return h, info, None
        except Exception as e:
            if i == 2: return None, None, f"抓取失敗：{str(e)[:60]}"
            time.sleep(1)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_overview():
    """抓取大盤概況"""
    indices = {
        "台灣加權": "^TWII", "美國S&P500": "^GSPC",
        "那斯達克": "^IXIC", "恐慌指數VIX": "^VIX",
    }
    rows = []
    for name, sym in indices.items():
        try:
            h = yf.Ticker(sym).history(period="2d")
            if not h.empty and len(h) >= 2:
                p   = safe_float(h["Close"].iloc[-1])
                chg = safe_float((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100)
                rows.append({"名稱": name, "現值": round(p,2), "漲跌": f"{'+' if chg>=0 else ''}{chg:.2f}%", "_chg": chg})
        except: pass
    return rows

# ═══════════════════════════════════════
# 技術指標計算（15項 + NaN防護）
# ═══════════════════════════════════════
def calc_indicators(hist: pd.DataFrame) -> dict:
    c = hist["Close"].squeeze().astype(float)
    h = hist["High"].squeeze().astype(float)
    l = hist["Low"].squeeze().astype(float)
    v = hist["Volume"].squeeze().astype(float)
    n = len(c)

    def _last(s):
        try:
            val = float(s.iloc[-1])
            return val if val == val else 0.0  # NaN check
        except: return 0.0

    # 均線
    ma5  = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(min(60, n)).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()

    # MACD
    macd     = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    macd_h   = macd - macd_sig

    # RSI（NaN防護）
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    loss_safe = loss.replace(0, 1e-10)
    rsi   = 100 - (100 / (1 + gain / loss_safe))
    rsi   = rsi.clip(0, 100)

    # Stochastic RSI（NaN防護）
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    rsi_range = (rsi_max - rsi_min).replace(0, 1e-10)
    stoch_k = (100 * (rsi - rsi_min) / rsi_range).clip(0, 100)
    stoch_d = stoch_k.rolling(3).mean()

    # Bollinger Bands
    bb_mid   = c.rolling(20).mean()
    bb_std   = c.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_range = (bb_upper - bb_lower).replace(0, 1e-10)
    bb_width = ((bb_upper - bb_lower) / bb_mid.replace(0, 1e-10) * 100)
    bb_pct   = ((c - bb_lower) / bb_range * 100).clip(0, 100)

    # ATR（NaN防護）
    prev_c = c.shift(1)
    tr = pd.concat([
        (h - l),
        (h - prev_c).abs(),
        (l - prev_c).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # OBV
    direction = (c.diff() > 0).astype(float) * 2 - 1
    direction.iloc[0] = 0
    obv = (v * direction).fillna(0).cumsum()

    # Williams %R
    hh = h.rolling(14).max()
    ll = l.rolling(14).min()
    hl_range = (hh - ll).replace(0, 1e-10)
    wr = (-100 * (hh - c) / hl_range).clip(-100, 0)

    # VWAP（20日近似）
    tp   = (h + l + c) / 3
    vwap_num = (tp * v).rolling(20).sum()
    vwap_den = v.rolling(20).sum().replace(0, 1e-10)
    vwap = vwap_num / vwap_den

    # 安全取得最後值
    price   = round(_last(c), 2)
    prev    = safe_float(c.iloc[-2]) if n >= 2 else price
    prev5   = safe_float(c.iloc[-6]) if n >= 6 else price
    prev21  = safe_float(c.iloc[-21]) if n >= 21 else price
    atr_val = round(_last(atr), 4)
    if atr_val == 0: atr_val = round(price * 0.02, 2)  # fallback: 2% of price

    ind = {
        "price":       price,
        "change_pct":  round((price - prev) / max(prev, 0.01) * 100, 2),
        "change_5d":   round((price - prev5) / max(prev5, 0.01) * 100, 2),
        "change_1m":   round((price - prev21) / max(prev21, 0.01) * 100, 2),
        "ma5":         round(_last(ma5), 2),
        "ma10":        round(_last(ma10), 2),
        "ma20":        round(_last(ma20), 2),
        "ma60":        round(_last(ma60), 2),
        "vwap":        round(_last(vwap), 2),
        "rsi":         round(_last(rsi), 1),
        "stoch_k":     round(_last(stoch_k), 1),
        "stoch_d":     round(_last(stoch_d), 1),
        "macd":        round(_last(macd), 4),
        "macd_sig":    round(_last(macd_sig), 4),
        "macd_hist":   round(_last(macd_h), 4),
        "williams_r":  round(_last(wr), 1),
        "atr":         atr_val,
        "bb_upper":    round(_last(bb_upper), 2),
        "bb_mid":      round(_last(bb_mid), 2),
        "bb_lower":    round(_last(bb_lower), 2),
        "bb_width":    round(_last(bb_width), 1),
        "bb_pct":      round(_last(bb_pct), 1),
        "volume":      int(_last(v)),
        "vol_ma20":    int(_last(v.rolling(20).mean())),
        "obv":         round(_last(obv), 0),
        "high_52w":    round(float(c.rolling(min(252,n)).max().iloc[-1]), 2),
        "low_52w":     round(float(c.rolling(min(252,n)).min().iloc[-1]), 2),
        "_c": c, "_h": h, "_l": l, "_v": v,
        "_rsi": rsi, "_stoch_k": stoch_k, "_stoch_d": stoch_d,
        "_macd": macd, "_macd_sig": macd_sig, "_macd_hist": macd_h,
        "_bb_upper": bb_upper, "_bb_lower": bb_lower, "_bb_mid": bb_mid,
        "_ma5": ma5, "_ma20": ma20, "_ma60": ma60, "_obv": obv,
    }

    # 量比說明
    vm20 = ind["vol_ma20"] if ind["vol_ma20"] > 0 else 1
    vr = round(ind["volume"] / vm20, 2)
    ind["vol_ratio"] = vr
    if vr >= 2.5:   ind["vol_desc"] = f"🔥 超級爆量（{vr:.1f}倍均量），市場極度關注"
    elif vr >= 1.5: ind["vol_desc"] = f"📢 明顯放量（{vr:.1f}倍），市場積極參與"
    elif vr >= 0.8: ind["vol_desc"] = f"📊 量能正常（{vr:.1f}倍），市場熱度穩定"
    else:           ind["vol_desc"] = f"😴 成交縮量（{vr:.1f}倍），交投清淡，訊號可信度低"

    # 52週位置
    pr52 = ind["high_52w"] - ind["low_52w"]
    pos = (price - ind["low_52w"]) / max(pr52, 0.01) * 100
    ind["position_52w"] = round(pos, 1)
    if pos >= 90:   ind["position_desc"] = f"接近52週高點（{pos:.0f}%），漲幅已大，需謹慎"
    elif pos >= 70: ind["position_desc"] = f"52週相對高位（{pos:.0f}%），仍有壓力"
    elif pos <= 10: ind["position_desc"] = f"接近52週低點（{pos:.0f}%），相對便宜但需確認趨勢"
    elif pos <= 30: ind["position_desc"] = f"52週相對低位（{pos:.0f}%），有撿便宜機會"
    else:           ind["position_desc"] = f"52週中間區域（{pos:.0f}%），位置相對中性"

    # RSI說明
    r = ind["rsi"]
    if r >= 80:   ind["rsi_desc"] = f"⚠️ RSI {r}，嚴重超買，短線風險極高"
    elif r >= 70: ind["rsi_desc"] = f"⚠️ RSI {r}，超買區，留意回調"
    elif r <= 20: ind["rsi_desc"] = f"💡 RSI {r}，嚴重超賣，留意強力反彈"
    elif r <= 30: ind["rsi_desc"] = f"💡 RSI {r}，超賣區，有反彈機會"
    elif r >= 55: ind["rsi_desc"] = f"✅ RSI {r}，多方偏強"
    elif r <= 45: ind["rsi_desc"] = f"⚠️ RSI {r}，空方偏強"
    else:         ind["rsi_desc"] = f"➡️ RSI {r}，多空均衡"

    # 技術狀態（三重確認）
    r_val = ind["rsi"]; k_val = ind["stoch_k"]; m_val = ind["macd_hist"]
    if ind["ma5"] > ind["ma20"] > ind["ma60"] and r_val > 55 and m_val > 0:
        ind["status"] = "強勢多頭 📈"; ind["sc"] = "🟢"
        ind["status_desc"] = "均線多頭排列＋RSI偏強＋MACD正值，三重確認多頭格局。"
    elif ind["ma5"] < ind["ma20"] < ind["ma60"] and r_val < 45 and m_val < 0:
        ind["status"] = "強勢空頭 📉"; ind["sc"] = "🔴"
        ind["status_desc"] = "均線空頭排列＋RSI偏弱＋MACD負值，三重確認空頭格局。"
    elif r_val <= 30 and k_val < 20:
        ind["status"] = "雙重超賣，留意反彈 🟡"; ind["sc"] = "🟡"
        ind["status_desc"] = "RSI與Stochastic雙雙超賣，反彈機率升高，但需量能確認。"
    elif r_val >= 70 and k_val > 80:
        ind["status"] = "雙重超買，注意回調 🟡"; ind["sc"] = "🟡"
        ind["status_desc"] = "RSI與Stochastic雙雙超買，短線獲利了結壓力大。"
    elif abs(ind["ma5"] - ind["ma20"]) / max(price, 0.01) < 0.015:
        ind["status"] = "均線糾結蓄勢 ⚪"; ind["sc"] = "⚪"
        ind["status_desc"] = "均線纏繞，多空拉鋸，等待突破方向，大行情可能即將爆發。"
    elif ind["ma5"] > ind["ma20"] and r_val > 50:
        ind["status"] = "短線偏多 🔵"; ind["sc"] = "🔵"
        ind["status_desc"] = "短均線在長均線上方，RSI偏強，短線多方略佔優勢。"
    else:
        ind["status"] = "弱勢盤整 🟠"; ind["sc"] = "🟠"
        ind["status_desc"] = "股價走勢疲軟，方向不明，建議觀望等待明確訊號。"

    return ind

# ═══════════════════════════════════════
# 綜合評分（0-100）
# ═══════════════════════════════════════
def calc_score(ind: dict, info: dict) -> dict:
    # 趨勢（30分）
    trend = 0
    if ind["ma5"] > ind["ma20"]:  trend += 8
    if ind["ma20"] > ind["ma60"]: trend += 8
    if ind["price"] > ind["ma20"]: trend += 7
    if ind["macd_hist"] > 0:      trend += 7
    trend = min(30, trend)

    # 動能（25分）
    mom = 0
    r = ind["rsi"]; k = ind["stoch_k"]; wr = ind["williams_r"]
    if 50 <= r <= 70:   mom += 10
    elif 40 <= r < 50:  mom += 5
    elif r < 30:        mom += 8
    elif r > 70:        mom += 3
    if 40 <= k <= 80:   mom += 8
    elif k < 20:        mom += 5
    if wr > -50:        mom += 7
    mom = min(25, mom)

    # 量能（20分）
    vr = ind["vol_ratio"]
    if vr >= 1.5 and ind["change_pct"] > 0: vol = 20
    elif vr >= 1.2 and ind["change_pct"] > 0: vol = 15
    elif 0.8 <= vr <= 1.5: vol = 10
    else: vol = 5
    vol = min(20, vol)

    # 位置（15分）
    pos = ind["position_52w"]
    if 30 <= pos <= 70:             psc = 15
    elif 20 <= pos < 30 or 70 < pos <= 80: psc = 10
    elif pos < 20:                  psc = 12
    else:                           psc = 4
    psc = min(15, psc)

    # 布林（10分）
    bp = ind["bb_pct"]
    if 20 <= bp <= 80: bsc = 10
    elif bp < 20:      bsc = 7
    else:              bsc = 3
    bsc = min(10, bsc)

    total = trend + mom + vol + psc + bsc
    if total >= 80:   grade, gc = "A（優秀）", "#00cc66"
    elif total >= 65: grade, gc = "B（良好）", "#66cc00"
    elif total >= 50: grade, gc = "C（普通）", "#ffaa00"
    elif total >= 35: grade, gc = "D（偏弱）", "#ff6600"
    else:             grade, gc = "E（警示）", "#ff3333"

    return {"total": total, "grade": grade, "gc": gc,
            "trend": trend, "mom": mom, "vol": vol, "pos": psc, "bb": bsc}

# ═══════════════════════════════════════
# 入場策略計算
# ═══════════════════════════════════════
def calc_entry(ind: dict, hist: pd.DataFrame) -> dict:
    c = ind["_c"]; h = ind["_h"]; l = ind["_l"]
    price = ind["price"]; atr = max(ind["atr"], price * 0.005)
    n = len(c)
    w = min(60, n)

    ph = round(float(h.iloc[-w:].max()), 2)
    pl = round(float(l.iloc[-w:].min()), 2)
    fr = max(ph - pl, atr)

    fibs = {
        "0.236": round(ph - 0.236 * fr, 2),
        "0.382": round(ph - 0.382 * fr, 2),
        "0.500": round(ph - 0.500 * fr, 2),
        "0.618": round(ph - 0.618 * fr, 2),
        "0.786": round(ph - 0.786 * fr, 2),
    }

    sup1 = round(float(l.iloc[-20:].min()), 2)
    sup2 = round(float(l.iloc[-w:].min()), 2)
    res1 = round(float(h.iloc[-20:].max()), 2)
    res2 = round(float(h.iloc[-w:].max()), 2)

    con_buy = round(min(sup1, fibs["0.382"]), 2)
    mod_buy = round((sup1 + ind["ma20"]) / 2, 2)
    agg_buy = round(price * 0.995, 2)

    sl_tight  = round(price - 1.5 * atr, 2)
    sl_normal = round(price - 2.5 * atr, 2)
    sl_wide   = round(max(sup2 * 0.97, price - 4 * atr), 2)

    tp1 = round(price + 2 * atr, 2)
    tp2 = round(price + 4 * atr, 2)
    tp3 = round(max(res2 * 1.02, price + 6 * atr), 2)

    rr_denom = max(mod_buy - sl_normal, 0.01)
    rr = round((tp1 - mod_buy) / rr_denom, 2)

    # 台股一張換算
    lot_cost = round(mod_buy * 1000, 0)

    return {
        "fibs": fibs, "sup1": sup1, "sup2": sup2, "res1": res1, "res2": res2,
        "con_buy": con_buy, "mod_buy": mod_buy, "agg_buy": agg_buy,
        "sl_tight": sl_tight, "sl_normal": sl_normal, "sl_wide": sl_wide,
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "rr": rr,
        "ph": ph, "pl": pl, "lot_cost": lot_cost, "atr": atr,
    }

# ═══════════════════════════════════════
# Gemini AI（含即時搜尋，自動切換模型）
# ═══════════════════════════════════════
def call_ai(api_key: str, prompt: str, use_search: bool = False) -> str:
    client = genai.Client(api_key=api_key)
    models = [
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash（備用）"),
        ("gemini-2.0-flash-lite", "Gemini Flash Lite（備用）"),
    ]
    last_err = None
    for mid, mname in models:
        try:
            if use_search:
                cfg = genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.3,
                )
                resp = client.models.generate_content(model=mid, contents=prompt, config=cfg)
            else:
                resp = client.models.generate_content(model=mid, contents=prompt)
            tag = " ＋🔍即時搜尋" if use_search else ""
            return f"> 🤖 {mname}{tag} ｜ 報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{resp.text}"
        except Exception as e:
            err = str(e)
            if any(k in err for k in ["quota", "429", "RESOURCE_EXHAUSTED", "404", "not found"]):
                last_err = err[:80]; continue
            raise
    raise Exception(f"所有模型均無法使用：{last_err}")

# ═══════════════════════════════════════
# AI 完整分析報告（含明日沙盤推演）
# ═══════════════════════════════════════
def ai_full_report(ind: dict, info: dict, sym: str, api_key: str, entry: dict, score: dict) -> str:
    co   = info.get("longName") or info.get("shortName") or sym
    sec  = info.get("sector", "未知")
    pe   = info.get("trailingPE", "N/A")
    fpe  = info.get("forwardPE", "N/A")
    pb   = info.get("priceToBook", "N/A")
    eps  = info.get("trailingEps", "N/A")
    dy   = info.get("dividendYield", 0)
    if isinstance(dy, float): dy = f"{dy*100:.1f}%"
    beta = info.get("beta", "N/A")
    tp_  = info.get("targetMeanPrice", "N/A")
    rec  = info.get("recommendationKey", "N/A")
    mc   = info.get("marketCap", "N/A")
    if isinstance(mc, (int, float)):
        mc = f"約{mc/1e8:.0f}億" if mc > 1e8 else f"{mc:,.0f}"
    roe  = info.get("returnOnEquity", "N/A")
    gm   = info.get("grossMargins", "N/A")
    pm   = info.get("profitMargins", "N/A")
    rg   = info.get("revenueGrowth", "N/A")
    eg   = info.get("earningsGrowth", "N/A")
    de   = info.get("debtToEquity", "N/A")

    # ATR價格區間（明日預測用）
    atr  = entry["atr"]
    bull_hi = round(ind["price"] + 1.5 * atr, 2)
    bull_lo = round(ind["price"] - 0.5 * atr, 2)
    bear_hi = round(ind["price"] + 0.5 * atr, 2)
    bear_lo = round(ind["price"] - 1.5 * atr, 2)
    neut_hi = round(ind["price"] + 1.0 * atr, 2)
    neut_lo = round(ind["price"] - 1.0 * atr, 2)
    max_up  = round(ind["price"] + 3.0 * atr, 2)
    max_dn  = round(ind["price"] - 3.0 * atr, 2)

    prompt = f"""你是一位同時精通技術分析、基本面、籌碼面、宏觀經濟與市場心理學的頂級金融分析師，同時也是最擅長用白話文教導股市新手的老師。

你的分析步驟（必須按順序執行）：
1. 即時搜尋「{co}（{sym}）」過去7天的最新新聞、公司公告、法人評級
2. 搜尋今日宏觀數據：聯準會（Fed）最新動態、美元指數（DXY）、VIX恐慌指數、10年期美債殖利率、原油、黃金
3. 搜尋川普最新政策聲明、地緣政治風險（台海、俄烏、中東）
4. 搜尋{sec}產業最新動態、供應鏈消息、競爭對手重大事件
5. 搜尋今晚至明日預定公布的重要經濟數據（CPI、非農、FOMC等）
6. 搜尋社群媒體（Reddit、PTT、社群討論）對此股的最新情緒與討論
7. 整合所有量化指標與質化情報，進行客觀嚴謹分析

══════════ 基本資料 ══════════
公司：{co}（{sym}）| 產業：{sec} | 市值：{mc}
PE：{pe} | 預估PE：{fpe} | PB：{pb} | EPS：{eps}
股息率：{dy} | ROE：{roe} | 毛利率：{gm} | 淨利率：{pm}
營收成長：{rg} | 獲利成長：{eg} | 負債權益比：{de}
Beta：{beta} | 分析師目標價：{tp_} | 評級：{rec}

══════════ 15項技術指標 ══════════
現價：{ind['price']} | 今日：{ind['change_pct']}% | 5日：{ind['change_5d']}% | 月：{ind['change_1m']}%
均線：MA5={ind['ma5']} MA20={ind['ma20']} MA60={ind['ma60']} VWAP={ind['vwap']}
RSI={ind['rsi']} | Stoch K={ind['stoch_k']} D={ind['stoch_d']} | Williams%R={ind['williams_r']}
MACD={ind['macd']} | Signal={ind['macd_sig']} | Histogram={ind['macd_hist']}
布林：上={ind['bb_upper']} 中={ind['bb_mid']} 下={ind['bb_lower']} | 位置={ind['bb_pct']:.0f}% | 寬度={ind['bb_width']}%
ATR(14)={atr} | OBV={'上升（買氣增強）' if ind['obv']>0 else '下降（賣壓增加）'}
52週：高={ind['high_52w']} 低={ind['low_52w']} 位置={ind['position_52w']}%
{ind['vol_desc']} | 狀態：{ind['status']}

══════════ 入場策略數據 ══════════
近期高={entry['ph']} 近期低={entry['pl']}
支撐1={entry['sup1']} 支撐2={entry['sup2']}
壓力1={entry['res1']} 壓力2={entry['res2']}
Fib 0.382={entry['fibs']['0.382']} | 0.618={entry['fibs']['0.618']}
參考買入：保守={entry['con_buy']} 穩健={entry['mod_buy']} 積極={entry['agg_buy']}
停損：緊={entry['sl_tight']} 標準={entry['sl_normal']} 寬={entry['sl_wide']}
目標：T1={entry['tp1']} T2={entry['tp2']} T3={entry['tp3']}
風報比={entry['rr']}:1

══════════ 綜合評分 ══════════
{score['total']}/100（{score['grade']}）
趨勢{score['trend']}/30 | 動能{score['mom']}/25 | 量能{score['vol']}/20 | 位置{score['pos']}/15 | 布林{score['bb']}/10

══════════ ATR明日波動預算 ══════════
ATR={atr} | 現價={ind['price']}
樂觀情境區間：{bull_lo} ～ {bull_hi}
悲觀情境區間：{bear_lo} ～ {bear_hi}
中性情境區間：{neut_lo} ～ {neut_hi}
3倍ATR上限（重大消息才可能突破）：{max_dn} ～ {max_up}

════════════════════════════
請完成即時搜尋後，用繁體中文輸出以下完整報告：
════════════════════════════

## 🌍 宏觀環境即時掃描
（說明今日總體經濟狀況：聯準會最新動態與市場對利率的預期、美元強弱、VIX恐慌指數現況、美債殖利率走向、川普最新政策、地緣政治風險。重點：這些因素對「{co}」的影響強度是強/中/弱，為什麼？）

## 📰 公司與產業最新情報（過去7天）
（搜尋並整理最重要的3~5則消息，每則標注：正面✅/負面❌/中立➡️。包含：財報數據、法人評級調整、產業供需變化、競爭對手動態、公司重大公告、社群討論熱度）

## 🏢 公司白話介紹
（這家公司是做什麼的？在產業鏈中的位置？主要客戶與競爭對手？護城河在哪裡？用新手也能理解的語言說明，包含1~2個生活化類比）

## 📊 15項技術指標完整解讀

**【趨勢系統】均線排列：**（MA5/MA20/MA60多空排列、VWAP位置、是否形成黃金/死亡交叉？）

**【動能系統】RSI + Stochastic + Williams%R：**（三指標是否共振？數值說明各在哪個區域、代表什麼）

**【趨勢動能】MACD：**（Histogram擴大/收縮、是否交叉、動能加速/減速）

**【波動系統】布林通道 + ATR：**（現價在布林{ind['bb_pct']:.0f}%位置意味著什麼？ATR={atr}代表每天正常波動多少錢？布林寬度{ind['bb_width']}%是收窄還是擴張？）

**【資金系統】OBV + 量能：**（OBV方向代表資金流向、今日量比{ind['vol_ratio']}x的量價配合度如何？）

## 💰 入場策略詳解（僅供參考，不構成投資建議）

**買入區（為什麼這些價位值得關注）：**
- 保守型 {entry['con_buy']}：（技術支撐邏輯）
- 穩健型 {entry['mod_buy']}：（技術依據與適合對象）
- 積極型 {entry['agg_buy']}：（適合哪種投資者）
- 台股一張參考成本：約 {entry['lot_cost']:,.0f} 元（穩健型 × 1000股）

**停損設定（一定要設，這是保護本金的安全帶）：**
- 緊 {entry['sl_tight']}（短線用，1.5倍ATR）
- 標準 {entry['sl_normal']}（一般投資者，2.5倍ATR）
- 寬 {entry['sl_wide']}（長線用，以主要支撐為基準）

**目標價位（每個目標的背後邏輯）：**
- T1 {entry['tp1']}（2倍ATR，短線合理）
- T2 {entry['tp2']}（4倍ATR，中線目標）
- T3 {entry['tp3']}（近期高點壓力位）

**風報比 {entry['rr']}:1 白話說明：**（這個數字好還是不好？新手應追求多少以上？）

**倉位建議：**（根據評分{score['total']}分，建議新手投入多少%資金？分批買入的邏輯？）

## 🔮 明日走勢沙盤推演與精準預測

> 本預測嚴格基於ATR波動率進行量化約束，並深度融合即時搜尋到的質化情報。
> ⚠️ 預測範圍：最大不超過3倍ATR（即 {max_dn}～{max_up}），除非有重大突發消息。

**📌 預期方向：**
（明確說明：偏多上攻 / 偏空回測 / 區間震盪
必須回答：「技術面訊號」與「最新新聞/市場情緒」是共振還是分歧？
- 若共振：方向訊號可信度提升，說明兩者如何共同指向同一方向
- 若分歧：哪個因素權重更高？最終傾向哪個方向？原因是什麼？
- 明確說明多空力道的相對強弱）

**📐 預估合理震幅（嚴格基於ATR={atr}計算）：**
- 🟢 樂觀情境（多方主導）：預估明日最高可測試 {bull_hi}，最低守在 {bull_lo}
  （說明：多方需具備什麼條件才能達到此目標？對應壓力位{entry['res1']}的關係）
- 🔴 悲觀情境（空方主導）：預估明日最低可測試 {bear_lo}，最高壓在 {bear_hi}
  （說明：跌破哪個關鍵位後悲觀情境成立？對應支撐位{entry['sup1']}的關係）
- ⚪ 中性情境（區間整理）：預估明日在 {neut_lo} ～ {neut_hi} 之間震盪
  （說明：什麼樣的盤面特徵代表是中性整理？如何判斷正在整理而非要噴出？）
- 最可能發生的情境是哪一個？理由是什麼？（結合技術面＋即時新聞情緒給出判斷）

**⚔️ 關鍵多空交戰點：**
- 🛡️ 多方必守支撐：___ 
  （這個價位的市場心理：為什麼守住多方才有機會？跌破意味著什麼？短線投資人心態如何？）
- 🚀 空方必破壓力：___
  （帶量突破此價位，多方攻勢才能確立，需要多大的量能配合？突破後下一個壓力在哪？）
- ⚡ 明日盤中最關鍵的1~2個觀察指標：（具體告訴新手盯著看哪個指標或價位，出現什麼訊號代表方向確立）

**🌀 潛在變數與催化劑（今晚至明日盤中）：**
（請搜尋並具體列出以下變數）
- 📅 今晚/明日預定公布的重要經濟數據（CPI、PCE、非農、FOMC等，說明公布時間與預期影響）
- 📢 {co}是否即將財報/法說會/重大公告？（如有，說明市場預期與可能的方向）
- 🌐 地緣政治或政策黑天鵝（川普推文風險、選舉、地區衝突升級等）
- 💹 聯動市場監測：費城半導體指數、台指期、美元/台幣匯率、相關ETF走勢
- 😱 最可能讓預測完全失效的黑天鵝：___（說明機率高低與可能的衝擊幅度）

**🎯 預測信心等級：**
（請給出1~5分，並說明為什麼是這個信心等級：技術面明確程度 + 新聞面清晰度 + 宏觀環境穩定性 = 最終信心評估）

## 🎯 短中期走勢研判
- 短期（1~2週）：（技術面+最新新聞，說明具體理由與關鍵觀察點）
- 中期（1~3月）：（基本面+產業趨勢+宏觀環境，說明主要驅動力）

## ⚠️ 主要風險清單（條列5點，技術+基本面+新聞面各角度覆蓋）

## 📌 小白總結
（用最口語的方式說：這支股票現在值不值得花時間研究？評分{score['total']}/100代表什麼感覺？現在是好的觀察時機嗎？用一個生活化的比喻來形容目前這支股票的狀態）

## 📖 術語速查對照表
（整理本報告所有專業術語，格式：**術語** ｜ 白話解釋，每行一個）

════════════════════════════
嚴格遵守規則：
✅ 所有術語第一次出現必須加括號白話解釋
✅ 明日預測必須基於ATR={atr}，不得超過3倍ATR（除非有重大消息催化劑）
✅ 必須明確區分哪些來自技術指標、哪些來自即時搜尋新聞
✅ 入場建議每次都需加「僅供參考，不構成投資建議」
✅ 必須搜尋今晚預定公布的經濟數據
❌ 禁止使用「一定」「保證」「必漲」「必跌」「穩賺」
❌ 禁止無數據支撐的確定性預測
❌ 禁止給出超過3倍ATR的明日價格預測
════════════════════════════"""

    return call_ai(api_key, prompt, use_search=True)

def ai_news_report(company: str, sym: str, sector: str, api_key: str) -> str:
    prompt = f"""請即時搜尋所有與「{company}（{sym}）」相關的最新資訊。

必須搜尋：
1. {company} 過去2週最新新聞與公告
2. {sector}產業最新動態與供應鏈消息
3. 宏觀政策：聯準會、各國央行、貿易政策、川普最新動態
4. 地緣政治：台海、俄烏、中東等風險事件
5. 競爭對手最新動態與比較
6. 分析師最新評級、目標價調整
7. 社群媒體討論情緒（Reddit/PTT/社群）

用繁體中文輸出：

## 🌍 宏觀環境（對此股的直接影響）
（聯準會、川普、各國央行、匯率、貿易等）

## 📰 公司最新重要消息（每則標注 ✅正面/❌負面/➡️中立）
## 🏭 產業鏈與競爭動態
## 💬 分析師觀點與市場情緒
## ⚡ 潛在黑天鵝風險

## 🎯 新聞面綜合評估
（整體正面/負面/中立？影響力強/中/弱？信心水準：高/中/低）

## ⚠️ 新手看新聞常犯的4個錯誤
（看到這些新聞，新手容易有什麼衝動？正確應對方式？）

禁止使用「一定」「保證」「必漲」「必跌」。"""
    return call_ai(api_key, prompt, use_search=True)

def ai_compare(sym1, n1, sc1, ind1, en1, sym2, n2, sc2, ind2, en2, api_key) -> str:
    prompt = f"""請即時搜尋兩支股票的最新動態，然後客觀比較，用白話文告訴股市新手哪支更值得關注。

股票A：{n1}（{sym1}）
評分：{sc1['total']}/100 | 狀態：{ind1['status']} | RSI：{ind1['rsi']}
月漲跌：{ind1['change_1m']}% | 量比：{ind1['vol_ratio']}x
穩健買入：{en1['mod_buy']} | 停損：{en1['sl_normal']} | 風報比：{en1['rr']}:1

股票B：{n2}（{sym2}）
評分：{sc2['total']}/100 | 狀態：{ind2['status']} | RSI：{ind2['rsi']}
月漲跌：{ind2['change_1m']}% | 量比：{ind2['vol_ratio']}x
穩健買入：{en2['mod_buy']} | 停損：{en2['sl_normal']} | 風報比：{en2['rr']}:1

搜尋兩支股票最新動態後，用繁體中文輸出：

## ⚖️ 技術面比較（哪支技術指標更強？為什麼？）
## 🌐 最新動態比較（各自發生了什麼大事？）
## 💰 基本面比較（哪支基本面更紮實？）
## 🏆 綜合比較結論（量化評分 + 質化分析）
## 🎯 新手建議（只能選一支的話，更值得關注的是哪支？說明3個理由）
## ⚠️ 各自的主要風險（各列2點）

禁止使用「一定」「保證」「必漲」「必跌」。"""
    return call_ai(api_key, prompt, use_search=True)

# ═══════════════════════════════════════
# 圖表建立
# ═══════════════════════════════════════
def build_chart(hist: pd.DataFrame, ind: dict, entry: dict, sym: str):
    idx = hist.index
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.50, 0.18, 0.17, 0.15],
        subplot_titles=["K線+均線+布林", "成交量", "RSI+KD", "MACD"]
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=idx, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name="K線",
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a"
    ), row=1, col=1)

    # 均線
    for key, color, name in [("_ma5","#FFA726","MA5"),("_ma20","#42A5F5","MA20"),("_ma60","#AB47BC","MA60")]:
        fig.add_trace(go.Scatter(x=idx, y=ind[key], line=dict(color=color, width=1.3), name=name), row=1, col=1)

    # 布林通道
    fig.add_trace(go.Scatter(x=idx, y=ind["_bb_upper"],
        line=dict(color="rgba(255,235,59,0.5)", width=1, dash="dot"), name="布林上"), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_bb_lower"],
        line=dict(color="rgba(255,235,59,0.5)", width=1, dash="dot"), name="布林下",
        fill="tonexty", fillcolor="rgba(255,235,59,0.04)"), row=1, col=1)

    # 支撐壓力與入場參考
    for y_val, color, label in [
        (entry["sup1"], "rgba(38,166,154,0.8)", f"支撐{entry['sup1']}"),
        (entry["res1"], "rgba(239,83,80,0.8)",  f"壓力{entry['res1']}"),
        (entry["mod_buy"], "rgba(100,220,100,0.8)", f"參考買入{entry['mod_buy']}"),
    ]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=color,
                      annotation_text=label, annotation_font_size=10, row=1, col=1)

    # 成交量
    vc = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(hist["Close"], hist["Open"])]
    fig.add_trace(go.Bar(x=idx, y=ind["_v"], marker_color=vc, showlegend=False, name="成交量"), row=2, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_v"].rolling(20).mean(),
        line=dict(color="#FFA726", width=1.2), name="均量", showlegend=False), row=2, col=1)

    # RSI + Stochastic
    fig.add_trace(go.Scatter(x=idx, y=ind["_rsi"],
        line=dict(color="#FF7043", width=1.5), name="RSI", showlegend=False), row=3, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_stoch_k"],
        line=dict(color="#66BB6A", width=1, dash="dot"), name="Stoch K", showlegend=False), row=3, col=1)
    for lv, lc in [(70, "rgba(239,83,80,0.4)"), (50, "rgba(150,150,150,0.3)"), (30, "rgba(38,166,154,0.4)")]:
        fig.add_hline(y=lv, line_dash="dash", line_color=lc, row=3, col=1)

    # MACD
    mc_colors = ["#ef5350" if x >= 0 else "#26a69a" for x in ind["_macd_hist"]]
    fig.add_trace(go.Bar(x=idx, y=ind["_macd_hist"], marker_color=mc_colors, showlegend=False, name="MACD Hist"), row=4, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_macd"], line=dict(color="#42A5F5", width=1), showlegend=False, name="MACD"), row=4, col=1)
    fig.add_trace(go.Scatter(x=idx, y=ind["_macd_sig"], line=dict(color="#FF7043", width=1), showlegend=False, name="Signal"), row=4, col=1)

    fig.update_layout(
        title=f"{sym} 進階技術分析", height=820,
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font_color="#FFFFFF", legend=dict(orientation="h", y=1.02, font_size=11),
        margin=dict(l=50, r=50, t=80, b=30),
    )
    return fig

# ═══════════════════════════════════════
# 側邊欄
# ═══════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input("🔑 Gemini API 金鑰", type="password", placeholder="AIza...")
    st.caption("金鑰只存在瀏覽器，不會被儲存")

    # 雲端狀態
    if HAS_DB:
        st.markdown('<span class="db-ok">✅ 雲端資料庫已連線（Supabase）</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="db-no">⚠️ 本機模式（需設定 Supabase Secrets）</span>', unsafe_allow_html=True)

    st.divider()

    # 帳號系統
    st.header("👤 個人帳號")
    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號（自訂英文/數字）", placeholder="如 jason123", key="lu")
            upin  = st.text_input("密碼", type="password", key="lp")
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔑 登入", use_container_width=True):
                    if uname.strip() and upin.strip():
                        ok, uid = db_verify_user(uname.strip(), upin.strip())
                        if ok:
                            st.session_state.user_id   = uid
                            st.session_state.username  = uname.strip()
                            st.session_state.logged_in = True
                            st.session_state.watchlist = db_load_watchlist(uid)
                            st.session_state.alerts    = db_load_alerts(uid)
                            st.session_state.portfolio = db_load_portfolio(uid)
                            st.success(f"✅ 歡迎，{uname}！")
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
                            st.session_state.logged_in = True
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")
            st.caption("帳號密碼請自行記住，系統無法找回密碼")
    else:
        st.success(f"👤 {st.session_state.username}")
        st.caption("✅ 雲端同步" if HAS_DB else "⚠️ 本機模式（未連線雲端）")
        if st.button("🚪 登出", use_container_width=True):
            for k in ["user_id","username","logged_in"]:
                st.session_state[k] = None if k != "logged_in" else False
            st.session_state.watchlist = []
            st.session_state.alerts = {}
            st.session_state.portfolio = {}
            st.rerun()

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("股票市場", ["🇹🇼 台股", "🇺🇸 美股"])
    period = st.selectbox("分析區間", ["3mo","6mo","1y","2y"], index=1,
        format_func=lambda x: {"3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年"}[x])
    st.caption("⏱️ 數據每5分鐘更新一次（快取機制）")

    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號", placeholder="輸入後按Enter", key="nw_inp")
    if nw and nw.strip():
        sa = get_sym(nw.strip(), market)
        if sa not in st.session_state.watchlist:
            st.session_state.watchlist.append(sa)
            if st.session_state.logged_in:
                db_add_watch(st.session_state.user_id, sa)
            st.rerun()
    for i, s in enumerate(st.session_state.watchlist):
        c1, c2 = st.columns([4, 1])
        c1.write(f"• {s}")
        if c2.button("❌", key=f"dw{i}"):
            if st.session_state.logged_in:
                db_del_watch(st.session_state.user_id, s)
            st.session_state.watchlist.pop(i)
            st.rerun()

    st.divider()
    st.header("🔔 價格警報")
    as_ = st.text_input("代號", key="al_sym")
    au_ = st.number_input("↑ 漲破提醒", 0.0, step=0.5)
    ad_ = st.number_input("↓ 跌破提醒", 0.0, step=0.5)
    if st.button("✅ 設定警報", use_container_width=True):
        if as_.strip():
            sa2 = get_sym(as_.strip(), market)
            st.session_state.alerts[sa2] = {"above": au_ or None, "below": ad_ or None}
            if st.session_state.logged_in:
                db_save_alert(st.session_state.user_id, sa2, au_, ad_)
            st.success("✅ 警報已設定")
    if st.session_state.alerts:
        st.caption("目前警報：")
        for sa3, av in list(st.session_state.alerts.items()):
            pts = []
            if av.get("above"): pts.append(f"↑{av['above']}")
            if av.get("below"): pts.append(f"↓{av['below']}")
            c1a, c2a = st.columns([4,1])
            c1a.caption(f"• {sa3}: {' / '.join(pts)}")
            if c2a.button("❌", key=f"dal_{sa3}"):
                if st.session_state.logged_in:
                    db_del_alert(st.session_state.user_id, sa3)
                del st.session_state.alerts[sa3]
                st.rerun()

    st.divider()
    st.header("📖 名詞解釋小百科")
    st.caption("點擊任一名詞查看白話解釋")
    for term, desc in GLOSSARY.items():
        with st.expander(term):
            st.info(desc)

# ═══════════════════════════════════════
# 主標題
# ═══════════════════════════════════════
st.title("📈 股市小白分析系統 Pro")
st.caption("AI即時搜尋 × 15項指標 × ATR明日預測 × 入場策略 × 帳號記憶")

# 大盤概況
with st.expander("🌐 今日大盤概況（點擊展開）", expanded=False):
    mkt_data = fetch_market_overview()
    if mkt_data:
        mc_cols = st.columns(len(mkt_data))
        for col, row in zip(mc_cols, mkt_data):
            chg_val = row["_chg"]
            delta_color = "normal" if chg_val >= 0 else "inverse"
            col.metric(row["名稱"], str(row["現值"]), row["漲跌"])
    else:
        st.caption("大盤數據暫時無法取得")

# 最近查詢
if st.session_state.recent_searches:
    st.markdown("**🕐 最近查詢：**")
    cols_r = st.columns(min(len(st.session_state.recent_searches), 8))
    for i, rs in enumerate(st.session_state.recent_searches):
        if cols_r[i].button(rs, key=f"rs_{i}_{rs}"):
            st.session_state.quick_sym = rs
            st.session_state.auto_analyze = True
            st.rerun()

# ═══════════════════════════════════════
# 主要分頁
# ═══════════════════════════════════════
tabs = st.tabs(["🔍 深度分析", "⭐ 自選股", "📰 即時新聞", "🏦 籌碼基本面", "⚖️ 股票比較", "💼 持股損益"])

# ─────────────────────────
# TAB 1：深度分析
# ─────────────────────────
with tabs[0]:
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
    c1, c2 = st.columns([3, 1])
    with c1:
        dv = st.session_state.quick_sym or ""
        ph_text = "例如：2330（台積電）、0050（元大台50）" if "台股" in market else "例如：NVDA（輝達）、AAPL（蘋果）"
        ticker_in = st.text_input("輸入股票代號", value=dv, placeholder=ph_text, key="main_ticker")
    with c2:
        st.write(""); st.write("")
        go_btn = st.button("🔍 開始深度分析", use_container_width=True, type="primary")

    # 自動觸發（快速選股按鈕）
    should_analyze = go_btn or (st.session_state.auto_analyze and st.session_state.quick_sym)
    if st.session_state.auto_analyze:
        st.session_state.auto_analyze = False

    if should_analyze and (ticker_in or st.session_state.quick_sym).strip():
        use_ticker = ticker_in.strip() or st.session_state.quick_sym
        if not api_key:
            st.warning("⚠️ 請在左側輸入 Gemini API 金鑰")
            st.stop()

        sym = get_sym(use_ticker, market)
        add_recent(sym)

        with st.spinner(f"抓取 {sym} 數據中...（每5分鐘更新一次）"):
            hist, info, err = fetch_data(sym, period)
        if err:
            st.error(f"❌ {err}")
            st.stop()

        ind   = calc_indicators(hist)
        entry = calc_entry(ind, hist)
        score = calc_score(ind, info)
        co    = info.get("longName") or info.get("shortName") or sym
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 警報檢查
        if sym in st.session_state.alerts:
            a = st.session_state.alerts[sym]
            if a.get("above") and ind["price"] >= a["above"]:
                st.error(f"🔔 警報觸發！{sym} 已漲破 {a['above']}，現價 {ind['price']}")
            if a.get("below") and ind["price"] <= a["below"]:
                st.error(f"🔔 警報觸發！{sym} 已跌破 {a['below']}，現價 {ind['price']}")

        # 標題 + 時間戳 + 加入自選
        ct, ca_ = st.columns([5, 1])
        with ct:
            st.subheader(f"📌 {co}（{sym}）")
            st.caption(f"數據時間：{now_str} ｜ 分析區間：{period}")
        with ca_:
            if sym not in st.session_state.watchlist:
                if st.button("⭐ 加入自選", use_container_width=True):
                    st.session_state.watchlist.append(sym)
                    if st.session_state.logged_in:
                        db_add_watch(st.session_state.user_id, sym)
                    st.success("✅ 已加入")
            else:
                st.success("⭐ 已在自選")

        # 評分 + 狀態
        cs_, cs2 = st.columns([1, 2])
        with cs_:
            st.markdown(f"""
            <div class="score-card">
                <div style="color:#94a3b8;font-size:12px">綜合健康評分</div>
                <div class="big-score" style="color:{score['gc']}">{score['total']}</div>
                <div style="color:#e2e8f0;font-size:14px;margin-top:4px">{score['grade']}</div>
                <div style="color:#64748b;font-size:11px;margin-top:4px">滿分100分</div>
            </div>""", unsafe_allow_html=True)
            st.progress(score["trend"] / 30, text=f"趨勢 {score['trend']}/30")
            st.progress(score["mom"] / 25,   text=f"動能 {score['mom']}/25")
            st.progress(score["vol"] / 20,   text=f"量能 {score['vol']}/20")
            st.progress(score["pos"] / 15,   text=f"位置 {score['pos']}/15")
            st.progress(score["bb"] / 10,    text=f"布林 {score['bb']}/10")

        with cs2:
            st.markdown(f"""
            <div class="status-card">
                <h3 style="margin:0;color:#e2e8f0">{ind['sc']} 目前狀態：{ind['status']}</h3>
                <p style="margin:8px 0 0 0;color:#94a3b8;font-size:13px">{ind['status_desc']}</p>
            </div>""", unsafe_allow_html=True)
            chg_icon = "🔴" if ind["change_pct"] >= 0 else "🟢"
            r1, r2, r3 = st.columns(3)
            r1.metric("💰 現價",  f"{ind['price']}")
            r2.metric("今日",     f"{chg_icon}{ind['change_pct']}%")
            r3.metric("本月",     f"{ind['change_1m']}%")
            r4, r5, r6 = st.columns(3)
            r4.metric("📏 RSI",  f"{ind['rsi']}")
            r5.metric("📦 量比", f"{ind['vol_ratio']}x")
            r6.metric("📐 ATR",  f"{ind['atr']}")

        st.divider()

        # 指標白話說明（可展開）
        with st.expander("🔍 各指標白話解讀（展開查看詳細說明）", expanded=True):
            ia, ib, ic = st.columns(3)
            with ia:
                st.info(f"**📏 RSI（{ind['rsi']}）**\n\n{ind['rsi_desc']}")
                sk = ind["stoch_k"]
                sk_desc = "⚠️ K值>80，超買區，短線過熱" if sk > 80 else ("💡 K值<20，超賣區，留意反彈" if sk < 20 else "➡️ K值中間區域，方向待確認")
                st.info(f"**📊 Stochastic K（{sk}）**\n\n{sk_desc}")
            with ib:
                st.info(f"**📦 成交量**\n\n{ind['vol_desc']}")
                bp = ind["bb_pct"]
                bp_desc = "⚠️ 接近布林上軌，過熱警戒" if bp > 80 else ("💡 接近布林下軌，超賣區" if bp < 20 else "✅ 在布林通道中間，波動正常")
                st.info(f"**📐 布林通道（{bp:.0f}%位置）**\n\n{bp_desc}")
            with ic:
                st.info(f"**📅 52週位置**\n\n{ind['position_desc']}")
                mh = ind["macd_hist"]
                st.info(f"**📡 MACD動能（{mh:.4f}）**\n\n{'📈 柱狀圖正值，上漲動能增強' if mh > 0 else '📉 柱狀圖負值，下跌動能增強'}")

        st.divider()

        # 入場策略
        with st.expander("💰 入場策略參考（展開查看）", expanded=True):
            st.caption("⚠️ 以下由技術指標自動計算，僅供參考學習，不構成任何投資建議，請自行判斷")
            e1, e2, e3 = st.columns(3)
            with e1:
                st.markdown(f"""
                <div class="entry-card">
                    <div style="color:#66cc66;font-weight:bold;font-size:14px">🎯 參考買入區</div>
                    <div style="margin:10px 0;color:#e2e8f0;line-height:2">
                        保守型：<b>{entry['con_buy']}</b><br>
                        穩健型：<b>{entry['mod_buy']}</b><br>
                        積極型：<b>{entry['agg_buy']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">台股一張參考：約 {entry['lot_cost']:,.0f} 元</div>
                </div>""", unsafe_allow_html=True)
            with e2:
                st.markdown(f"""
                <div class="stop-card">
                    <div style="color:#ff6666;font-weight:bold;font-size:14px">🛡️ 停損參考</div>
                    <div style="margin:10px 0;color:#e2e8f0;line-height:2">
                        緊（短線）：<b>{entry['sl_tight']}</b><br>
                        標準：<b>{entry['sl_normal']}</b><br>
                        寬（長線）：<b>{entry['sl_wide']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">跌破停損線就出場，這是保護本金的安全帶</div>
                </div>""", unsafe_allow_html=True)
            with e3:
                st.markdown(f"""
                <div class="target-card">
                    <div style="color:#66aaff;font-weight:bold;font-size:14px">🎯 目標價位</div>
                    <div style="margin:10px 0;color:#e2e8f0;line-height:2">
                        短線 T1：<b>{entry['tp1']}</b><br>
                        中線 T2：<b>{entry['tp2']}</b><br>
                        長線 T3：<b>{entry['tp3']}</b>
                    </div>
                    <div style="color:#94a3b8;font-size:11px">風報比：{entry['rr']}:1（建議至少2:1以上）</div>
                </div>""", unsafe_allow_html=True)

            with st.expander("📐 Fibonacci 回撤關鍵支撐壓力位"):
                st.caption(f"計算基準：近期高點 {entry['ph']} ↔ 近期低點 {entry['pl']}")
                fib_df = pd.DataFrame([
                    {"回撤位置": "0.236（弱支撐）",   "價位": entry['fibs']['0.236'], "白話說明": "下跌力道弱，短線支撐"},
                    {"回撤位置": "0.382（強支撐）★", "價位": entry['fibs']['0.382'], "白話說明": "最常見強支撐，技術派愛在此買入"},
                    {"回撤位置": "0.500（中間位）",   "價位": entry['fibs']['0.500'], "白話說明": "心理支撐，多空攻防關鍵"},
                    {"回撤位置": "0.618（黃金比例）★","價位": entry['fibs']['0.618'], "白話說明": "最重要的支撐壓力，黃金分割點"},
                    {"回撤位置": "0.786（深回撤）",   "價位": entry['fibs']['0.786'], "白話說明": "回撤幅度深，測試主要趨勢強度"},
                ])
                st.dataframe(fib_df, use_container_width=True, hide_index=True)

        st.divider()

        # 圖表
        st.markdown("### 📈 進階技術分析圖")
        st.caption("含布林通道、支撐壓力、RSI+Stochastic、MACD ｜ 滑鼠滾輪縮放，拖曳移動時間範圍")
        st.plotly_chart(build_chart(hist, ind, entry, sym), use_container_width=True)

        st.divider()

        # AI報告（分段展開）
        st.markdown("### 🤖 AI 深度分析報告")
        st.caption("Gemini AI 即時搜尋 Google 全網 × 15項技術指標 × ATR明日沙盤推演")

        with st.spinner("🔍 AI 即時搜尋最新資訊並深度分析中（約 30~60 秒，請耐心等候）..."):
            try:
                full_report = ai_full_report(ind, info, sym, api_key, entry, score)
                # 分段顯示（依 ## 標題拆分）
                sections = full_report.split("\n## ")
                if len(sections) > 1:
                    # 第一段（引言）直接顯示
                    st.markdown(sections[0])
                    # 其餘各段做成展開區塊
                    section_labels = {
                        "🌍": "宏觀環境即時掃描",
                        "📰": "公司與產業最新情報",
                        "🏢": "公司白話介紹",
                        "📊": "15項技術指標完整解讀",
                        "💰": "入場策略詳解",
                        "🔮": "明日走勢沙盤推演",
                        "🎯": "短中期走勢研判",
                        "⚠️": "主要風險清單",
                        "📌": "小白總結",
                        "📖": "術語速查對照表",
                    }
                    for sec in sections[1:]:
                        lines = sec.split("\n", 1)
                        title = f"## {lines[0]}"
                        content = lines[1] if len(lines) > 1 else ""
                        # 🔮 明日預測區塊特別標亮
                        if "🔮" in title:
                            st.markdown(f"""
                            <div class="predict-card">
                                <div style="color:#c084fc;font-size:16px;font-weight:bold;margin-bottom:12px">{title}</div>
                            </div>""", unsafe_allow_html=True)
                            st.markdown(content)
                        else:
                            with st.expander(title, expanded=("🔮" in title or "📌" in title)):
                                st.markdown(content)
                else:
                    st.markdown(full_report)
                st.session_state.last_report_time[sym] = now_str
            except Exception as e:
                st.error(f"❌ AI 分析失敗：{str(e)}")

        st.divider()
        st.warning("⚠️ **免責聲明**：本系統所有分析與入場策略建議**僅供學習與參考用途**，不構成任何投資建議。股市有風險，請為自己的投資決策負責。")

        with st.expander("🔧 進階：完整原始技術指標數據"):
            raw_df = pd.DataFrame({
                "指標": ["現價","今日%","5日%","月%","MA5","MA10","MA20","MA60","VWAP",
                         "RSI","Stoch K","Stoch D","Williams%R","MACD","Signal","Hist",
                         "布林上","布林中","布林下","BB%","布林寬度%","ATR","OBV",
                         "成交量","20日均量","量比","52週高","52週低","52週位置%"],
                "數值": [ind["price"],f"{ind['change_pct']}%",f"{ind['change_5d']}%",f"{ind['change_1m']}%",
                         ind["ma5"],ind["ma10"],ind["ma20"],ind["ma60"],ind["vwap"],
                         ind["rsi"],ind["stoch_k"],ind["stoch_d"],ind["williams_r"],
                         ind["macd"],ind["macd_sig"],ind["macd_hist"],
                         ind["bb_upper"],ind["bb_mid"],ind["bb_lower"],
                         f"{ind['bb_pct']:.0f}%",f"{ind['bb_width']:.1f}%",ind["atr"],ind["obv"],
                         ind["volume"],ind["vol_ma20"],f"{ind['vol_ratio']}x",
                         ind["high_52w"],ind["low_52w"],f"{ind['position_52w']}%"],
            })
            st.dataframe(raw_df, use_container_width=True, hide_index=True)

# ─────────────────────────
# TAB 2：自選股
# ─────────────────────────
with tabs[1]:
    st.markdown("### ⭐ 我的自選股清單")
    if not st.session_state.logged_in:
        st.info("💡 登入帳號後，自選股永久保存在雲端，換電腦也不會消失")
    if not st.session_state.watchlist:
        st.info("📝 自選股是空的！在左側欄位新增，或分析股票後按「加入自選」")
    else:
        if api_key:
            with st.spinner("載入即時股價中..."):
                rows = []
                for s in st.session_state.watchlist:
                    try:
                        hh = yf.Ticker(s).history(period="5d")
                        if not hh.empty and len(hh) >= 2:
                            p   = round(float(hh["Close"].iloc[-1]), 2)
                            chg = round((float(hh["Close"].iloc[-1]) - float(hh["Close"].iloc[-2])) / float(hh["Close"].iloc[-2]) * 100, 2)
                            chg_str = f"🔴+{chg}%" if chg >= 0 else f"🟢{chg}%"
                            has_alert = "🔔" if s in st.session_state.alerts else ""
                            rows.append({"代號": s, "現價": p, "今日": chg_str, "警報": has_alert})
                        else:
                            rows.append({"代號": s, "現價": "N/A", "今日": "-", "警報": ""})
                    except:
                        rows.append({"代號": s, "現價": "N/A", "今日": "-", "警報": ""})

            if rows:
                wl_df = pd.DataFrame(rows)
                st.dataframe(wl_df, use_container_width=True, hide_index=True)
                st.caption("點擊代號可直接跳到分析頁")
                # 快速分析按鈕
                btn_cols = st.columns(min(len(st.session_state.watchlist), 6))
                for i, s in enumerate(st.session_state.watchlist[:6]):
                    if btn_cols[i].button(f"分析 {s}", use_container_width=True, key=f"wl_analyze_{i}"):
                        st.session_state.quick_sym = s.replace(".TW", "") if ".TW" in s else s
                        st.session_state.auto_analyze = True
                        st.rerun()
        else:
            st.dataframe(pd.DataFrame({"代號": st.session_state.watchlist}), use_container_width=True, hide_index=True)
            st.caption("輸入 API 金鑰後可顯示即時股價")

        if st.button("🗑️ 清空所有自選股"):
            if st.session_state.logged_in:
                for s in st.session_state.watchlist:
                    db_del_watch(st.session_state.user_id, s)
            st.session_state.watchlist = []
            st.rerun()

# ─────────────────────────
# TAB 3：即時新聞
# ─────────────────────────
with tabs[2]:
    st.markdown("### 📰 AI 即時新聞分析")
    st.info("💡 AI 即時搜尋 Google 全網，包含新聞、分析師報告、社群討論、宏觀政策等，用白話解釋對股票的影響")
    cn1, cn2 = st.columns([3, 1])
    with cn1:
        n_in = st.text_input("輸入股票代號", placeholder="例如：2330 或 NVDA", key="news_inp")
    with cn2:
        st.write(""); st.write("")
        n_btn = st.button("🔍 搜尋全網資訊", use_container_width=True, type="primary")

    if n_btn and n_in.strip():
        if not api_key:
            st.warning("⚠️ 需要 API 金鑰")
        else:
            ns = get_sym(n_in.strip(), market)
            _, ni, _ = fetch_data(ns, "1mo")
            nc  = (ni or {}).get("longName") or ns
            nsc = (ni or {}).get("sector", "")
            with st.spinner("🔍 AI 搜尋全網最新資訊（約 30~60 秒）..."):
                try:
                    rpt = ai_news_report(nc, ns, nsc, api_key)
                    sections_n = rpt.split("\n## ")
                    if len(sections_n) > 1:
                        st.markdown(sections_n[0])
                        for sec in sections_n[1:]:
                            lines = sec.split("\n", 1)
                            with st.expander(f"## {lines[0]}", expanded=True):
                                st.markdown(lines[1] if len(lines) > 1 else "")
                    else:
                        st.markdown(rpt)
                except Exception as e:
                    st.error(f"❌ {str(e)}")

# ─────────────────────────
# TAB 4：籌碼基本面
# ─────────────────────────
with tabs[3]:
    st.markdown("### 🏦 籌碼面 + 基本面深度分析")
    st.caption("💡 美股數據較完整；台股的機構持股數據有限，這是數據來源的限制。")
    cc1, cc2 = st.columns([3, 1])
    with cc1:
        c_in = st.text_input("輸入股票代號", placeholder="例如：AAPL 或 2330", key="chip_inp")
    with cc2:
        st.write(""); st.write("")
        c_btn = st.button("🏦 查看籌碼", use_container_width=True)

    if c_btn and c_in.strip():
        cs_ = get_sym(c_in.strip(), market)
        with st.spinner("載入籌碼數據..."):
            try:
                to_ = yf.Ticker(cs_)
                ic_ = to_.info
                cc_ = ic_.get("longName") or cs_
                st.subheader(f"📌 {cc_} 籌碼基本面分析")

                # 財務指標網格（18項）
                with st.expander("📊 核心財務指標（展開查看）", expanded=True):
                    metrics_list = [
                        ("市值", ic_.get("marketCap")),
                        ("本益比 PE（目前）", ic_.get("trailingPE")),
                        ("本益比 PE（預估）", ic_.get("forwardPE")),
                        ("股價淨值比 PB", ic_.get("priceToBook")),
                        ("每股盈餘 EPS", ic_.get("trailingEps")),
                        ("ROE 股東權益報酬", ic_.get("returnOnEquity")),
                        ("毛利率", ic_.get("grossMargins")),
                        ("淨利率", ic_.get("profitMargins")),
                        ("營收成長率", ic_.get("revenueGrowth")),
                        ("獲利成長率", ic_.get("earningsGrowth")),
                        ("股息殖利率", ic_.get("dividendYield")),
                        ("Beta 波動係數", ic_.get("beta")),
                        ("分析師目標價", ic_.get("targetMeanPrice")),
                        ("分析師評級", ic_.get("recommendationKey")),
                        ("負債權益比", ic_.get("debtToEquity")),
                        ("流動比率", ic_.get("currentRatio")),
                        ("52週最高", ic_.get("fiftyTwoWeekHigh")),
                        ("52週最低", ic_.get("fiftyTwoWeekLow")),
                    ]
                    gcols_ = st.columns(3)
                    for i, (k_, val_) in enumerate(metrics_list):
                        if val_ is not None:
                            try:
                                if k_ == "股息殖利率" and isinstance(val_, float): val_ = f"{val_*100:.2f}%"
                                elif k_ == "市值" and isinstance(val_, (int, float)):
                                    val_ = f"約{val_/1e8:.0f}億" if val_ > 1e8 else f"{val_:,.0f}"
                                elif k_ in ["ROE 股東權益報酬","毛利率","淨利率","營收成長率","獲利成長率"] and isinstance(val_, float):
                                    val_ = f"{val_*100:.1f}%"
                                gcols_[i % 3].metric(k_, val_)
                            except: pass

                st.info("""
                📖 **基本面白話速查：**
                • **PE偏低** = 可能相對便宜（需跟同產業比較）
                • **ROE高** = 公司用你的錢賺錢的效率高，越高越好
                • **Beta>1** = 漲跌比大盤更劇烈，適合能承受波動的人
                • **分析師評級 buy** = 多數分析師建議買入；**hold** = 觀望；**sell** = 賣出
                • **負債權益比高** = 公司借了很多錢，要注意財務風險
                """)

                # 機構持股
                st.divider()
                gm1, gm2 = st.columns(2)
                with gm1:
                    st.markdown("#### 股權結構")
                    mh_ = to_.major_holders
                    if mh_ is not None and not mh_.empty:
                        st.dataframe(mh_, use_container_width=True, hide_index=True)
                    else:
                        st.info("無法取得（台股較少）")
                with gm2:
                    st.markdown("#### 主要機構持股 Top 10")
                    ih_ = to_.institutional_holders
                    if ih_ is not None and not ih_.empty:
                        st.dataframe(ih_.head(10), use_container_width=True, hide_index=True)
                        st.caption("法人持股越多、越集中，代表機構看好這支股票")
                    else:
                        st.info("無法取得（台股較少）")

                # AI籌碼解讀
                if api_key:
                    st.divider()
                    st.markdown("### 🤖 AI 籌碼基本面白話解讀（含即時搜尋）")
                    with st.spinner("AI 分析中..."):
                        try:
                            chip_prompt = f"""請即時搜尋「{cc_}」最新財務表現、分析師評價、法人動向，然後用白話文解讀以下數據。

數據：
PE={ic_.get('trailingPE','N/A')} | 預估PE={ic_.get('forwardPE','N/A')} | PB={ic_.get('priceToBook','N/A')}
ROE={ic_.get('returnOnEquity','N/A')} | 毛利率={ic_.get('grossMargins','N/A')} | 淨利率={ic_.get('profitMargins','N/A')}
Beta={ic_.get('beta','N/A')} | 評級={ic_.get('recommendationKey','N/A')} | 目標價={ic_.get('targetMeanPrice','N/A')}
負債權益比={ic_.get('debtToEquity','N/A')} | 流動比率={ic_.get('currentRatio','N/A')}

搜尋最新資訊後，用繁體中文輸出：

## 💰 基本面白話解讀
（每個數據用白話解釋，跟產業平均比較，說明是貴還是便宜）

## 🌐 分析師最新看法
（目標價和評級代表什麼，目前分析師共識如何，最近有沒有調升或調降評級）

## 📊 與主要競爭對手比較
（搜尋同產業對手，做簡單比較，誰的基本面更好？）

## 🏦 法人籌碼解讀
（機構持股的意義，法人最近是加碼還是減碼？對散戶的參考價值）

## ⚠️ 新手看基本面常犯的3個錯誤

禁止使用「一定」「保證」「必漲」「必跌」。"""
                            chip_rpt = call_ai(api_key, chip_prompt, use_search=True)
                            sections_c = chip_rpt.split("\n## ")
                            st.markdown(sections_c[0])
                            for sec in sections_c[1:]:
                                lines = sec.split("\n", 1)
                                with st.expander(f"## {lines[0]}", expanded=True):
                                    st.markdown(lines[1] if len(lines) > 1 else "")
                        except Exception as e:
                            st.error(f"❌ {str(e)}")

                if "台股" in market:
                    st.warning("⚠️ 台股外資/投信/自營商詳細數據需透過台灣證交所取得，目前系統顯示的是 yfinance 提供的有限數據，美股數據更完整。")

            except Exception as e:
                st.error(f"❌ 載入失敗：{str(e)}")

# ─────────────────────────
# TAB 5：股票比較
# ─────────────────────────
with tabs[4]:
    st.markdown("### ⚖️ 股票比較分析")
    st.caption("同時分析兩支股票，AI 即時搜尋後客觀比較，幫你做出更好的決策")
    cm1, cm2 = st.columns(2)
    with cm1:
        s1_in = st.text_input("股票 A", placeholder="例如：2330", key="s1_inp")
    with cm2:
        s2_in = st.text_input("股票 B", placeholder="例如：2454", key="s2_inp")
    cmp_btn = st.button("⚖️ 開始比較", use_container_width=True, type="primary")

    if cmp_btn and s1_in.strip() and s2_in.strip():
        if not api_key:
            st.warning("⚠️ 需要 API 金鑰")
        else:
            sym1 = get_sym(s1_in.strip(), market)
            sym2 = get_sym(s2_in.strip(), market)
            with st.spinner("載入兩支股票數據..."):
                h1, i1, e1_err = fetch_data(sym1, period)
                h2, i2, e2_err = fetch_data(sym2, period)
            if e1_err or e2_err:
                st.error(f"❌ {e1_err or e2_err}")
            else:
                ind1_ = calc_indicators(h1); ind2_ = calc_indicators(h2)
                sc1_  = calc_score(ind1_, i1); sc2_ = calc_score(ind2_, i2)
                en1_  = calc_entry(ind1_, h1); en2_ = calc_entry(ind2_, h2)
                n1_   = (i1 or {}).get("longName") or sym1
                n2_   = (i2 or {}).get("longName") or sym2

                # 比較數據表
                cmp_df = pd.DataFrame({
                    "指標": ["現價","今日漲跌","月漲跌","RSI","Stoch K","MACD方向","量比","52週位置","布林位置","ATR","綜合評分","技術狀態"],
                    n1_: [ind1_["price"],f"{ind1_['change_pct']}%",f"{ind1_['change_1m']}%",
                          ind1_["rsi"],ind1_["stoch_k"],"📈" if ind1_["macd_hist"]>0 else "📉",
                          f"{ind1_['vol_ratio']}x",f"{ind1_['position_52w']}%",f"{ind1_['bb_pct']:.0f}%",
                          ind1_["atr"],f"{sc1_['total']}/100",ind1_["status"]],
                    n2_: [ind2_["price"],f"{ind2_['change_pct']}%",f"{ind2_['change_1m']}%",
                          ind2_["rsi"],ind2_["stoch_k"],"📈" if ind2_["macd_hist"]>0 else "📉",
                          f"{ind2_['vol_ratio']}x",f"{ind2_['position_52w']}%",f"{ind2_['bb_pct']:.0f}%",
                          ind2_["atr"],f"{sc2_['total']}/100",ind2_["status"]],
                })
                st.dataframe(cmp_df, use_container_width=True, hide_index=True)

                # 評分對比
                sc_c1, sc_c2 = st.columns(2)
                with sc_c1:
                    st.markdown(f"""<div class="score-card">
                        <div style="color:#94a3b8;font-size:12px">{n1_}</div>
                        <div class="big-score" style="color:{sc1_['gc']}">{sc1_['total']}</div>
                        <div style="color:#e2e8f0;font-size:13px">{sc1_['grade']}</div>
                    </div>""", unsafe_allow_html=True)
                with sc_c2:
                    st.markdown(f"""<div class="score-card">
                        <div style="color:#94a3b8;font-size:12px">{n2_}</div>
                        <div class="big-score" style="color:{sc2_['gc']}">{sc2_['total']}</div>
                        <div style="color:#e2e8f0;font-size:13px">{sc2_['grade']}</div>
                    </div>""", unsafe_allow_html=True)

                # 圖表對比
                cg1, cg2 = st.columns(2)
                with cg1: st.plotly_chart(build_chart(h1, ind1_, en1_, sym1), use_container_width=True)
                with cg2: st.plotly_chart(build_chart(h2, ind2_, en2_, sym2), use_container_width=True)

                st.divider()
                st.markdown("### 🤖 AI 比較分析（即時搜尋版）")
                with st.spinner("AI 搜尋並比較中（約 30~60 秒）..."):
                    try:
                        cmp_rpt = ai_compare(sym1, n1_, sc1_, ind1_, en1_, sym2, n2_, sc2_, ind2_, en2_, api_key)
                        sections_cmp = cmp_rpt.split("\n## ")
                        st.markdown(sections_cmp[0])
                        for sec in sections_cmp[1:]:
                            lines = sec.split("\n", 1)
                            with st.expander(f"## {lines[0]}", expanded=True):
                                st.markdown(lines[1] if len(lines) > 1 else "")
                    except Exception as e:
                        st.error(f"❌ {str(e)}")

# ─────────────────────────
# TAB 6：持股損益
# ─────────────────────────
with tabs[5]:
    st.markdown("### 💼 持股損益試算")
    st.caption("輸入你的買入成本與股數，即時計算損益、年化報酬、台股張數換算")

    pp1, pp2, pp3, pp4, pp5 = st.columns(5)
    with pp1: p_s = st.text_input("股票代號", placeholder="如 2330", key="pf_sym")
    with pp2: p_c = st.number_input("買入成本（每股）", min_value=0.0, step=0.5, key="pf_cost")
    with pp3: p_n = st.number_input("持有股數", min_value=0.0, step=100.0, key="pf_shares")
    with pp4: p_d = st.date_input("買入日期", key="pf_date")
    with pp5:
        st.write(""); st.write("")
        p_btn = st.button("📊 計算損益", use_container_width=True, type="primary")

    if p_btn and p_s.strip() and p_c > 0 and p_n > 0:
        ps_ = get_sym(p_s.strip(), market)
        with st.spinner("取得現價..."):
            ph_, pi_, pe_ = fetch_data(ps_, "5d")
        if pe_:
            st.error(f"❌ {pe_}")
        else:
            cp_ = round(float(ph_["Close"].iloc[-1]), 2)
            pnl = round((cp_ - p_c) * p_n, 2)
            pct = round((cp_ - p_c) / max(p_c, 0.01) * 100, 2)
            tc  = round(p_c * p_n, 2)
            cv  = round(cp_ * p_n, 2)
            co_ = (pi_ or {}).get("longName") or ps_

            # 持有天數與年化報酬
            hold_days = (date.today() - p_d).days if p_d else 0
            annual_rtn = round(pct / max(hold_days, 1) * 365, 2) if hold_days > 0 else 0
            # 台股張數
            lots = round(p_n / 1000, 2)

            st.subheader(f"📌 {co_}（{ps_}）")
            col_r = st.columns(5)
            col_r[0].metric("💰 現價",    f"{cp_}")
            col_r[1].metric("📊 總成本",  f"{tc:,.0f}")
            col_r[2].metric("💎 現值",    f"{cv:,.0f}")
            col_r[3].metric("損益",       f"{pnl:+,.0f}", delta=f"{pct:+.2f}%")
            col_r[4].metric("年化報酬",   f"{annual_rtn:+.1f}%")

            clr = "#0d2b0d" if pnl >= 0 else "#2b0d0d"
            bdr = "#2a5a2a" if pnl >= 0 else "#5a2a2a"
            ico = "📈 獲利中" if pnl >= 0 else "📉 虧損中"
            st.markdown(f"""
            <div style="background:{clr};border-radius:12px;padding:20px;margin:12px 0;border:1px solid {bdr}">
                <h3 style="margin:0;color:{'#66ff66' if pnl>=0 else '#ff6666'}">{ico}　{abs(pnl):,.0f} 元（{pct:+.2f}%）</h3>
                <p style="color:#94a3b8;margin:8px 0 0 0;line-height:1.8">
                    成本：{p_c} × {p_n:.0f} 股 = {tc:,.0f} 元　｜　
                    現值：{cp_} × {p_n:.0f} 股 = {cv:,.0f} 元<br>
                    每股{'獲利' if pnl>=0 else '虧損'}：{cp_-p_c:+.2f} 元　｜　
                    持有 {hold_days} 天　｜　年化報酬：{annual_rtn:+.1f}%<br>
                    台股：持有約 {lots:.1f} 張（1張=1000股）
                </p>
            </div>""", unsafe_allow_html=True)

            if st.session_state.logged_in:
                if st.button("💾 儲存到持股記錄", key="save_portfolio"):
                    db_save_portfolio(st.session_state.user_id, ps_, p_c, p_n, "", str(p_d))
                    st.session_state.portfolio[ps_] = {"cost": p_c, "shares": p_n, "note": "", "buy_date": str(p_d)}
                    st.success("✅ 已儲存到雲端")
            else:
                st.info("💡 登入帳號後可永久儲存持股記錄")

    # 持股記錄總覽
    if st.session_state.portfolio:
        st.divider()
        st.markdown("### 📋 我的持股記錄")
        pr_rows = []
        total_cost_all = 0; total_val_all = 0
        for ps2, pd2 in st.session_state.portfolio.items():
            try:
                hh2 = yf.Ticker(ps2).history(period="2d")
                if not hh2.empty:
                    cp2 = round(float(hh2["Close"].iloc[-1]), 2)
                    pnl2 = round((cp2 - pd2["cost"]) / max(pd2["cost"],0.01) * 100, 2)
                    cost_total = round(pd2["cost"] * pd2["shares"], 0)
                    val_total  = round(cp2 * pd2["shares"], 0)
                    buy_d = pd2.get("buy_date","")
                    if buy_d:
                        try:
                            hd = (date.today() - date.fromisoformat(buy_d)).days
                            hold_str = f"{hd}天"
                        except: hold_str = "-"
                    else: hold_str = "-"
                    pr_rows.append({
                        "代號": ps2, "成本": pd2["cost"], "現價": cp2,
                        "損益%": f"{pnl2:+.2f}%",
                        "總損益": f"{val_total-cost_total:+,.0f}",
                        "股數": pd2["shares"], "持有": hold_str,
                    })
                    total_cost_all += cost_total
                    total_val_all  += val_total
            except: pass

        if pr_rows:
            st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)
            total_pnl = total_val_all - total_cost_all
            total_pct = round(total_pnl / max(total_cost_all, 1) * 100, 2)
            st.metric("📊 持股組合總損益",
                      f"{total_pnl:+,.0f} 元",
                      delta=f"{total_pct:+.2f}%")

        if st.button("🗑️ 清空持股記錄"):
            if st.session_state.logged_in:
                for s in list(st.session_state.portfolio.keys()):
                    db_del_portfolio(st.session_state.user_id, s)
            st.session_state.portfolio = {}
            st.rerun()

# 頁尾
st.divider()
st.caption("📈 股市小白分析系統 Pro | AI即時搜尋 × 15項指標 × ATR明日沙盤推演 × 入場策略 × 帳號雲端記憶 | ⚠️ 僅供學習參考，不構成投資建議")