import json
import time
import logging
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timezone, timedelta

# 隱藏 yfinance 批次下載時的雜訊
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
TW_TZ = timezone(timedelta(hours=8))

# 將計算邏輯獨立，避免 import app.py 觸發 Streamlit 警告
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
    
    price = round(_last(c),2)
    vwap = ((h+l+c)/3*v).rolling(20).sum()/(v.rolling(20).sum()+1e-10)
    
    ind = {
        "price": price, "vwap": round(_last(vwap),2), "rsi": round(_last(rsi),1), 
        "stoch_k": round(_last(stk),1), "macd_hist": round(_last(macd_h),4),
        "ma5": round(_last(ma5),2), "ma20": round(_last(ma20),2), "ma60": round(_last(ma60),2),
        "volume": int(_last(v)), "vol_ma20": int(_last(v.rolling(20).mean())),
        "high_52w": round(float(c.rolling(min(252,n)).max().iloc[-1]),2), 
        "low_52w": round(float(c.rolling(min(252,n)).min().iloc[-1]),2)
    }

    vr = ind["volume"] / max(ind["vol_ma20"], 1)
    ind["vol_ratio"] = round(vr, 2)
    pos = (price - ind["low_52w"]) / max(ind["high_52w"] - ind["low_52w"], 0.01) * 100
    ind["position_52w"] = round(pos, 1)

    rv, kv, mv = ind["rsi"], ind["stoch_k"], ind["macd_hist"]
    if ind["ma5"] > ind["ma20"] > ind["ma60"] and rv > 55 and mv > 0: ind["status"] = "強勢多頭 📈"
    elif ind["ma5"] < ind["ma20"] < ind["ma60"] and rv < 45 and mv < 0: ind["status"] = "強勢空頭 📉"
    elif rv <= 30 and kv < 20: ind["status"] = "雙重超賣 🟡"
    elif rv >= 70 and kv > 80: ind["status"] = "雙重超買 🟡"
    elif abs(ind["ma5"] - ind["ma20"]) / max(price, 0.01) < 0.015: ind["status"] = "盤整蓄勢 ⚪"
    elif ind["ma5"] > ind["ma20"] and rv > 50: ind["status"] = "短線偏多 🔵"
    else: ind["status"] = "方向不明 🟠"
    return ind

def get_full_universe():
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 1. 正在向 FinMind 獲取全市場最新標的清單...")
    try:
        from FinMind.data import DataLoader
        dl = DataLoader()
        df = dl.taiwan_stock_info()
        df = df[df['type'].isin(['twse', 'tpex'])]
        
        universe = {"個股": {}, "被動式ETF": {}, "主動式ETF": {}}
        for _, row in df.iterrows():
            sym, name, ind = str(row['stock_id']), str(row['stock_name']), str(row['industry_category'])
            full_sym = f"{sym}.TW" if row['type'] == 'twse' else f"{sym}.TWO"
            
            if ind == 'ETF' or sym.startswith('00'):
                if sym.endswith('A'): universe["主動式ETF"][full_sym] = name
                else: universe["被動式ETF"][full_sym] = name
            else:
                if len(sym) == 4 and sym.isdigit(): universe["個股"][full_sym] = name
        return universe
    except Exception as e:
        print(f"獲取全市場清單失敗: {e}")
        return None

def generate_leaderboard():
    universe = get_full_universe()
    if not universe:
        print("無法取得清單，排程延後執行。")
        return
        
    all_tickers = [sym for cat in universe.values() for sym in cat.keys()]
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 2. 開始批次下載 {len(all_tickers)} 檔標的歷史數據 (多線程併發)...")
    
    data = yf.download(all_tickers, period="6mo", group_by="ticker", threads=True, progress=True)
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 3. 資料下載完成，開始進行 AI 策略演算評分...")
    
    all_results = {"個股": [], "被動式ETF": [], "主動式ETF": []}
    for category, symbols_dict in universe.items():
        for sym, name in symbols_dict.items():
            try:
                df = data[sym] if len(all_tickers) > 1 else data
                if "Close" not in df.columns: continue
                df = df.dropna(subset=["Close"])
                if len(df) < 20: continue 
                
                ind = calc_indicators(df)
                dt_score = min(100, int((ind["vol_ratio"] / 2.5 * 40) + (20 if ind["price"] > ind["vwap"] else 0) + (ind["rsi"] * 0.4)))
                st_score = min(100, int((30 if ind["ma5"] > ind["ma20"] else 0) + (30 if ind["macd_hist"] > 0 else 0) + (ind["stoch_k"] * 0.4)))
                lt_score = min(100, int((40 if ind["price"] > ind["ma60"] else 0) + (30 if 30 <= ind["position_52w"] <= 70 else 10) + (30 if ind["ma20"] > ind["ma60"] else 0)))
                total_score = round(dt_score * 0.2 + st_score * 0.4 + lt_score * 0.4, 1)
                
                if ind.get("volume", 0) < 500 and category == "個股": continue
                
                reason = []
                if dt_score > 75: reason.append(f"量能放大({ind['vol_ratio']:.1f}x)")
                if st_score > 75: reason.append("短線均線多頭")
                if lt_score > 75: reason.append("站穩季線支撐")
                if not reason: reason.append("震盪盤整中")
                
                all_results[category].append({
                    "sym": sym.replace(".TW", "").replace(".TWO", ""), "name": name, "category": category,
                    "score": total_score, "dt_score": dt_score, "st_score": st_score, "lt_score": lt_score,
                    "status": ind["status"], "reason": " | ".join(reason), "update_time": datetime.now(TW_TZ).strftime("%m/%d %H:%M")
                })
            except: continue
            
    final_lb = {cat: sorted(items, key=lambda x: x["score"], reverse=True)[:10] for cat, items in all_results.items()}
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(final_lb, f, ensure_ascii=False, indent=4)
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] ✅ 全市場排行榜更新完成！已寫入 leaderboard.json")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        time.sleep(3600)