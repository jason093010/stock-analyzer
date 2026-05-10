import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from google import genai
from google.genai import types as genai_types
import time
from datetime import datetime
import hashlib

# ═══════════════════════════════════════
# 頁面設定
# ═══════════════════════════════════════
st.set_page_config(
    page_title="股市小白分析系統 Pro",
    page_icon="📈",
    layout="wide"
)

# ═══════════════════════════════════════
# Supabase 初始化（若未設定則用本地模式）
# ═══════════════════════════════════════
HAS_DB = False
try:
    from supabase import create_client
    _url = st.secrets.get("SUPABASE_URL","")
    _key = st.secrets.get("SUPABASE_KEY","")
    if _url and _key:
        _supabase = create_client(_url, _key)
        HAS_DB = True
except:
    pass

# ═══════════════════════════════════════
# CSS 樣式
# ═══════════════════════════════════════
st.markdown("""
<style>
@media (max-width:768px){
    h1{font-size:1.2rem!important}
    h3{font-size:0.95rem!important}
    .stButton button{font-size:11px!important}
}
.score-card{
    background:linear-gradient(135deg,#1e1e2e,#2a2a3e);
    border-radius:16px;padding:20px;text-align:center;
    border:1px solid #3a3a5e;margin-bottom:12px;
}
.big-score{font-size:4rem;font-weight:900;line-height:1}
.status-card{
    background:#1e1e2e;border-radius:12px;padding:18px;
    margin:10px 0;border-left:5px solid #7c3aed;
}
.entry-card{
    background:linear-gradient(135deg,#1a3a1a,#1e2e1e);
    border-radius:12px;padding:18px;margin:10px 0;
    border:1px solid #2a5a2a;
}
.stop-card{
    background:#3a1a1a;border-radius:12px;padding:18px;
    margin:10px 0;border:1px solid #5a2a2a;
}
.target-card{
    background:#1a2a3a;border-radius:12px;padding:18px;
    margin:10px 0;border:1px solid #2a4a6a;
}
.news-card{
    background:#1e1e2e;border-radius:8px;padding:12px 16px;
    margin:6px 0;border-left:3px solid #42A5F5;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════
# Session State
# ═══════════════════════════════════════
_defaults = {
    "user_id":None,"username":None,"logged_in":False,
    "watchlist":[],"alerts":{},"portfolio":{},"quick_sym":"",
}
for k,v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════════════════════
# 名詞解釋資料庫
# ═══════════════════════════════════════
GLOSSARY = {
    "多頭 📈":"市場看漲，大家都在買，股價往上走。\n就像牛用角往上頂，牛市=上漲市場。",
    "空頭 📉":"市場看跌，大家都在賣，股價往下走。\n就像熊用爪子往下拍，熊市=下跌市場。",
    "超買 🔴":"股價漲太快太多，短期可能休息甚至回跌。\n就像人跑太快需要停下喘口氣。",
    "超賣 🟢":"股價跌太快太多，可能跌過頭，有機會反彈。\n就像橡皮筋拉太緊會彈回來。",
    "均線 MA":"把過去N天收盤價取平均畫成的線。\nMA5=5日 MA20=月線 MA60=季線\n股價在均線上方=強勢；在下方=弱勢。",
    "布林通道":"股價的「正常波動範圍」。\n上軌=過熱 中軌=MA20 下軌=超賣\n通道收窄=大行情即將來臨。",
    "RSI 強弱":"衡量漲跌力道，0~100。\n>70=超買 <30=超賣 50附近=多空平衡。",
    "Stochastic KD":"衡量現價在近期高低點中的位置。\nK>80=超買 K<20=超賣。",
    "MACD 動能":"判斷動能加速或減速。\n柱狀圖由負轉正=動能轉強；由正轉負=動能轉弱。",
    "ATR 波幅":"每天平均波動金額。\nATR高=波動大風險高；ATR低=比較穩適合新手。",
    "OBV 能量潮":"把成交量方向累計的指標。\nOBV上升=買氣強勁；OBV下降=賣壓沉重。",
    "Williams %R":"超買超賣確認指標，-20以上=超買，-80以下=超賣。",
    "布林寬度":"布林通道的寬窄程度。越窄=大行情即將爆發。",
    "支撐":"股價跌到這裡會停下反彈，就像地板。",
    "壓力":"股價漲到這裡會遇到阻力，就像天花板。",
    "費波那契":"根據數學比例的支撐壓力位。\n0.382和0.618是最重要的兩個關鍵點。",
    "成交量":"今天買賣了幾張。\n量大+價漲=真漲；量小+價漲=假漲；量大+價跌=有人出貨。",
    "本益比 PE":"花多少錢買1元獲利。PE=20代表20年回本，越低可能越便宜。",
    "股息殖利率":"每年配息÷股價。5%=每100元每年配5元。",
    "Beta 係數":"與大盤連動程度。Beta=1.5=大盤漲1%它漲1.5%，跌也更猛。",
    "停損":"當股價跌到某個價位就認賠賣出，保護本金的安全線。",
    "停利":"當股價漲到目標就獲利賣出，鎖住獲利。",
    "風險報酬比":"預期獲利÷預期虧損。3:1=賺3元才冒1元風險，越高越划算。",
    "ROE":"股東權益報酬率，公司用股東的錢賺了多少%，越高越好。",
}

# ═══════════════════════════════════════
# 熱門股票清單
# ═══════════════════════════════════════
TW_HOT = {
    "科技":  [("2330","台積電"),("2454","聯發科"),("2303","聯電"),("3711","日月光")],
    "ETF":   [("0050","台灣50"),("0056","高股息"),("00878","永續高息"),("00929","科技優息")],
    "金融":  [("2882","國泰金"),("2881","富邦金"),("2891","中信金"),("2884","玉山金")],
    "傳產":  [("1301","台塑"),("2002","中鋼"),("2412","中華電"),("1216","統一")],
}
US_HOT = {
    "科技":  [("AAPL","蘋果"),("MSFT","微軟"),("NVDA","輝達"),("GOOGL","Google")],
    "AI":    [("AMD","超微"),("TSM","台積電"),("SMCI","超微電腦"),("PLTR","Palantir")],
    "ETF":   [("SPY","S&P500"),("QQQ","那斯達克"),("VT","全球"),("ARKK","方舟")],
    "其他":  [("TSLA","特斯拉"),("AMZN","亞馬遜"),("META","Meta"),("NFLX","Netflix")],
}

# ═══════════════════════════════════════
# 資料庫函數（Supabase）
# ═══════════════════════════════════════
def make_uid(username:str, pin:str)->str:
    return hashlib.sha256(f"{username.lower()}:{pin}".encode()).hexdigest()[:16]

def db_load_watchlist(uid:str)->list:
    if not HAS_DB: return st.session_state.watchlist
    try:
        r = _supabase.table("watchlists").select("symbol").eq("user_id",uid).execute()
        return [x["symbol"] for x in r.data]
    except: return []

def db_add_watch(uid:str, sym:str):
    if not HAS_DB: return
    try:
        ex = _supabase.table("watchlists").select("id").eq("user_id",uid).eq("symbol",sym).execute()
        if not ex.data:
            _supabase.table("watchlists").insert({"user_id":uid,"symbol":sym}).execute()
    except: pass

def db_del_watch(uid:str, sym:str):
    if not HAS_DB: return
    try: _supabase.table("watchlists").delete().eq("user_id",uid).eq("symbol",sym).execute()
    except: pass

def db_load_alerts(uid:str)->dict:
    if not HAS_DB: return st.session_state.alerts
    try:
        r = _supabase.table("alerts").select("*").eq("user_id",uid).execute()
        return {x["symbol"]:{"above":x.get("above_price"),"below":x.get("below_price")} for x in r.data}
    except: return {}

def db_save_alert(uid:str, sym:str, above:float, below:float):
    if not HAS_DB: return
    try:
        ex = _supabase.table("alerts").select("id").eq("user_id",uid).eq("symbol",sym).execute()
        d = {"user_id":uid,"symbol":sym,"above_price":above or None,"below_price":below or None}
        if ex.data: _supabase.table("alerts").update(d).eq("user_id",uid).eq("symbol",sym).execute()
        else: _supabase.table("alerts").insert(d).execute()
    except: pass

def db_load_portfolio(uid:str)->dict:
    if not HAS_DB: return st.session_state.portfolio
    try:
        r = _supabase.table("portfolio").select("*").eq("user_id",uid).execute()
        return {x["symbol"]:{"cost":x["cost_price"],"shares":x["shares"],"note":x.get("note","")} for x in r.data}
    except: return {}

def db_save_portfolio(uid:str, sym:str, cost:float, shares:float, note:str=""):
    if not HAS_DB: return
    try:
        ex = _supabase.table("portfolio").select("id").eq("user_id",uid).eq("symbol",sym).execute()
        d = {"user_id":uid,"symbol":sym,"cost_price":cost,"shares":shares,"note":note}
        if ex.data: _supabase.table("portfolio").update(d).eq("user_id",uid).eq("symbol",sym).execute()
        else: _supabase.table("portfolio").insert(d).execute()
    except: pass

def db_del_portfolio(uid:str, sym:str):
    if not HAS_DB: return
    try: _supabase.table("portfolio").delete().eq("user_id",uid).eq("symbol",sym).execute()
    except: pass

# ═══════════════════════════════════════
# 股票代號處理
# ═══════════════════════════════════════
def get_sym(raw:str, market:str)->str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"):
        return raw + ".TW"
    return raw

# ═══════════════════════════════════════
# 數據抓取（5分鐘快取）
# ═══════════════════════════════════════
@st.cache_data(ttl=300)
def fetch_data(symbol:str, period:str):
    for i in range(3):
        try:
            t = yf.Ticker(symbol)
            h = t.history(period=period)
            info = t.info
            if h.empty: return None,None,"查無此股票代號"
            return h, info, None
        except Exception as e:
            if i==2: return None,None,f"抓取失敗：{e}"
            time.sleep(1)

# ═══════════════════════════════════════
# 核心技術指標計算（15+ 指標）
# ═══════════════════════════════════════
def calc_indicators(hist:pd.DataFrame)->dict:
    c = hist["Close"].squeeze()
    h = hist["High"].squeeze()
    l = hist["Low"].squeeze()
    v = hist["Volume"].squeeze()
    n = len(c)

    # 均線
    ma5   = c.rolling(5).mean()
    ma10  = c.rolling(10).mean()
    ma20  = c.rolling(20).mean()
    ma60  = c.rolling(60).mean()
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()

    # MACD
    macd      = ema12 - ema26
    macd_sig  = macd.ewm(span=9).mean()
    macd_hist = macd - macd_sig

    # RSI
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100/(1+gain/loss.replace(0,float("nan"))))

    # Stochastic RSI
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    stoch_k = 100*(rsi-rsi_min)/(rsi_max-rsi_min+1e-10)
    stoch_d = stoch_k.rolling(3).mean()

    # Bollinger Bands
    bb_mid   = c.rolling(20).mean()
    bb_std   = c.rolling(20).std()
    bb_upper = bb_mid + 2*bb_std
    bb_lower = bb_mid - 2*bb_std
    bb_width = (bb_upper-bb_lower)/bb_mid*100
    bb_pct   = (c-bb_lower)/(bb_upper-bb_lower+1e-10)*100

    # ATR
    tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # OBV
    obv = (v*((c.diff()>0).astype(int)*2-1)).fillna(0).cumsum()

    # Williams %R
    hh = h.rolling(14).max()
    ll = l.rolling(14).min()
    wr = -100*(hh-c)/(hh-ll+1e-10)

    # VWAP（20日近似）
    tp   = (h+l+c)/3
    vwap = (tp*v).rolling(20).sum()/v.rolling(20).sum()

    def _last(s):
        try: return float(s.iloc[-1]) if not pd.isna(s.iloc[-1]) else 0.0
        except: return 0.0

    ind = {
        # 價格
        "price"      : round(_last(c),2),
        "change_pct" : round((_last(c)-float(c.iloc[-2]))/float(c.iloc[-2])*100,2),
        "change_5d"  : round((_last(c)-float(c.iloc[-6]))/float(c.iloc[-6])*100,2) if n>5 else 0,
        "change_1m"  : round((_last(c)-float(c.iloc[-21]))/float(c.iloc[-21])*100,2) if n>21 else 0,
        # 均線
        "ma5"  : round(_last(ma5),2),
        "ma10" : round(_last(ma10),2),
        "ma20" : round(_last(ma20),2),
        "ma60" : round(_last(ma60) if n>=60 else _last(ma20),2),
        "vwap" : round(_last(vwap),2),
        # 動能
        "rsi"       : round(_last(rsi),1),
        "stoch_k"   : round(_last(stoch_k),1),
        "stoch_d"   : round(_last(stoch_d),1),
        "macd"      : round(_last(macd),4),
        "macd_sig"  : round(_last(macd_sig),4),
        "macd_hist" : round(_last(macd_hist),4),
        "williams_r": round(_last(wr),1),
        # 波動
        "atr"      : round(_last(atr),2),
        "bb_upper" : round(_last(bb_upper),2),
        "bb_mid"   : round(_last(bb_mid),2),
        "bb_lower" : round(_last(bb_lower),2),
        "bb_width" : round(_last(bb_width),1),
        "bb_pct"   : round(_last(bb_pct),1),
        # 成交量
        "volume"   : int(_last(v)),
        "vol_ma20" : int(_last(v.rolling(20).mean())),
        "obv"      : round(_last(obv),0),
        # 52週
        "high_52w" : round(float(c.rolling(min(252,n)).max().iloc[-1]),2),
        "low_52w"  : round(float(c.rolling(min(252,n)).min().iloc[-1]),2),
        # 序列（供圖表）
        "_c":c,"_h":h,"_l":l,"_v":v,
        "_rsi":rsi,"_stoch_k":stoch_k,"_stoch_d":stoch_d,
        "_macd":macd,"_macd_sig":macd_sig,"_macd_hist":macd_hist,
        "_bb_upper":bb_upper,"_bb_lower":bb_lower,"_bb_mid":bb_mid,
        "_ma5":ma5,"_ma20":ma20,"_ma60":ma60,"_obv":obv,
    }

    # 量比說明
    vr = ind["volume"]/ind["vol_ma20"] if ind["vol_ma20"]>0 else 1
    ind["vol_ratio"] = round(vr,2)
    if vr>=2.5: ind["vol_desc"] = f"🔥 超級爆量！成交量是均量的 {vr:.1f} 倍，市場極度關注"
    elif vr>=1.5: ind["vol_desc"] = f"📢 明顯放量（{vr:.1f} 倍），市場積極參與"
    elif vr>=0.8: ind["vol_desc"] = f"📊 量能正常（{vr:.1f} 倍），市場熱度穩定"
    else: ind["vol_desc"] = f"😴 成交縮量（{vr:.1f} 倍），交投清淡，訊號可信度低"

    # 52週位置
    pr = ind["high_52w"]-ind["low_52w"]
    pos = (ind["price"]-ind["low_52w"])/pr*100 if pr>0 else 50
    ind["position_52w"] = round(pos,1)
    if pos>=90: ind["position_desc"] = f"接近52週高點（{pos:.0f}%），近期漲幅已大，需謹慎"
    elif pos>=70: ind["position_desc"] = f"52週相對高位（{pos:.0f}%），仍有壓力"
    elif pos<=10: ind["position_desc"] = f"接近52週低點（{pos:.0f}%），相對便宜但需確認趨勢"
    elif pos<=30: ind["position_desc"] = f"52週相對低位（{pos:.0f}%），有撿便宜機會"
    else: ind["position_desc"] = f"52週中間區域（{pos:.0f}%），位置相對中性"

    # RSI說明
    r = ind["rsi"]
    if r>=80: ind["rsi_desc"] = f"⚠️ RSI {r}，嚴重超買，短線風險極高"
    elif r>=70: ind["rsi_desc"] = f"⚠️ RSI {r}，超買區，留意回調"
    elif r<=20: ind["rsi_desc"] = f"💡 RSI {r}，嚴重超賣，留意強力反彈"
    elif r<=30: ind["rsi_desc"] = f"💡 RSI {r}，超賣區，有反彈機會"
    elif r>=55: ind["rsi_desc"] = f"✅ RSI {r}，多方偏強"
    elif r<=45: ind["rsi_desc"] = f"⚠️ RSI {r}，空方偏強"
    else: ind["rsi_desc"] = f"➡️ RSI {r}，多空均衡"

    # 技術狀態（多條件複合判斷）
    r_val = ind["rsi"]
    k_val = ind["stoch_k"]
    m_val = ind["macd_hist"]
    if ind["ma5"]>ind["ma20"]>ind["ma60"] and r_val>55 and m_val>0:
        ind["status"]="強勢多頭 📈"; ind["sc"]="🟢"
        ind["status_desc"]="均線多頭排列＋RSI偏強＋MACD正值，三重確認多頭格局。"
    elif ind["ma5"]<ind["ma20"]<ind["ma60"] and r_val<45 and m_val<0:
        ind["status"]="強勢空頭 📉"; ind["sc"]="🔴"
        ind["status_desc"]="均線空頭排列＋RSI偏弱＋MACD負值，三重確認空頭格局。"
    elif r_val<=30 and k_val<20:
        ind["status"]="雙重超賣，留意反彈 🟡"; ind["sc"]="🟡"
        ind["status_desc"]="RSI與Stochastic雙雙超賣，反彈機率升高，但需量能確認。"
    elif r_val>=70 and k_val>80:
        ind["status"]="雙重超買，注意回調 🟡"; ind["sc"]="🟡"
        ind["status_desc"]="RSI與Stochastic雙雙超買，短線獲利了結壓力大。"
    elif abs(ind["ma5"]-ind["ma20"])/ind["price"]<0.015:
        ind["status"]="均線糾結蓄勢 ⚪"; ind["sc"]="⚪"
        ind["status_desc"]="均線纏繞，多空拉鋸，等待突破方向，大行情可能即將爆發。"
    elif ind["ma5"]>ind["ma20"] and r_val>50:
        ind["status"]="短線偏多 🔵"; ind["sc"]="🔵"
        ind["status_desc"]="短均線在長均線上方，RSI偏強，短線多方略佔優勢。"
    else:
        ind["status"]="弱勢盤整 🟠"; ind["sc"]="🟠"
        ind["status_desc"]="股價走勢疲軟，方向不明，建議觀望等待明確訊號。"

    return ind

# ═══════════════════════════════════════
# 綜合評分系統（0-100）
# ═══════════════════════════════════════
def calc_score(ind:dict, info:dict)->dict:
    # 趨勢（30分）
    trend=0
    if ind["ma5"]>ind["ma20"]: trend+=8
    if ind["ma20"]>ind["ma60"]: trend+=8
    if ind["price"]>ind["ma20"]: trend+=7
    if ind["macd_hist"]>0: trend+=7
    trend=min(30,trend)

    # 動能（25分）
    mom=0
    r=ind["rsi"]; k=ind["stoch_k"]; wr=ind["williams_r"]
    if 50<=r<=70: mom+=10
    elif 40<=r<50: mom+=5
    elif r<30: mom+=8
    elif r>70: mom+=3
    if 40<=k<=80: mom+=8
    elif k<20: mom+=5
    if wr>-50: mom+=7
    mom=min(25,mom)

    # 量能（20分）
    vol=0; vr=ind["vol_ratio"]
    if vr>=1.5 and ind["change_pct"]>0: vol=20
    elif vr>=1.2 and ind["change_pct"]>0: vol=15
    elif 0.8<=vr<=1.5: vol=10
    else: vol=5
    vol=min(20,vol)

    # 位置（15分）
    pos=ind["position_52w"]
    if 30<=pos<=70: psc=15
    elif 20<=pos<30 or 70<pos<=80: psc=10
    elif pos<20: psc=12
    else: psc=4
    psc=min(15,psc)

    # 布林位置（10分）
    bp=ind["bb_pct"]
    if 20<=bp<=80: bsc=10
    elif bp<20: bsc=7
    else: bsc=3
    bsc=min(10,bsc)

    total=trend+mom+vol+psc+bsc
    if total>=80: grade,gc="A（優秀）","#00cc66"
    elif total>=65: grade,gc="B（良好）","#66cc00"
    elif total>=50: grade,gc="C（普通）","#ffaa00"
    elif total>=35: grade,gc="D（偏弱）","#ff6600"
    else: grade,gc="E（警示）","#ff3333"

    return {"total":total,"grade":grade,"gc":gc,
            "trend":trend,"mom":mom,"vol":vol,"pos":psc,"bb":bsc}

# ═══════════════════════════════════════
# 入場策略計算
# ═══════════════════════════════════════
def calc_entry(ind:dict, hist:pd.DataFrame)->dict:
    c=ind["_c"]; h=ind["_h"]; l=ind["_l"]
    price=ind["price"]; atr=ind["atr"]
    n=len(c)

    ph = float(h.iloc[-min(60,n):].max())
    pl = float(l.iloc[-min(60,n):].min())
    fr = ph-pl

    fibs={
        "0.236": round(ph-0.236*fr,2),
        "0.382": round(ph-0.382*fr,2),
        "0.500": round(ph-0.500*fr,2),
        "0.618": round(ph-0.618*fr,2),
        "0.786": round(ph-0.786*fr,2),
    }

    sup1 = round(float(l.iloc[-20:].min()),2)
    sup2 = round(float(l.iloc[-min(60,n):].min()),2)
    res1 = round(float(h.iloc[-20:].max()),2)
    res2 = round(float(h.iloc[-min(60,n):].max()),2)

    con_buy  = round(min(sup1, fibs["0.382"]),2)
    mod_buy  = round((sup1+ind["ma20"])/2,2)
    agg_buy  = round(price*0.99,2)

    sl_tight  = round(price-1.5*atr,2)
    sl_normal = round(price-2.5*atr,2)
    sl_wide   = round(sup2*0.97,2)

    tp1 = round(price+2*atr,2)
    tp2 = round(price+4*atr,2)
    tp3 = round(res2*1.02,2)

    rr = round((tp1-mod_buy)/(mod_buy-sl_normal+0.01),2)

    return {
        "fibs":fibs,"sup1":sup1,"sup2":sup2,"res1":res1,"res2":res2,
        "con_buy":con_buy,"mod_buy":mod_buy,"agg_buy":agg_buy,
        "sl_tight":sl_tight,"sl_normal":sl_normal,"sl_wide":sl_wide,
        "tp1":tp1,"tp2":tp2,"tp3":tp3,"rr":rr,"ph":ph,"pl":pl,
    }

# ═══════════════════════════════════════
# Gemini AI（含 Google 即時搜尋）
# ═══════════════════════════════════════
def call_ai(api_key:str, prompt:str, use_search:bool=False)->str:
    client = genai.Client(api_key=api_key)
    models = [
        ("gemini-2.5-flash","Gemini 2.5 Flash"),
        ("gemini-2.0-flash","Gemini 2.0 Flash（備用）"),
        ("gemini-2.0-flash-lite","Gemini Flash Lite（備用）"),
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
            tag = "＋🔍即時搜尋" if use_search else ""
            return f"> 🤖 {mname}{tag}\n\n{resp.text}"
        except Exception as e:
            if any(k in str(e) for k in ["quota","429","RESOURCE_EXHAUSTED","404","not found"]):
                last_err=str(e)[:80]; continue
            raise
    raise Exception(f"所有模型均無法使用：{last_err}")

def ai_full_report(ind:dict, info:dict, sym:str, api_key:str, entry:dict, score:dict)->str:
    co   = info.get("longName") or info.get("shortName") or sym
    sec  = info.get("sector","未知")
    pe   = info.get("trailingPE","N/A")
    pb   = info.get("priceToBook","N/A")
    eps  = info.get("trailingEps","N/A")
    dy   = info.get("dividendYield",0)
    if isinstance(dy,float): dy=f"{dy*100:.1f}%"
    beta = info.get("beta","N/A")
    tp   = info.get("targetMeanPrice","N/A")
    rec  = info.get("recommendationKey","N/A")
    mc   = info.get("marketCap","N/A")
    if isinstance(mc,(int,float)): mc=f"約{mc/1e8:.0f}億" if mc>1e8 else f"{mc:,.0f}"
    roe  = info.get("returnOnEquity","N/A")
    gm   = info.get("grossMargins","N/A")
    pm   = info.get("profitMargins","N/A")

    prompt = f"""你是一位同時精通技術分析、基本面、籌碼面與宏觀經濟的頂級金融分析師，同時也是最擅長用白話文教導股市新手的老師。

請先即時搜尋「{co}（{sym}）」的最新新聞、產業動態、宏觀政策等資訊，然後綜合所有數據進行全面分析。

═══ 基本資料 ═══
公司：{co}（{sym}）| 產業：{sec} | 市值：{mc}
PE：{pe} | PB：{pb} | EPS：{eps} | 股息率：{dy}
ROE：{roe} | 毛利率：{gm} | 淨利率：{pm}
Beta：{beta} | 分析師目標價：{tp} | 評級：{rec}

═══ 技術指標（15項）═══
現價：{ind['price']} | 今日：{ind['change_pct']}% | 5日：{ind['change_5d']}% | 月：{ind['change_1m']}%
MA5：{ind['ma5']} | MA20：{ind['ma20']} | MA60：{ind['ma60']} | VWAP：{ind['vwap']}
RSI：{ind['rsi']} | Stoch K：{ind['stoch_k']} D：{ind['stoch_d']} | Williams%R：{ind['williams_r']}
MACD：{ind['macd']} | Signal：{ind['macd_sig']} | Hist：{ind['macd_hist']}
布林上：{ind['bb_upper']} 中：{ind['bb_mid']} 下：{ind['bb_lower']} | BB%：{ind['bb_pct']:.0f}%
ATR：{ind['atr']} | OBV趨勢：{'上升（買氣增強）' if ind['obv']>0 else '下降（賣壓增加）'}
52週高：{ind['high_52w']} 低：{ind['low_52w']} | 位置：{ind['position_52w']}%
{ind['vol_desc']}
狀態：{ind['status']}

═══ 入場參考 ═══
近期高：{entry['ph']} 近期低：{entry['pl']}
支撐1：{entry['sup1']} 支撐2：{entry['sup2']}
壓力1：{entry['res1']} 壓力2：{entry['res2']}
Fib 0.382：{entry['fibs']['0.382']} | 0.618：{entry['fibs']['0.618']}
建議買入（保守）：{entry['con_buy']} 穩健：{entry['mod_buy']} 積極：{entry['agg_buy']}
停損（標準）：{entry['sl_normal']} | 目標1：{entry['tp1']} 目標2：{entry['tp2']}
風險報酬比：{entry['rr']}:1

═══ 綜合評分 ═══
{score['total']}/100（{score['grade']}）
趨勢{score['trend']}/30 | 動能{score['mom']}/25 | 量能{score['vol']}/20 | 位置{score['pos']}/15 | 布林{score['bb']}/10

請搜尋最新資訊後，用繁體中文輸出以下完整報告：

## 🌍 宏觀環境與時事影響
（搜尋並說明目前總體經濟環境、聯準會政策、匯率、地緣政治等對此股的影響）

## 📰 公司與產業最新動態
（搜尋最新新聞，說明公司本身及所在產業的最新發展）

## 🏢 公司白話介紹
（這家公司是做什麼的？在產業中的地位？新手也能看懂）

## 📊 技術面完整解讀
**均線系統：**（均線排列現況，多空力道）
**RSI + Stochastic：**（雙重動能指標解讀）
**MACD動能：**（動能趨勢轉折）
**布林通道：**（現價位置，波動狀態）
**Williams %R：**（超買超賣確認）
**OBV能量潮：**（資金流向）
**量能分析：**（量價關係解讀）

## 💰 入場策略（僅供參考，不構成投資建議）
**建議觀察買入區：**（不同風險承受度的入場策略）
**停損設定：**（為什麼要設停損，建議設在哪裡）
**目標價位：**（短中長期目標，以及背後邏輯）
**風險報酬比 {entry['rr']}:1 的意義：**（用白話解釋這個數字）
**建議倉位：**（新手建議投入比例）

## 🎯 短中期走勢研判
- 短期（1~2週）：（具體說明理由）
- 中期（1~3月）：（具體說明理由）

## ⚠️ 主要風險（條列4~5點，含新聞面風險）

## 📌 小白總結
（用最簡單的方式說明：這支股票現在適不適合關注？評分{score['total']}分代表什麼？信心程度：高/中/低，原因是？）

## 📖 名詞對照快速查詢
（整理本報告出現的所有專業術語，做成白話對照表）

重要規則：所有術語第一次出現必須加白話解釋。禁止使用「一定」「保證」「必漲」「必跌」。所有入場建議需加「僅供參考，不構成投資建議」。"""

    return call_ai(api_key, prompt, use_search=True)

def ai_news(company:str, sym:str, sector:str, api_key:str)->str:
    prompt = f"""你是頂級財經分析師，請立即搜尋所有與「{company}（{sym}）」相關的最新資訊。

必須搜尋：
1. {company} 過去1個月最新新聞
2. {sector} 產業最新動態
3. 影響此股的宏觀政策（聯準會、各國央行、貿易政策）
4. 川普政策對此股或產業的影響
5. 地緣政治風險（台海、俄烏等）
6. 競爭對手最新動態
7. 分析師最新評級變化
8. 社群媒體討論熱度與情緒

搜尋完成後，用繁體中文輸出：

## 🌍 宏觀環境（對此股的直接影響）
（聯準會、川普政策、各國央行、匯率變動、貿易戰等）

## 📰 公司最新重要新聞
（財報、人事、新產品、合作案、重大事件）

## 🏭 產業鏈與競爭動態
（整個產業的趨勢、競爭對手動態）

## 💬 市場情緒與分析師觀點
（分析師評級變化、目標價調整、機構動向）

## ⚡ 潛在黑天鵝風險
（任何可能突然衝擊股價的風險事件）

## 🎯 新聞面綜合評分
（正面/負面/中立？影響力強/中/弱？說明理由）

## ⚠️ 新手看新聞常犯的錯誤
（看到這些新聞，新手容易有什麼衝動？正確應對方式是什麼？）

所有分析必須基於實際搜尋到的資訊。找不到的資訊請直接說明。
禁止使用「一定」「保證」「必漲」「必跌」。"""

    return call_ai(api_key, prompt, use_search=True)

# ═══════════════════════════════════════
# 圖表建立
# ═══════════════════════════════════════
def build_chart(hist:pd.DataFrame, ind:dict, entry:dict, sym:str):
    idx = hist.index
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.50,0.18,0.17,0.15],
        subplot_titles=[
            "K線圖 + 均線 + 布林通道（紅=漲、綠=跌）",
            "成交量（紅=量漲、綠=量跌）",
            "RSI 強弱 + Stochastic（70過熱、30過冷）",
            "MACD 動能（柱子向上=漲勢、向下=跌勢）"
        ]
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=idx, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name="K線",
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a"
    ), row=1, col=1)

    # 均線
    for key,color,name in [("_ma5","#FFA726","MA5"),("_ma20","#42A5F5","MA20"),("_ma60","#AB47BC","MA60")]:
        fig.add_trace(go.Scatter(x=idx,y=ind[key],line=dict(color=color,width=1.3),name=name), row=1,col=1)

    # 布林通道
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_upper"],line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林上軌"), row=1,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_bb_lower"],line=dict(color="rgba(255,235,59,0.5)",width=1,dash="dot"),name="布林下軌",
                             fill="tonexty",fillcolor="rgba(255,235,59,0.03)"), row=1,col=1)

    # 支撐壓力
    fig.add_hline(y=entry["sup1"],line_dash="dash",line_color="rgba(38,166,154,0.7)",
                  annotation_text=f"支撐{entry['sup1']}",row=1,col=1)
    fig.add_hline(y=entry["res1"],line_dash="dash",line_color="rgba(239,83,80,0.7)",
                  annotation_text=f"壓力{entry['res1']}",row=1,col=1)
    fig.add_hline(y=entry["mod_buy"],line_dash="dot",line_color="rgba(100,220,100,0.8)",
                  annotation_text=f"參考買入{entry['mod_buy']}",row=1,col=1)

    # 成交量
    vc = ["#ef5350" if c>=o else "#26a69a" for c,o in zip(hist["Close"],hist["Open"])]
    fig.add_trace(go.Bar(x=idx,y=hist["Volume"],marker_color=vc,showlegend=False), row=2,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_v"].rolling(20).mean(),
                             line=dict(color="#FFA726",width=1),name="均量",showlegend=False), row=2,col=1)

    # RSI + Stochastic
    fig.add_trace(go.Scatter(x=idx,y=ind["_rsi"],line=dict(color="#FF7043",width=1.5),name="RSI",showlegend=False), row=3,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_stoch_k"],line=dict(color="#66BB6A",width=1,dash="dot"),name="Stoch K",showlegend=False), row=3,col=1)
    for lv,lc in [(70,"rgba(239,83,80,0.4)"),(30,"rgba(38,166,154,0.4)"),(50,"rgba(150,150,150,0.3)")]:
        fig.add_hline(y=lv,line_dash="dash",line_color=lc,row=3,col=1)

    # MACD
    mc=[("#ef5350" if x>=0 else "#26a69a") for x in ind["_macd_hist"]]
    fig.add_trace(go.Bar(x=idx,y=ind["_macd_hist"],marker_color=mc,showlegend=False), row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd"],line=dict(color="#42A5F5",width=1),showlegend=False), row=4,col=1)
    fig.add_trace(go.Scatter(x=idx,y=ind["_macd_sig"],line=dict(color="#FF7043",width=1),showlegend=False), row=4,col=1)

    fig.update_layout(
        title=f"{sym} 進階技術分析圖",
        height=820, xaxis_rangeslider_visible=False,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font_color="#FFFFFF", legend=dict(orientation="h",y=1.02,font_size=11),
        margin=dict(l=50,r=50,t=80,b=30),
    )
    return fig

# ═══════════════════════════════════════
# 側邊欄
# ═══════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input("🔑 Gemini API 金鑰", type="password", placeholder="AIza...")
    st.caption("金鑰只存在瀏覽器，不會被儲存")

    st.divider()
    st.header("👤 個人帳號")

    if not st.session_state.logged_in:
        with st.expander("🔐 登入 / 建立帳號", expanded=True):
            uname = st.text_input("帳號名稱（自訂）", placeholder="例如：jason123", key="lu")
            upin  = st.text_input("密碼", type="password", placeholder="設定密碼", key="lp")
            ca, cb = st.columns(2)
            with ca:
                if st.button("🔑 登入", use_container_width=True):
                    if uname.strip() and upin.strip():
                        uid = make_uid(uname.strip(), upin.strip())
                        st.session_state.user_id   = uid
                        st.session_state.username  = uname.strip()
                        st.session_state.logged_in = True
                        st.session_state.watchlist = db_load_watchlist(uid)
                        st.session_state.alerts    = db_load_alerts(uid)
                        st.session_state.portfolio = db_load_portfolio(uid)
                        st.success(f"✅ 歡迎，{uname}！")
                        st.rerun()
            with cb:
                if st.button("✨ 建立", use_container_width=True):
                    if uname.strip() and upin.strip():
                        uid = make_uid(uname.strip(), upin.strip())
                        st.session_state.user_id   = uid
                        st.session_state.username  = uname.strip()
                        st.session_state.logged_in = True
                        st.success(f"✅ 帳號已建立！")
                        st.rerun()
            if HAS_DB: st.caption("✅ 雲端模式：資料永久保存")
            else: st.caption("⚠️ 本機模式：重新整理後消失（需設定 Supabase）")
    else:
        st.success(f"👤 {st.session_state.username}")
        st.caption("✅ 雲端保存" if HAS_DB else "⚠️ 本機模式")
        if st.button("🚪 登出", use_container_width=True):
            for k in ["user_id","username","logged_in"]:
                st.session_state[k] = False if k=="logged_in" else None
            st.session_state.watchlist=[]
            st.session_state.alerts={}
            st.session_state.portfolio={}
            st.rerun()

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("股票市場", ["🇹🇼 台股","🇺🇸 美股"])
    period = st.selectbox("分析區間",["3mo","6mo","1y","2y"],index=1,
        format_func=lambda x:{"3mo":"3個月","6mo":"6個月","1y":"1年","2y":"2年"}[x])

    st.divider()
    st.header("⭐ 自選股")
    nw = st.text_input("新增代號", placeholder="輸入代號", key="nw")
    if nw and nw.strip():
        sa = get_sym(nw, market)
        if sa not in st.session_state.watchlist:
            st.session_state.watchlist.append(sa)
            if st.session_state.logged_in: db_add_watch(st.session_state.user_id, sa)
            st.rerun()
    for i, s in enumerate(st.session_state.watchlist):
        c1,c2 = st.columns([4,1])
        c1.write(f"• {s}")
        if c2.button("❌", key=f"dw{i}"):
            if st.session_state.logged_in: db_del_watch(st.session_state.user_id, s)
            st.session_state.watchlist.pop(i)
            st.rerun()

    st.divider()
    st.header("🔔 價格警報")
    as_ = st.text_input("代號", key="as_")
    au  = st.number_input("↑ 漲破提醒", 0.0, step=0.5, key="au_")
    ad  = st.number_input("↓ 跌破提醒", 0.0, step=0.5, key="ad_")
    if st.button("✅ 設定警報", use_container_width=True):
        if as_.strip():
            sa2 = get_sym(as_, market)
            st.session_state.alerts[sa2] = {"above":au or None,"below":ad or None}
            if st.session_state.logged_in: db_save_alert(st.session_state.user_id,sa2,au,ad)
            st.success("✅ 警報已設定")

    st.divider()
    st.header("📖 名詞解釋")
    for term, desc in GLOSSARY.items():
        with st.expander(term): st.info(desc)

# ═══════════════════════════════════════
# 主標題
# ═══════════════════════════════════════
st.title("📈 股市小白分析系統 Pro")
st.caption("AI即時搜尋 × 15項指標 × 入場策略 × 完全白話 × 雲端記憶")

tabs = st.tabs(["🔍 深度分析","⭐ 自選股","📰 即時新聞","🏦 籌碼基本面","⚖️ 股票比較","💼 持股損益"])

# ═══════════════════════════════════════
# TAB 1：深度分析
# ═══════════════════════════════════════
with tabs[0]:
    # 快速選股
    st.markdown("### 🚀 快速選股")
    hot = TW_HOT if "台股" in market else US_HOT
    for cat, stocks in hot.items():
        cols = st.columns(len(stocks))
        for col,(sym_,name_) in zip(cols,stocks):
            if col.button(f"{sym_}\n{name_}",use_container_width=True,key=f"qs_{sym_}"):
                st.session_state.quick_sym = sym_

    st.divider()
    c1,c2 = st.columns([3,1])
    with c1:
        dv = st.session_state.quick_sym or ""
        ph = "例如：2330（台積電）" if "台股" in market else "例如：NVDA（輝達）"
        ticker_in = st.text_input("輸入股票代號", value=dv, placeholder=ph)
    with c2:
        st.write(""); st.write("")
        go_btn = st.button("🔍 開始深度分析", use_container_width=True, type="primary")

    if go_btn and ticker_in.strip():
        if not api_key:
            st.warning("⚠️ 請在左側輸入 Gemini API 金鑰")
            st.stop()

        sym = get_sym(ticker_in, market)
        with st.spinner(f"抓取 {sym} 數據中..."):
            hist, info, err = fetch_data(sym, period)
        if err: st.error(f"❌ {err}"); st.stop()

        ind   = calc_indicators(hist)
        entry = calc_entry(ind, hist)
        score = calc_score(ind, info)
        co    = info.get("longName") or info.get("shortName") or sym

        # 警報檢查
        if sym in st.session_state.alerts:
            a = st.session_state.alerts[sym]
            if a.get("above") and ind["price"]>=a["above"]:
                st.error(f"🔔 警報！{sym} 已漲破 {a['above']}，現價 {ind['price']}")
            if a.get("below") and ind["price"]<=a["below"]:
                st.error(f"🔔 警報！{sym} 已跌破 {a['below']}，現價 {ind['price']}")

        # 標題 + 加入自選
        ct, ca_ = st.columns([5,1])
        with ct: st.subheader(f"📌 {co}（{sym}）")
        with ca_:
            if sym not in st.session_state.watchlist:
                if st.button("⭐ 加入自選", use_container_width=True):
                    st.session_state.watchlist.append(sym)
                    if st.session_state.logged_in: db_add_watch(st.session_state.user_id, sym)
                    st.success("✅ 已加入")

        # 評分卡 + 狀態
        cs_, cs2 = st.columns([1,2])
        with cs_:
            st.markdown(f"""
            <div class="score-card">
                <div style="color:#94a3b8;font-size:13px">綜合健康評分</div>
                <div class="big-score" style="color:{score['gc']}">{score['total']}</div>
                <div style="color:#e2e8f0;font-size:15px;margin-top:6px">{score['grade']}</div>
            </div>
            """, unsafe_allow_html=True)
            st.progress(score["trend"]/30, text=f"趨勢 {score['trend']}/30")
            st.progress(score["mom"]/25,   text=f"動能 {score['mom']}/25")
            st.progress(score["vol"]/20,   text=f"量能 {score['vol']}/20")
            st.progress(score["pos"]/15,   text=f"位置 {score['pos']}/15")
            st.progress(score["bb"]/10,    text=f"布林 {score['bb']}/10")

        with cs2:
            st.markdown(f"""
            <div class="status-card">
                <h3 style="margin:0;color:#e2e8f0">{ind['sc']} 目前狀態：{ind['status']}</h3>
                <p style="margin:8px 0 0 0;color:#94a3b8;font-size:14px">{ind['status_desc']}</p>
            </div>
            """, unsafe_allow_html=True)
            ci = "🔴" if ind["change_pct"]>=0 else "🟢"
            c1_,c2_,c3_ = st.columns(3)
            c1_.metric("💰 現價",  f"{ind['price']}")
            c2_.metric("今日",     f"{ci}{ind['change_pct']}%")
            c3_.metric("本月",     f"{ind['change_1m']}%")
            c4_,c5_,c6_ = st.columns(3)
            c4_.metric("📏 RSI",   f"{ind['rsi']}")
            c5_.metric("📦 量比",  f"{ind['vol_ratio']}x")
            c6_.metric("📐 ATR",   f"{ind['atr']}")

        st.divider()

        # 指標白話說明
        st.markdown("### 🔍 各指標白話解讀")
        ia,ib,ic = st.columns(3)
        with ia:
            st.info(f"**📏 RSI（{ind['rsi']}）**\n\n{ind['rsi_desc']}")
            sk=ind['stoch_k']
            st.info(f"**📊 Stochastic K（{sk}）**\n\n{'⚠️ K>80 超買區，短線過熱' if sk>80 else '💡 K<20 超賣區，留意反彈' if sk<20 else '➡️ 中間區域，方向待確認'}")
        with ib:
            st.info(f"**📦 成交量**\n\n{ind['vol_desc']}")
            bp=ind['bb_pct']
            st.info(f"**📐 布林通道（{bp:.0f}%）**\n\n{'⚠️ 接近上軌，過熱警戒' if bp>80 else '💡 接近下軌，超賣區' if bp<20 else '✅ 在通道中間，相對健康'}")
        with ic:
            st.info(f"**📅 52週位置**\n\n{ind['position_desc']}")
            mh=ind['macd_hist']
            st.info(f"**📡 MACD動能（{mh:.4f}）**\n\n{'📈 柱狀圖為正，上漲動能增強' if mh>0 else '📉 柱狀圖為負，下跌動能增強'}")

        st.divider()

        # 入場策略
        st.markdown("### 💰 入場策略參考")
        st.caption("⚠️ 以下由技術分析自動計算，僅供參考學習，不構成投資建議，請自行判斷")
        e1,e2,e3 = st.columns(3)
        with e1:
            st.markdown(f"""
            <div class="entry-card">
                <div style="color:#66cc66;font-weight:bold;font-size:15px">🎯 參考買入區</div>
                <div style="margin:10px 0;color:#e2e8f0;line-height:1.8">
                    保守型：<b>{entry['con_buy']}</b><br>
                    穩健型：<b>{entry['mod_buy']}</b><br>
                    積極型：<b>{entry['agg_buy']}</b>
                </div>
                <div style="color:#94a3b8;font-size:11px">保守=等更深支撐；積極=現在附近入場</div>
            </div>""", unsafe_allow_html=True)
        with e2:
            st.markdown(f"""
            <div class="stop-card">
                <div style="color:#ff6666;font-weight:bold;font-size:15px">🛡️ 停損參考</div>
                <div style="margin:10px 0;color:#e2e8f0;line-height:1.8">
                    緊（短線）：<b>{entry['sl_tight']}</b><br>
                    標準：<b>{entry['sl_normal']}</b><br>
                    寬（長線）：<b>{entry['sl_wide']}</b>
                </div>
                <div style="color:#94a3b8;font-size:11px">跌破停損線就出場，保護本金</div>
            </div>""", unsafe_allow_html=True)
        with e3:
            st.markdown(f"""
            <div class="target-card">
                <div style="color:#66aaff;font-weight:bold;font-size:15px">🎯 目標價位</div>
                <div style="margin:10px 0;color:#e2e8f0;line-height:1.8">
                    目標1（短）：<b>{entry['tp1']}</b><br>
                    目標2（中）：<b>{entry['tp2']}</b><br>
                    目標3（壓力）：<b>{entry['tp3']}</b>
                </div>
                <div style="color:#94a3b8;font-size:11px">風險報酬比：{entry['rr']}:1（>2為佳）</div>
            </div>""", unsafe_allow_html=True)

        with st.expander("📐 Fibonacci 回撤關鍵支撐壓力位"):
            st.caption(f"計算基準：近期高點 {entry['ph']} → 低點 {entry['pl']}")
            fdf = pd.DataFrame([
                {"回撤比例":"0.236（弱支撐）","價位":entry['fibs']['0.236'],"說明":"下跌力道弱，短線支撐"},
                {"回撤比例":"0.382（強支撐）★","價位":entry['fibs']['0.382'],"說明":"最常見強支撐，技術派愛在此買"},
                {"回撤比例":"0.500（中間位）","價位":entry['fibs']['0.500'],"說明":"心理支撐，多空攻防關鍵"},
                {"回撤比例":"0.618（黃金比例）★","價位":entry['fibs']['0.618'],"說明":"最重要的支撐壓力，黃金分割"},
                {"回撤比例":"0.786（深回撤）","價位":entry['fibs']['0.786'],"說明":"回撤幅度深，測試主要趨勢"},
            ])
            st.dataframe(fdf, use_container_width=True, hide_index=True)

        st.divider()

        # 圖表
        st.markdown("### 📈 進階技術分析圖（含布林通道、支撐壓力、RSI+Stochastic、MACD）")
        st.caption("滑鼠滾輪縮放，拖曳移動時間範圍")
        st.plotly_chart(build_chart(hist, ind, entry, sym), use_container_width=True)

        st.divider()

        # AI報告
        st.markdown("### 🤖 AI 深度分析報告（即時搜尋版）")
        st.caption("Gemini AI 即時搜尋 Google + 分析 15項技術指標 + 入場策略，給你最完整的白話報告")
        with st.spinner("🔍 AI 正在即時搜尋最新資訊並深度分析（約 30~60 秒，請耐心等待）..."):
            try:
                rpt = ai_full_report(ind, info, sym, api_key, entry, score)
                st.markdown(rpt)
            except Exception as e:
                st.error(f"❌ AI 分析失敗：{str(e)}")

        st.divider()
        st.warning("⚠️ **免責聲明**：本系統所有分析與入場建議僅供學習參考，不構成任何投資建議。股市有風險，請獨立判斷並為自己的投資決策負責。")

        with st.expander("🔧 進階：完整原始技術指標數據"):
            raw_df = pd.DataFrame({
                "指標":["現價","MA5","MA20","MA60","VWAP","RSI","Stoch K","Stoch D",
                        "Williams%R","MACD","Signal","Hist","布林上","布林中","布林下",
                        "BB%","ATR","OBV","成交量","20日均量","漲跌幅","52週高","52週低"],
                "數值":[ind["price"],ind["ma5"],ind["ma20"],ind["ma60"],ind["vwap"],
                        ind["rsi"],ind["stoch_k"],ind["stoch_d"],ind["williams_r"],
                        ind["macd"],ind["macd_sig"],ind["macd_hist"],
                        ind["bb_upper"],ind["bb_mid"],ind["bb_lower"],f"{ind['bb_pct']:.0f}%",
                        ind["atr"],ind["obv"],ind["volume"],ind["vol_ma20"],
                        f"{ind['change_pct']}%",ind["high_52w"],ind["low_52w"]]
            })
            st.dataframe(raw_df, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════
# TAB 2：自選股
# ═══════════════════════════════════════
with tabs[1]:
    st.markdown("### ⭐ 我的自選股清單")
    if not st.session_state.logged_in:
        st.info("💡 登入帳號後，自選股永久保存在雲端，換電腦也不會消失")
    if not st.session_state.watchlist:
        st.info("📝 自選股是空的！在左側新增，或分析股票後按「加入自選」")
    else:
        if api_key:
            with st.spinner("載入即時股價..."):
                rows=[]
                for s in st.session_state.watchlist:
                    try:
                        hh = yf.Ticker(s).history(period="5d")
                        if not hh.empty and len(hh)>=2:
                            p   = round(float(hh["Close"].iloc[-1]),2)
                            chg = round((float(hh["Close"].iloc[-1])-float(hh["Close"].iloc[-2]))/float(hh["Close"].iloc[-2])*100,2)
                            rows.append({"代號":s,"現價":p,"今日":f"{'🔴+' if chg>=0 else '🟢'}{chg}%","警報":"🔔" if s in st.session_state.alerts else ""})
                        else: rows.append({"代號":s,"現價":"N/A","今日":"-","警報":""})
                    except: rows.append({"代號":s,"現價":"N/A","今日":"-","警報":""})
                if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.dataframe(pd.DataFrame({"代號":st.session_state.watchlist}), use_container_width=True, hide_index=True)
        if st.button("🗑️ 清空所有自選股"):
            if st.session_state.logged_in:
                for s in st.session_state.watchlist: db_del_watch(st.session_state.user_id,s)
            st.session_state.watchlist=[]
            st.rerun()

# ═══════════════════════════════════════
# TAB 3：即時新聞
# ═══════════════════════════════════════
with tabs[2]:
    st.markdown("### 📰 AI 即時新聞分析")
    st.info("💡 AI 即時搜尋 Google 全網，找最新新聞、產業動態、宏觀政策、川普消息等，用白話解釋對股票的影響")
    cn1,cn2 = st.columns([3,1])
    with cn1: n_in = st.text_input("輸入股票代號", placeholder="例如：2330 或 NVDA", key="nin")
    with cn2:
        st.write(""); st.write("")
        n_btn = st.button("🔍 搜尋全網資訊", use_container_width=True, type="primary")
    if n_btn and n_in.strip():
        if not api_key: st.warning("⚠️ 需要 API 金鑰"); st.stop()
        ns = get_sym(n_in, market)
        _, ni, ne = fetch_data(ns, "1mo")
        nc = (ni or {}).get("longName") or ns
        nsc = (ni or {}).get("sector","")
        with st.spinner("🔍 AI 正在搜尋全網最新資訊（約 30~60 秒）..."):
            try: st.markdown(ai_news(nc, ns, nsc, api_key))
            except Exception as e: st.error(f"❌ {str(e)}")

# ═══════════════════════════════════════
# TAB 4：籌碼基本面
# ═══════════════════════════════════════
with tabs[3]:
    st.markdown("### 🏦 籌碼面 + 基本面深度分析")
    cc1,cc2 = st.columns([3,1])
    with cc1: c_in = st.text_input("輸入股票代號", placeholder="例如：AAPL 或 2330", key="cin")
    with cc2:
        st.write(""); st.write("")
        c_btn = st.button("🏦 查看籌碼", use_container_width=True)
    if c_btn and c_in.strip():
        cs = get_sym(c_in, market)
        with st.spinner("載入籌碼數據..."):
            try:
                to = yf.Ticker(cs)
                ic = to.info
                cc = ic.get("longName") or cs
                st.subheader(f"📌 {cc} 籌碼基本面")

                # 基本面指標網格
                st.markdown("#### 📊 核心財務數據")
                metrics_ = [
                    ("市值",ic.get("marketCap")),("本益比PE",ic.get("trailingPE")),
                    ("預估PE",ic.get("forwardPE")),("股價淨值比PB",ic.get("priceToBook")),
                    ("EPS每股盈餘",ic.get("trailingEps")),("ROE股東權益報酬",ic.get("returnOnEquity")),
                    ("毛利率",ic.get("grossMargins")),("淨利率",ic.get("profitMargins")),
                    ("營收成長率",ic.get("revenueGrowth")),("獲利成長率",ic.get("earningsGrowth")),
                    ("股息殖利率",ic.get("dividendYield")),("Beta波動係數",ic.get("beta")),
                    ("分析師目標價",ic.get("targetMeanPrice")),("分析師評級",ic.get("recommendationKey")),
                    ("負債權益比",ic.get("debtToEquity")),("流動比率",ic.get("currentRatio")),
                    ("52週高",ic.get("fiftyTwoWeekHigh")),("52週低",ic.get("fiftyTwoWeekLow")),
                ]
                gcols = st.columns(3)
                for i,(k,val) in enumerate(metrics_):
                    if val is not None:
                        if k=="股息殖利率" and isinstance(val,float): val=f"{val*100:.2f}%"
                        elif k=="市值" and isinstance(val,(int,float)): val=f"約{val/1e8:.0f}億" if val>1e8 else f"{val:,.0f}"
                        elif k in ["ROE股東權益報酬","毛利率","淨利率","營收成長率","獲利成長率"] and isinstance(val,float): val=f"{val*100:.1f}%"
                        gcols[i%3].metric(k,val)

                st.divider()
                gm1,gm2 = st.columns(2)
                with gm1:
                    st.markdown("#### 股權結構")
                    mh = to.major_holders
                    if mh is not None and not mh.empty: st.dataframe(mh,use_container_width=True,hide_index=True)
                    else: st.info("無法取得（台股較少）")
                with gm2:
                    st.markdown("#### 主要機構持股 Top10")
                    ih = to.institutional_holders
                    if ih is not None and not ih.empty: st.dataframe(ih.head(10),use_container_width=True,hide_index=True)
                    else: st.info("無法取得（台股較少）")

                if api_key:
                    st.divider()
                    st.markdown("### 🤖 AI 籌碼基本面白話解讀（含即時搜尋）")
                    with st.spinner("AI 分析中..."):
                        try:
                            p_ = f"""你是頂級股市老師，請即時搜尋「{cc}」最新財務表現和分析師評價，然後用白話文解讀以下數據。

數據：PE={ic.get('trailingPE','N/A')} | PB={ic.get('priceToBook','N/A')} | ROE={ic.get('returnOnEquity','N/A')}
毛利率={ic.get('grossMargins','N/A')} | 淨利率={ic.get('profitMargins','N/A')}
Beta={ic.get('beta','N/A')} | 分析師評級={ic.get('recommendationKey','N/A')} | 目標價={ic.get('targetMeanPrice','N/A')}

請搜尋最新財務資訊後，用繁體中文輸出：

## 💰 基本面白話解讀
（每個數據用白話解釋，跟產業平均比較，說明是便宜還是貴）

## 🌐 分析師怎麼看這支股票
（目標價和評級代表什麼，目前共識如何）

## 📊 跟主要競爭對手比較
（搜尋同產業對手，做簡單比較）

## 🏦 籌碼面解讀
（機構持股的意義，法人動向對散戶的參考價值）

## ⚠️ 新手看基本面常犯的錯誤

禁止使用「一定」「保證」「必漲」「必跌」。"""
                            st.markdown(call_ai(api_key, p_, use_search=True))
                        except Exception as e: st.error(f"❌ {str(e)}")
            except Exception as e: st.error(f"❌ 載入失敗：{str(e)}")

# ═══════════════════════════════════════
# TAB 5：股票比較
# ═══════════════════════════════════════
with tabs[4]:
    st.markdown("### ⚖️ 股票比較分析")
    st.caption("同時分析兩支股票，AI 搜尋最新資訊後客觀比較")
    cm1,cm2 = st.columns(2)
    with cm1: s1 = st.text_input("股票 A", placeholder="例如：2330", key="s1")
    with cm2: s2 = st.text_input("股票 B", placeholder="例如：2454", key="s2")
    cmp_btn = st.button("⚖️ 開始比較", use_container_width=True, type="primary")

    if cmp_btn and s1.strip() and s2.strip():
        if not api_key: st.warning("⚠️ 需要 API 金鑰"); st.stop()
        sym1=get_sym(s1,market); sym2=get_sym(s2,market)
        with st.spinner("載入兩支股票數據..."):
            h1,i1,e1 = fetch_data(sym1,period)
            h2,i2,e2 = fetch_data(sym2,period)
        if e1 or e2: st.error(f"❌ {e1 or e2}"); st.stop()

        ind1=calc_indicators(h1); ind2=calc_indicators(h2)
        sc1=calc_score(ind1,i1); sc2=calc_score(ind2,i2)
        en1=calc_entry(ind1,h1); en2=calc_entry(ind2,h2)
        n1=(i1 or {}).get("longName") or sym1
        n2=(i2 or {}).get("longName") or sym2

        # 比較表
        cdf = pd.DataFrame({
            "指標":["現價","今日漲跌","月漲跌","RSI","Stoch K","MACD方向","成交量比","52週位置","布林%","ATR波幅","綜合評分","技術狀態"],
            n1:[ind1["price"],f"{ind1['change_pct']}%",f"{ind1['change_1m']}%",
                ind1["rsi"],ind1["stoch_k"],"📈" if ind1["macd_hist"]>0 else "📉",
                f"{ind1['vol_ratio']}x",f"{ind1['position_52w']}%",f"{ind1['bb_pct']:.0f}%",
                ind1["atr"],f"{sc1['total']}/100",ind1["status"]],
            n2:[ind2["price"],f"{ind2['change_pct']}%",f"{ind2['change_1m']}%",
                ind2["rsi"],ind2["stoch_k"],"📈" if ind2["macd_hist"]>0 else "📉",
                f"{ind2['vol_ratio']}x",f"{ind2['position_52w']}%",f"{ind2['bb_pct']:.0f}%",
                ind2["atr"],f"{sc2['total']}/100",ind2["status"]],
        })
        st.dataframe(cdf, use_container_width=True, hide_index=True)

        cg1,cg2 = st.columns(2)
        with cg1: st.plotly_chart(build_chart(h1,ind1,en1,sym1),use_container_width=True)
        with cg2: st.plotly_chart(build_chart(h2,ind2,en2,sym2),use_container_width=True)

        st.divider()
        st.markdown("### 🤖 AI 比較分析（含即時搜尋）")
        with st.spinner("AI 搜尋並比較中（約 30~60 秒）..."):
            try:
                cp = f"""請即時搜尋並客觀比較這兩支股票，用白話文告訴股市新手哪支更值得關注。

股票A：{n1}（{sym1}）
評分：{sc1['total']}/100 | 狀態：{ind1['status']} | RSI：{ind1['rsi']} | 月漲跌：{ind1['change_1m']}%
入場參考：{en1['mod_buy']} | 停損：{en1['sl_normal']} | 風報比：{en1['rr']}:1

股票B：{n2}（{sym2}）
評分：{sc2['total']}/100 | 狀態：{ind2['status']} | RSI：{ind2['rsi']} | 月漲跌：{ind2['change_1m']}%
入場參考：{en2['mod_buy']} | 停損：{en2['sl_normal']} | 風報比：{en2['rr']}:1

搜尋兩支股票的最新動態後，用繁體中文輸出：

## 📊 技術面比較（哪支技術指標更強？）
## 🌐 最新動態比較（各自發生了什麼大事？）
## 💰 基本面比較（哪支基本面更紮實？）
## ⚖️ 綜合比較結論
## 🎯 新手建議（只能選一支的話，更值得關注的是哪支？原因？）

禁止使用「一定」「保證」「必漲」「必跌」。"""
                st.markdown(call_ai(api_key, cp, use_search=True))
            except Exception as e: st.error(f"❌ {str(e)}")

# ═══════════════════════════════════════
# TAB 6：持股損益
# ═══════════════════════════════════════
with tabs[5]:
    st.markdown("### 💼 持股損益試算")
    st.caption("輸入你的買入成本與股數，即時計算損益")

    pp1,pp2,pp3,pp4 = st.columns(4)
    with pp1: p_s = st.text_input("股票代號", placeholder="例如：2330", key="ps_")
    with pp2: p_c = st.number_input("買入成本（每股）",min_value=0.0,step=0.5,key="pc_")
    with pp3: p_n = st.number_input("持有股數",min_value=0.0,step=1.0,key="pn_")
    with pp4:
        st.write(""); st.write("")
        p_btn = st.button("📊 計算損益", use_container_width=True, type="primary")

    if p_btn and p_s.strip() and p_c>0 and p_n>0:
        ps_ = get_sym(p_s, market)
        with st.spinner("取得現價..."):
            ph_, pi_, pe_ = fetch_data(ps_, "5d")
        if pe_: st.error(f"❌ {pe_}")
        else:
            cp_ = round(float(ph_["Close"].iloc[-1]),2)
            pnl = round((cp_-p_c)*p_n,2)
            pct = round((cp_-p_c)/p_c*100,2)
            tc  = round(p_c*p_n,2)
            cv  = round(cp_*p_n,2)
            co_ = (pi_ or {}).get("longName") or ps_

            st.subheader(f"📌 {co_}（{ps_}）")
            col_r = st.columns(4)
            col_r[0].metric("💰 現價",   f"{cp_}")
            col_r[1].metric("📊 總成本", f"{tc:,.0f}")
            col_r[2].metric("💎 現值",   f"{cv:,.0f}")
            col_r[3].metric("損益",      f"{pnl:+,.0f}", delta=f"{pct:+.2f}%")

            clr = "#1a3a1a" if pnl>=0 else "#3a1a1a"
            bdr = "#2a5a2a" if pnl>=0 else "#5a2a2a"
            ico = "📈 獲利" if pnl>=0 else "📉 虧損"
            st.markdown(f"""
            <div style="background:{clr};border-radius:12px;padding:20px;margin:12px 0;border:1px solid {bdr}">
                <h3 style="margin:0;color:{'#66ff66' if pnl>=0 else '#ff6666'}">{ico} {abs(pnl):,.0f} 元（{pct:+.2f}%）</h3>
                <p style="color:#94a3b8;margin:8px 0 0 0">
                    成本：{p_c} × {p_n:.0f} 股 = {tc:,.0f} 元 ｜
                    現值：{cp_} × {p_n:.0f} 股 = {cv:,.0f} 元 ｜
                    每股{'獲利' if pnl>=0 else '虧損'}：{cp_-p_c:+.2f} 元
                </p>
            </div>""", unsafe_allow_html=True)

            if st.session_state.logged_in:
                if st.button("💾 儲存到持股記錄"):
                    db_save_portfolio(st.session_state.user_id,ps_,p_c,p_n)
                    st.session_state.portfolio[ps_]={"cost":p_c,"shares":p_n,"note":""}
                    st.success("✅ 已儲存")

    # 持股記錄
    if st.session_state.portfolio:
        st.divider()
        st.markdown("### 📋 我的持股記錄")
        pr_rows=[]
        for ps2, pd2 in st.session_state.portfolio.items():
            try:
                hh2 = yf.Ticker(ps2).history(period="2d")
                if not hh2.empty:
                    cp2 = round(float(hh2["Close"].iloc[-1]),2)
                    pnl2= round((cp2-pd2["cost"])/pd2["cost"]*100,2)
                    pr_rows.append({"代號":ps2,"成本":pd2["cost"],"現價":cp2,
                                    "損益%":f"{pnl2:+.2f}%","股數":pd2["shares"],
                                    "總損益":f"{(cp2-pd2['cost'])*pd2['shares']:+,.0f}"})
            except: pass
        if pr_rows:
            st.dataframe(pd.DataFrame(pr_rows), use_container_width=True, hide_index=True)

st.divider()
st.caption("📈 股市小白分析系統 Pro | AI即時搜尋 × 15項技術指標 × 入場策略 × 雲端記憶 | 僅供學習參考，不構成投資建議")