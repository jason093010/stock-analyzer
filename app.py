import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from google import genai
import time
from datetime import datetime

# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="股市小白分析系統",
    page_icon="📈",
    layout="wide"
)

# ─────────────────────────────────────────────
# 手機版 CSS 優化
# ─────────────────────────────────────────────
st.markdown("""
<style>
    @media (max-width: 768px) {
        h1 { font-size: 1.4rem !important; }
        h2 { font-size: 1.1rem !important; }
        h3 { font-size: 1rem !important; }
        .stButton button { font-size: 13px !important; }
    }
    .news-card {
        background: #1e1e2e;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
        border-left: 3px solid #42A5F5;
    }
    .status-card {
        background: #1e1e2e;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
        border-left: 5px solid #7c3aed;
    }
    .alert-box {
        background: #ff4b4b22;
        border: 1px solid #ff4b4b;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# Session State 初始化（記憶用戶資料）
# ─────────────────────────────────────────────
if "watchlist" not in st.session_state:
    st.session_state.watchlist = []
if "alerts" not in st.session_state:
    st.session_state.alerts = {}

# ─────────────────────────────────────────────
# 名詞解釋資料庫
# ─────────────────────────────────────────────
GLOSSARY = {
    "多頭": "📈 多頭（Bull）\n\n白話說：市場看漲，大家都在買，股價往上走。\n\n就像一頭牛用角把東西往上頂，所以用牛來代表上漲。",
    "空頭": "📉 空頭（Bear）\n\n白話說：市場看跌，大家都在賣，股價往下走。\n\n就像一隻熊用爪子把東西往下拍，所以用熊來代表下跌。",
    "超買": "🔴 超買（Overbought）\n\n白話說：股價漲太快、太多了，很多人已經買進，短期可能會休息甚至回跌。\n\n就像一個人跑太快，需要停下來喘口氣。",
    "超賣": "🟢 超賣（Oversold）\n\n白話說：股價跌太快、太多了，可能跌過頭，短期有機會反彈回升。\n\n就像橡皮筋拉太緊，有可能彈回來。",
    "均線": "📊 均線（Moving Average）\n\n白話說：把過去幾天的收盤價加起來取平均，畫成一條線。\n\n• MA5 = 最近5天平均價\n• MA20 = 最近20天平均價（約一個月）\n• MA60 = 最近60天平均價（約一季）\n\n股價在均線上方 = 強勢；在下方 = 弱勢。",
    "均線糾結": "🔀 均線糾結\n\n白話說：MA5、MA20、MA60 三條線纏在一起，代表市場方向不明，多空勢均力敵，建議觀望。",
    "RSI": "📏 RSI（相對強弱指標）\n\n數值介於 0~100。\n\n• RSI > 70：超買，漲太多，小心回跌\n• RSI < 30：超賣，跌太多，留意反彈\n• RSI 50 附近：多空平衡",
    "MACD": "📡 MACD（指數平滑異同移動平均線）\n\n判斷股票動能是否在加速或減速。\n\n• 柱狀圖由負轉正 = 動能轉強\n• 柱狀圖由正轉負 = 動能轉弱",
    "ATR": "📐 ATR（平均真實波幅）\n\n衡量每天平均會波動多少。\n\n• ATR 高 = 波動大，風險較高\n• ATR 低 = 比較穩，波動小",
    "支撐": "🛡️ 支撐（Support）\n\n股價跌到某個價位就會停下來反彈。就像地板，股價跌到這裡就被「撐住」了。",
    "壓力": "🚧 壓力（Resistance）\n\n股價漲到某個價位就會遇到阻力下跌。就像天花板，股價漲到這裡就被「擋住」了。",
    "成交量": "📦 成交量（Volume）\n\n今天這支股票總共被買賣了幾張。\n\n• 量大 + 價漲 = 真的在漲\n• 量小 + 價漲 = 假漲，不可靠\n• 量大 + 價跌 = 有人在出貨，要小心",
    "52週高低": "📅 52週高低\n\n過去一整年的最高價和最低價。\n\n現價接近高點 = 相對貴；接近低點 = 相對便宜。",
    "本益比(PE)": "💰 本益比（P/E Ratio）\n\n白話說：你花多少錢買 1 元的獲利。\n\nPE=20 代表要 20 年才能回本。越低可能越便宜，但也要看產業平均。",
    "Beta值": "📐 Beta 值\n\n衡量股票跟大盤的連動程度。\n\n• Beta=1：跟大盤一起漲跌\n• Beta>1：比大盤波動更大（漲更多也跌更多）\n• Beta<1：比大盤穩定",
    "法人/籌碼": "🏦 法人（Institutional Investors）\n\n有大量資金的機構，包含：\n• 外資（外國機構，如高盛、摩根）\n• 投信（本土基金公司）\n• 自營商（券商自己操作）\n\n法人持續買進 = 通常是正面訊號。",
}

# ─────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key = st.text_input(
        "🔑 Gemini API 金鑰",
        type="password",
        placeholder="AIza..."
    )
    st.caption("金鑰只存在你的瀏覽器，不會被儲存")

    st.divider()
    st.header("📊 分析設定")
    market = st.radio("選擇股票市場", ["🇹🇼 台股", "🇺🇸 美股"])
    period = st.selectbox(
        "分析時間區間",
        ["3mo", "6mo", "1y", "2y"],
        index=1,
        format_func=lambda x: {
            "3mo": "3個月（短線）",
            "6mo": "6個月（中線）",
            "1y":  "1年（長線）",
            "2y":  "2年（趨勢）"
        }[x]
    )

    st.divider()
    st.header("⭐ 自選股管理")
    new_stock = st.text_input("新增股票", placeholder="輸入代號後按 Enter", key="add_watch")
    if new_stock and new_stock.strip():
        sym_add = new_stock.strip().upper()
        if "台股" in market and not sym_add.endswith(".TW"):
            sym_add += ".TW"
        if sym_add not in st.session_state.watchlist:
            st.session_state.watchlist.append(sym_add)
            st.success(f"✅ 已新增 {sym_add}")

    if st.session_state.watchlist:
        for i, s in enumerate(st.session_state.watchlist):
            col_s, col_x = st.columns([4, 1])
            col_s.write(f"• {s}")
            if col_x.button("❌", key=f"del_{i}", help="移除"):
                st.session_state.watchlist.pop(i)
                st.rerun()

    st.divider()
    st.header("🔔 價格警報")
    alert_sym = st.text_input("股票代號", placeholder="例如 2330", key="alert_sym")
    alert_above = st.number_input("漲破此價格提醒 ↑", min_value=0.0, value=0.0, step=0.5)
    alert_below = st.number_input("跌破此價格提醒 ↓", min_value=0.0, value=0.0, step=0.5)
    if st.button("✅ 設定警報", use_container_width=True):
        if alert_sym.strip():
            sym_alert = alert_sym.strip().upper()
            if "台股" in market and not sym_alert.endswith(".TW"):
                sym_alert += ".TW"
            st.session_state.alerts[sym_alert] = {
                "above": alert_above if alert_above > 0 else None,
                "below": alert_below if alert_below > 0 else None
            }
            st.success(f"✅ {sym_alert} 警報已設定")

    if st.session_state.alerts:
        st.caption("目前警報：")
        for sym_a, a in st.session_state.alerts.items():
            parts = []
            if a.get("above"): parts.append(f"↑{a['above']}")
            if a.get("below"): parts.append(f"↓{a['below']}")
            st.caption(f"• {sym_a}: {' / '.join(parts)}")

    st.divider()
    st.header("📖 名詞解釋小百科")
    st.caption("點擊名詞查看白話解釋")
    for term in GLOSSARY:
        with st.expander(term):
            st.info(GLOSSARY[term])

# ─────────────────────────────────────────────
# 主標題
# ─────────────────────────────────────────────
st.title("📈 股市小白分析系統")
st.caption("不懂技術分析也沒關係，AI 幫你用白話解釋每一個數字的意義")

# ─────────────────────────────────────────────
# 主要分頁
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 股票分析",
    "⭐ 自選股清單",
    "📰 新聞分析",
    "🏦 籌碼面"
])

# ─────────────────────────────────────────────
# 共用函數
# ─────────────────────────────────────────────

def get_ticker_symbol(raw: str, market: str) -> str:
    raw = raw.strip().upper()
    if "台股" in market and not raw.endswith(".TW"):
        return raw + ".TW"
    return raw

def fetch_stock_data(symbol: str, period: str):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            hist   = ticker.history(period=period)
            info   = ticker.info
            news   = ticker.news or []
            if hist.empty:
                return None, None, [], "查無此股票代號，請確認輸入是否正確"
            return hist, info, news, None
        except Exception as e:
            if attempt == 2:
                return None, None, [], f"數據抓取失敗：{str(e)}"
            time.sleep(1)

def calculate_indicators(hist: pd.DataFrame) -> dict:
    close = hist["Close"]
    ma5   = close.rolling(5).mean()
    ma20  = close.rolling(20).mean()
    ma60  = close.rolling(60).mean()

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - (100 / (1 + rs))

    ema12     = close.ewm(span=12).mean()
    ema26     = close.ewm(span=26).mean()
    macd      = ema12 - ema26
    signal    = macd.ewm(span=9).mean()
    hist_macd = macd - signal

    high, low = hist["High"], hist["Low"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    latest = {
        "price"      : round(float(close.iloc[-1]), 2),
        "ma5"        : round(float(ma5.iloc[-1]), 2),
        "ma20"       : round(float(ma20.iloc[-1]), 2),
        "ma60"       : round(float(ma60.iloc[-1] if len(close) >= 60 else ma20.iloc[-1]), 2),
        "rsi"        : round(float(rsi.iloc[-1]), 1),
        "macd"       : round(float(macd.iloc[-1]), 4),
        "macd_signal": round(float(signal.iloc[-1]), 4),
        "macd_hist"  : round(float(hist_macd.iloc[-1]), 4),
        "atr"        : round(float(atr.iloc[-1]), 2),
        "volume"     : int(hist["Volume"].iloc[-1]),
        "vol_avg20"  : int(hist["Volume"].rolling(20).mean().iloc[-1]),
        "change_pct" : round(float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100), 2),
        "high_52w"   : round(float(close.rolling(252).max().iloc[-1]), 2),
        "low_52w"    : round(float(close.rolling(252).min().iloc[-1]), 2),
    }

    rsi_val = latest["rsi"]
    if latest["ma5"] > latest["ma20"] > latest["ma60"] and rsi_val > 55:
        latest["status"]       = "強勢多頭 📈"
        latest["status_color"] = "🟢"
        latest["status_desc"]  = "三條均線整齊向上排列，RSI 也偏強，目前市場氣氛偏好，多方佔優勢。"
    elif latest["ma5"] < latest["ma20"] < latest["ma60"] and rsi_val < 45:
        latest["status"]       = "強勢空頭 📉"
        latest["status_color"] = "🔴"
        latest["status_desc"]  = "三條均線整齊向下排列，RSI 偏弱，目前市場下跌趨勢明顯，空方佔優勢。"
    elif rsi_val < 30:
        latest["status"]       = "超賣，留意反彈 🟡"
        latest["status_color"] = "🟡"
        latest["status_desc"]  = "RSI 低於 30，股價短期跌太多，像橡皮筋拉太緊，有機會反彈，但不代表一定會漲。"
    elif rsi_val > 70:
        latest["status"]       = "超買，留意回調 🟡"
        latest["status_color"] = "🟡"
        latest["status_desc"]  = "RSI 高於 70，股價短期漲太多，像跑太快需要喘息，短期可能會休息甚至小跌。"
    elif abs(latest["ma5"] - latest["ma20"]) / latest["price"] < 0.02:
        latest["status"]       = "均線糾結，方向未明 ⚪"
        latest["status_color"] = "⚪"
        latest["status_desc"]  = "三條均線糾纏在一起，多空雙方勢均力敵，市場在等待明確訊號，建議觀望。"
    else:
        latest["status"]       = "弱勢盤整 🟠"
        latest["status_color"] = "🟠"
        latest["status_desc"]  = "股價走勢疲軟，沒有明顯方向，在區間內來回震盪。"

    if rsi_val >= 70:
        latest["rsi_desc"] = f"⚠️ RSI {rsi_val}，數值偏高（超買區），短期漲太快，要小心回跌"
    elif rsi_val <= 30:
        latest["rsi_desc"] = f"💡 RSI {rsi_val}，數值偏低（超賣區），短期跌太多，留意反彈機會"
    elif rsi_val >= 50:
        latest["rsi_desc"] = f"✅ RSI {rsi_val}，數值偏強，多方略佔優勢"
    else:
        latest["rsi_desc"] = f"⚠️ RSI {rsi_val}，數值偏弱，空方略佔優勢"

    vol_ratio = latest["volume"] / latest["vol_avg20"] if latest["vol_avg20"] > 0 else 1
    latest["vol_ratio"] = round(vol_ratio, 2)
    if vol_ratio >= 1.5:
        latest["vol_desc"] = f"📢 今日成交量是近期平均的 {vol_ratio:.1f} 倍，成交活躍，市場關注度高"
    elif vol_ratio >= 0.8:
        latest["vol_desc"] = f"📊 今日成交量接近近期平均（{vol_ratio:.1f} 倍），市場熱度正常"
    else:
        latest["vol_desc"] = f"😴 今日成交量只有近期平均的 {vol_ratio:.1f} 倍，交投冷清，訊號可信度較低"

    price_range = latest["high_52w"] - latest["low_52w"]
    position = (latest["price"] - latest["low_52w"]) / price_range * 100 if price_range > 0 else 50
    latest["position_52w"] = round(position, 1)
    if position >= 80:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於相對高位，買進需謹慎"
    elif position <= 20:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於相對低位，相對便宜但需確認趨勢"
    else:
        latest["position_desc"] = f"現價在52週區間的 {position:.0f}% 位置，處於中間區域"

    return latest

def check_price_alerts(symbol: str, current_price: float) -> list:
    """檢查是否觸發價格警報"""
    triggered = []
    if symbol in st.session_state.alerts:
        a = st.session_state.alerts[symbol]
        if a.get("above") and current_price >= a["above"]:
            triggered.append(f"🔴 {symbol} 已漲破 {a['above']}！現價 {current_price}")
        if a.get("below") and current_price <= a["below"]:
            triggered.append(f"🟢 {symbol} 已跌破 {a['below']}！現價 {current_price}")
    return triggered

def build_chart(hist: pd.DataFrame, symbol: str):
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[
            "K線圖 + 均線（紅=漲、綠=跌）",
            "成交量（今天買賣了多少）",
            "RSI 強弱指標（70以上過熱、30以下過冷）"
        ]
    )

    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name="K線",
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a"
    ), row=1, col=1)

    close = hist["Close"]
    for span, color, name in [
        (5,  "#FFA726", "MA5（5日均線）"),
        (20, "#42A5F5", "MA20（20日均線）"),
        (60, "#AB47BC", "MA60（60日均線）")
    ]:
        fig.add_trace(go.Scatter(
            x=hist.index, y=close.rolling(span).mean(),
            line=dict(color=color, width=1.5), name=name
        ), row=1, col=1)

    colors = ["#ef5350" if c >= o else "#26a69a"
              for c, o in zip(hist["Close"], hist["Open"])]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=colors, showlegend=False
    ), row=2, col=1)

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
    fig.add_trace(go.Scatter(
        x=hist.index, y=rsi,
        line=dict(color="#FF7043", width=1.5), showlegend=False
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(239,83,80,0.5)",  row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(38,166,154,0.5)", row=3, col=1)

    fig.update_layout(
        title=f"{symbol} 技術分析圖表", height=700,
        xaxis_rangeslider_visible=False,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font_color="#FFFFFF", legend=dict(orientation="h", y=1.02)
    )
    return fig

def call_gemini(api_key: str, prompt: str) -> str:
    """呼叫 Gemini AI，自動切換模型"""
    client = genai.Client(api_key=api_key)
    models_to_try = [
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash（備用）"),
        ("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite（備用）"),
    ]
    last_error = None
    for model_id, model_name in models_to_try:
        try:
            response = client.models.generate_content(model=model_id, contents=prompt)
            return f"> 🤖 本次使用模型：{model_name}\n\n{response.text}"
        except Exception as e:
            if any(kw in str(e) for kw in ["quota","429","404","not found","RESOURCE_EXHAUSTED"]):
                last_error = f"{model_name} 額度不足"
                continue
            else:
                raise
    raise Exception(f"所有模型均無法使用：{last_error}")

def ai_stock_analysis(ind: dict, info: dict, symbol: str, api_key: str, news_titles: str = "") -> str:
    company_name = info.get("longName") or info.get("shortName") or symbol
    sector       = info.get("sector", "未知產業")
    pe_ratio     = info.get("trailingPE", "N/A")
    news_section = f"\n【最新新聞標題】\n{news_titles}" if news_titles else ""

    prompt = f"""你是一位專門服務股市新手的財經老師，擅長用最簡單的白話文解釋股票。

請根據以下數據，寫一份「完全給股市小白看的分析報告」。

規則：
- 所有專業術語出現時，必須立刻用括號加上白話解釋
- 禁止使用「一定」「保證」「必漲」「必跌」等詞
- 語氣像在跟朋友解釋，輕鬆但客觀
- 每個結論都要說明「為什麼」
- 若數據不足，直接說「目前資訊不夠，無法判斷」
- 請使用繁體中文

【股票資料】
代號：{symbol} | 公司：{company_name} | 產業：{sector} | 本益比：{pe_ratio}

【技術數據】
現價：{ind['price']} | 技術狀態：{ind['status']} | 今日漲跌：{ind['change_pct']}%
RSI：{ind['rsi']} | MACD動能：{'正向（上漲動能）' if ind['macd_hist'] > 0 else '負向（下跌動能）'}
成交量：{ind['vol_desc']} | 52週位置：{ind['position_desc']}
均線排列：{'MA5>MA20（短線偏強）' if ind['ma5'] > ind['ma20'] else 'MA5<MA20（短線偏弱）'}
{news_section}

請依照以下格式輸出：

## 🔰 這支股票現在是什麼狀況？
（2~3句白話說明）

## 📊 各項指標白話解讀
**均線（股價平均走勢）：**
**RSI（超買超賣指標）：**
**MACD（動能指標）：**
**成交量（市場熱度）：**

## 📰 新聞面影響
（如有新聞，說明對股票可能的影響；無新聞則說明）

## 🎯 短期可能的走勢？
（1~2週，客觀說明往上或往下的理由）

## ⚠️ 新手要特別注意什麼？
（條列2~3個容易犯的錯誤）

## 📌 總結
（一句話總結 + 信心程度：高／中／低）

## 📖 本報告名詞解釋
（整理所有專業名詞的白話解釋）"""

    return call_gemini(api_key, prompt)

# ─────────────────────────────────────────────
# Tab 1：股票分析
# ─────────────────────────────────────────────
with tab1:
    st.info("""
    💡 **使用方式：**
    左側輸入 Gemini API 金鑰 → 選台股或美股 → 輸入代號 → 按「開始分析」
    """)

    col1, col2 = st.columns([3, 1])
    with col1:
        if "台股" in market:
            ticker_input = st.text_input(
                "輸入台股代號",
                placeholder="例如：2330（台積電）、0050（元大台灣50）、2454（聯發科）"
            )
        else:
            ticker_input = st.text_input(
                "輸入美股代號",
                placeholder="例如：AAPL（蘋果）、TSLA（特斯拉）、NVDA（輝達）"
            )
    with col2:
        st.write("")
        st.write("")
        analyze_btn = st.button("🔍 開始分析", use_container_width=True, type="primary")

    if analyze_btn:
        if not ticker_input.strip():
            st.warning("⚠️ 請輸入股票代號")
            st.stop()
        if not api_key:
            st.warning("⚠️ 請在左側輸入 Gemini API 金鑰")
            st.stop()

        symbol = get_ticker_symbol(ticker_input, market)

        with st.spinner(f"正在抓取 {symbol} 的數據..."):
            hist, info, news, error = fetch_stock_data(symbol, period)

        if error:
            st.error(f"❌ {error}")
            st.stop()

        ind          = calculate_indicators(hist)
        company_name = info.get("longName") or info.get("shortName") or symbol

        # 價格警報檢查
        for alert_msg in check_price_alerts(symbol, ind["price"]):
            st.error(f"🔔 {alert_msg}")

        # 標題 + 加入自選股
        col_t, col_add = st.columns([4, 1])
        with col_t:
            st.subheader(f"📌 {company_name}（{symbol}）")
        with col_add:
            if symbol not in st.session_state.watchlist:
                if st.button("⭐ 加入自選", use_container_width=True):
                    st.session_state.watchlist.append(symbol)
                    st.success("✅ 已加入自選股！")
            else:
                st.success("⭐ 已在自選股")

        # 狀態卡
        st.markdown(f"""
        <div class="status-card">
            <h3 style="margin:0;color:#e2e8f0">{ind['status_color']} 目前狀態：{ind['status']}</h3>
            <p style="margin:8px 0 0 0;color:#94a3b8;font-size:15px">{ind['status_desc']}</p>
        </div>
        """, unsafe_allow_html=True)

        # 五大指標
        c1, c2, c3, c4, c5 = st.columns(5)
        chg_icon = "🔴" if ind['change_pct'] >= 0 else "🟢"
        c1.metric("💰 現價",     f"{ind['price']}")
        c2.metric("📅 今日漲跌", f"{chg_icon} {ind['change_pct']}%")
        c3.metric("📏 RSI",      f"{ind['rsi']}")
        c4.metric("📐 ATR 波動", f"{ind['atr']}")
        c5.metric("📦 量比",     f"{ind['vol_ratio']}x")

        # 白話說明卡
        st.markdown("### 🔍 各指標白話說明")
        col_a, col_b = st.columns(2)
        with col_a:
            st.info(f"**📏 RSI 強弱**\n\n{ind['rsi_desc']}")
            st.info(f"**📦 成交量熱度**\n\n{ind['vol_desc']}")
        with col_b:
            st.info(f"**📅 52週位置**\n\n{ind['position_desc']}")
            macd_txt = "📈 MACD 正值，上漲動能增強" if ind['macd_hist'] > 0 else "📉 MACD 負值，下跌動能增強"
            st.info(f"**📡 MACD 動能**\n\n{macd_txt}")

        st.divider()

        # 圖表
        st.markdown("### 📈 互動式圖表")
        st.caption("滑鼠滾輪縮放，拖曳移動時間範圍；紅色代表上漲，綠色代表下跌")
        st.plotly_chart(build_chart(hist, symbol), use_container_width=True)

        st.divider()

        # AI 分析報告（含新聞）
        st.markdown("### 🤖 AI 小白版分析報告")
        st.caption("由 Gemini AI 根據上方數據自動生成，僅供參考，不構成投資建議")

        news_titles = "\n".join([f"- {n.get('title','')}" for n in news[:5]]) if news else ""

        with st.spinner("AI 老師正在分析中，請稍候（約 15~30 秒）..."):
            try:
                report = ai_stock_analysis(ind, info, symbol, api_key, news_titles)
                st.markdown(report)
            except Exception as e:
                st.error(f"❌ AI 分析失敗：{str(e)}")

        st.divider()
        st.warning("⚠️ **重要提醒**：本系統所有分析僅供學習參考，不構成投資建議。股票投資有風險，請獨立判斷。")

        with st.expander("🔧 進階：查看完整原始數據"):
            df_ind = pd.DataFrame({
                "指標": ["現價","MA5","MA20","MA60","RSI","MACD","Signal","Hist","ATR","成交量","均量","漲跌幅","52週高","52週低"],
                "數值": [ind["price"],ind["ma5"],ind["ma20"],ind["ma60"],ind["rsi"],
                        ind["macd"],ind["macd_signal"],ind["macd_hist"],ind["atr"],
                        ind["volume"],ind["vol_avg20"],f"{ind['change_pct']}%",
                        ind["high_52w"],ind["low_52w"]]
            })
            st.dataframe(df_ind, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────
# Tab 2：自選股清單
# ─────────────────────────────────────────────
with tab2:
    st.markdown("### ⭐ 我的自選股清單")
    st.caption("在左側欄位新增股票，或在股票分析頁按「加入自選」")

    if not st.session_state.watchlist:
        st.info("📝 你還沒有自選股。可以在左側新增股票代號，或在分析完股票後點「加入自選」。")
    else:
        if not api_key:
            st.warning("⚠️ 請在左側輸入 Gemini API 金鑰才能載入即時股價")
        else:
            with st.spinner("載入自選股即時數據中..."):
                rows = []
                for sym in st.session_state.watchlist:
                    try:
                        t = yf.Ticker(sym)
                        h = t.history(period="5d")
                        if not h.empty and len(h) >= 2:
                            price = round(float(h["Close"].iloc[-1]), 2)
                            chg   = round(float((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100), 2)
                            chg_str = f"🔴 +{chg}%" if chg >= 0 else f"🟢 {chg}%"
                            alert_flag = "🔔" if check_price_alerts(sym, price) else ""
                            rows.append({"股票代號": sym, "現價": price, "今日漲跌": chg_str, "警報": alert_flag})
                        else:
                            rows.append({"股票代號": sym, "現價": "無法取得", "今日漲跌": "-", "警報": ""})
                    except:
                        rows.append({"股票代號": sym, "現價": "無法取得", "今日漲跌": "-", "警報": ""})

                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        if st.button("🗑️ 清空所有自選股"):
            st.session_state.watchlist = []
            st.rerun()

# ─────────────────────────────────────────────
# Tab 3：新聞分析
# ─────────────────────────────────────────────
with tab3:
    st.markdown("### 📰 財經新聞分析")
    st.caption("美股新聞較豐富，台股新聞數量較少")

    col_n1, col_n2 = st.columns([3, 1])
    with col_n1:
        news_ticker = st.text_input("輸入股票代號查看新聞", placeholder="例如：AAPL 或 2330", key="news_input")
    with col_n2:
        st.write("")
        st.write("")
        news_btn = st.button("📰 查看新聞", use_container_width=True)

    if news_btn and news_ticker.strip():
        sym = get_ticker_symbol(news_ticker, market)
        with st.spinner("抓取新聞中..."):
            _, info_n, news_list, err = fetch_stock_data(sym, "1mo")

        if err:
            st.error(f"❌ {err}")
        elif not news_list:
            st.info("📭 目前沒有找到相關新聞（台股新聞較少，美股較豐富）")
        else:
            company_n = info_n.get("longName") or sym
            st.subheader(f"📌 {company_n} 最新新聞")

            news_for_ai = []
            for n in news_list[:8]:
                title     = n.get("title", "無標題")
                link      = n.get("link", "#")
                publisher = n.get("publisher", "")
                pub_time  = n.get("providerPublishTime", 0)
                time_str  = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d %H:%M") if pub_time else ""
                news_for_ai.append(title)

                st.markdown(f"""
                <div class="news-card">
                    <a href="{link}" target="_blank" style="color:#e2e8f0;text-decoration:none;font-size:15px;font-weight:bold">
                        🔗 {title}
                    </a>
                    <div style="color:#94a3b8;font-size:12px;margin-top:4px">{publisher} · {time_str}</div>
                </div>
                """, unsafe_allow_html=True)

            # AI 新聞摘要
            if api_key and news_for_ai:
                st.divider()
                st.markdown("### 🤖 AI 新聞重點摘要")
                with st.spinner("AI 分析新聞影響中..."):
                    try:
                        news_prompt = f"""你是股市新手的財經老師，請用白話文分析以下關於「{company_n}」的新聞標題。

新聞標題：
{chr(10).join([f'{i+1}. {t}' for i, t in enumerate(news_for_ai)])}

請用繁體中文，白話分析：

## 📰 新聞整體氣氛
（這些新聞整體是正面、負面還是中立？為什麼？）

## 📈 對股票可能的影響
（短期內這些新聞可能帶來什麼影響？）

## ⚠️ 新手注意事項
（看到這些新聞，新手不應該有什麼衝動行為？）

注意：禁止使用「一定」「保證」「必漲」「必跌」等詞。"""

                        result = call_gemini(api_key, news_prompt)
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"❌ AI 分析失敗：{str(e)}")
            elif not api_key:
                st.info("💡 在左側輸入 API 金鑰，AI 可以幫你分析這些新聞的影響")

# ─────────────────────────────────────────────
# Tab 4：籌碼面
# ─────────────────────────────────────────────
with tab4:
    st.markdown("### 🏦 籌碼面分析")
    st.caption("籌碼面 = 誰在買、誰在賣。了解大戶與機構的動向，幫助判斷市場信心。")
    st.info("💡 美股的籌碼數據較完整；台股部分數據可能較少，這是數據來源的限制。")

    col_c1, col_c2 = st.columns([3, 1])
    with col_c1:
        chip_ticker = st.text_input("輸入股票代號", placeholder="例如：AAPL 或 2330", key="chip_input")
    with col_c2:
        st.write("")
        st.write("")
        chip_btn = st.button("🏦 查看籌碼", use_container_width=True)

    if chip_btn and chip_ticker.strip():
        sym = get_ticker_symbol(chip_ticker, market)
        with st.spinner("載入籌碼數據中..."):
            try:
                t_obj    = yf.Ticker(sym)
                info_c   = t_obj.info
                company_c = info_c.get("longName") or sym

                st.subheader(f"📌 {company_c} 籌碼分析")

                major = t_obj.major_holders
                inst  = t_obj.institutional_holders

                col_m1, col_m2 = st.columns(2)

                with col_m1:
                    st.markdown("#### 📊 股權結構")
                    if major is not None and not major.empty:
                        label_map = {
                            "% of Shares Held by All Insider":    "公司內部人持股比例",
                            "% of Shares Held by Institutions":   "機構法人持股比例",
                            "% of Float Held by Institutions":    "流通股中法人比例",
                            "Number of Institutions Holding Shares": "持股機構總數",
                        }
                        major_copy = major.copy()
                        major_copy.columns = ["數值", "說明"]
                        major_copy["說明"] = major_copy["說明"].map(lambda x: label_map.get(x, x))
                        st.dataframe(major_copy[["說明","數值"]], use_container_width=True, hide_index=True)
                        st.info("📖 **白話解釋：**\n\n• 內部人持股高 → 公司高管看好自己公司，不輕易賣出\n• 機構持股高 → 大型法人看好這支股票\n• 機構數量多 → 有很多機構在關注，市場流動性較好")
                    else:
                        st.info("此股票無法取得股權結構數據（台股常見）")

                with col_m2:
                    st.markdown("#### 🏦 主要機構持股 Top 10")
                    if inst is not None and not inst.empty:
                        cols_show = [c for c in ["Holder","Shares","% Out","Value"] if c in inst.columns]
                        inst_show = inst[cols_show].head(10).copy()
                        rename_map = {"Holder":"機構名稱","Shares":"持股數量","% Out":"持股比例","Value":"市值(USD)"}
                        inst_show.rename(columns=rename_map, inplace=True)
                        st.dataframe(inst_show, use_container_width=True, hide_index=True)
                        st.caption("這些是持股最多的大型機構投資者")
                    else:
                        st.info("此股票無法取得機構持股數據（台股常見）")

                st.divider()
                st.markdown("#### 📋 基本面關鍵數據")

                metrics_map = {
                    "市值":              info_c.get("marketCap"),
                    "本益比 PE":         info_c.get("trailingPE"),
                    "股價淨值比 PB":     info_c.get("priceToBook"),
                    "每股盈餘 EPS":      info_c.get("trailingEps"),
                    "股息殖利率":        info_c.get("dividendYield"),
                    "Beta值（波動係數）": info_c.get("beta"),
                    "分析師平均目標價":   info_c.get("targetMeanPrice"),
                    "分析師評級":        info_c.get("recommendationKey"),
                    "52週最高":          info_c.get("fiftyTwoWeekHigh"),
                    "52週最低":          info_c.get("fiftyTwoWeekLow"),
                }

                col_f1, col_f2 = st.columns(2)
                for i, (k, v) in enumerate(metrics_map.items()):
                    if v is not None:
                        col = col_f1 if i % 2 == 0 else col_f2
                        if k == "股息殖利率" and isinstance(v, float):
                            v = f"{v*100:.2f}%"
                        elif k == "市值" and isinstance(v, (int, float)):
                            v = f"約 {v/1e8:.0f} 億" if v > 1e8 else f"{v:,.0f}"
                        col.metric(k, v)

                st.divider()
                st.info("""
                📖 **基本面白話解釋：**

                - **本益比(PE)**：你花多少錢買 1 元的獲利。PE=20 代表要 20 年回本，越低可能越便宜。
                - **股價淨值比(PB)**：股價是公司實際資產的幾倍。PB<1 可能被低估。
                - **Beta值**：Beta=1.5 代表大盤漲 1%，它可能漲 1.5%，跌的時候也更猛。
                - **分析師目標價**：華爾街分析師認為合理的股價，可以當作參考。
                - **分析師評級**：Buy=買進、Hold=觀望、Sell=賣出。
                """)

                if "台股" in market:
                    st.warning("⚠️ 台股的外資、投信、自營商詳細數據需透過台灣證交所取得，目前系統顯示的是 yfinance 提供的有限數據，美股數據更完整。")

                # AI 籌碼解讀
                if api_key:
                    st.divider()
                    st.markdown("### 🤖 AI 籌碼白話解讀")
                    with st.spinner("AI 分析籌碼面中..."):
                        try:
                            pe  = info_c.get("trailingPE", "N/A")
                            pb  = info_c.get("priceToBook", "N/A")
                            beta = info_c.get("beta", "N/A")
                            rec  = info_c.get("recommendationKey", "N/A")
                            target = info_c.get("targetMeanPrice", "N/A")
                            div_yield = info_c.get("dividendYield", 0)
                            if isinstance(div_yield, float):
                                div_yield = f"{div_yield*100:.2f}%"

                            chip_prompt = f"""你是股市新手的財經老師，請用白話文解讀以下「{company_c}」的基本面與籌碼數據。

數據：
- 本益比(PE)：{pe}
- 股價淨值比(PB)：{pb}
- Beta值：{beta}
- 股息殖利率：{div_yield}
- 分析師評級：{rec}
- 分析師目標價：{target}

請用繁體中文，白話分析：

## 🏦 籌碼與基本面白話解讀
（每個數據代表什麼意思，用最簡單的方式解釋）

## 💡 這些數據告訴我們什麼？
（綜合判斷，這支股票的基本面狀況如何）

## ⚠️ 新手需要特別注意什麼？
（根據這些數據，新手要避免哪些誤解）

禁止使用「一定」「保證」「必漲」「必跌」等詞。"""

                            result = call_gemini(api_key, chip_prompt)
                            st.markdown(result)
                        except Exception as e:
                            st.error(f"❌ AI 分析失敗：{str(e)}")

            except Exception as e:
                st.error(f"❌ 籌碼數據載入失敗：{str(e)}")