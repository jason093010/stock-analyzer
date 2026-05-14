import json
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from app import fetch_data, calc_indicators

TW_TZ = timezone(timedelta(hours=8))

# 建立觀測池 (實務上可透過爬蟲取得全市場名單，此處以代表性清單示範)
UNIVERSE = {
    "個股": ["2330.TW", "2317.TW", "2454.TW", "2382.TW", "2308.TW", "2603.TW", "3231.TW", "2356.TW", "2327.TW", "2492.TW"],
    "被動式ETF": ["0050.TW", "0056.TW", "00878.TW", "00929.TW", "006208.TW", "00713.TW", "00679B.TW"],
    "主動式ETF": ["00928.TW", "00933B.TW", "00915.TW"] # 台灣多為 Smart Beta，暫列此區
}

def analyze_asset(sym, category):
    h, info, err = fetch_data(sym, "6mo")
    if err or h is None or h.empty: return None
    
    ind = calc_indicators(h)
    
    # 維度獨立評分 (滿分各 100)
    # 當沖 (Day Trade): 著重爆發量能、VWAP、日內動能與布林通道寬度
    dt_score = min(100, int((ind["vol_ratio"] / 2.5 * 40) + (20 if ind["price"] > ind["vwap"] else 0) + (ind["rsi"] * 0.4)))
    
    # 短線 (Short Term): 著重 MA5/MA20 趨勢、MACD 動能、RSI
    st_score = min(100, int((30 if ind["ma5"] > ind["ma20"] else 0) + (30 if ind["macd_hist"] > 0 else 0) + (ind["stoch_k"] * 0.4)))
    
    # 長線 (Long Term): 著重 MA60 季線支撐、位階、乖離率
    lt_score = min(100, int((40 if ind["price"] > ind["ma60"] else 0) + (30 if 30 <= ind["position_52w"] <= 70 else 10) + (30 if ind["ma20"] > ind["ma60"] else 0)))
    
    # 綜合評分 (依權重)
    total_score = round(dt_score * 0.2 + st_score * 0.4 + lt_score * 0.4, 1)
    
    # 產生簡易評分原因
    reason = []
    if dt_score > 75: reason.append(f"量能放大({ind['vol_ratio']:.1f}x)")
    if st_score > 75: reason.append("短線均線多頭")
    if lt_score > 75: reason.append("站穩季線支撐")
    if not reason: reason.append("震盪盤整中")

    return {
        "sym": sym.replace(".TW", ""),
        "name": info.get("longName", sym.replace(".TW", "")),
        "category": category,
        "score": total_score,
        "dt_score": dt_score,
        "st_score": st_score,
        "lt_score": lt_score,
        "status": ind["status"],
        "reason": " | ".join(reason),
        "update_time": datetime.now(TW_TZ).strftime("%m/%d %H:%M")
    }

def generate_leaderboard():
    print(f"[{datetime.now(TW_TZ).strftime('%H:%M:%S')}] 開始執行全市場分類掃描...")
    all_results = {"個股": [], "被動式ETF": [], "主動式ETF": []}
    
    for category, symbols in UNIVERSE.items():
        print(f"掃描 {category}...")
        for sym in symbols:
            res = analyze_asset(sym, category)
            if res: all_results[category].append(res)
            time.sleep(1) # 遵守速率限制
            
    # 取各分類 Top 10
    final_lb = {}
    for cat, items in all_results.items():
        final_lb[cat] = sorted(items, key=lambda x: x["score"], reverse=True)[:10]
        
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(final_lb, f, ensure_ascii=False, indent=4)
    print("✅ 全分類排行榜更新完成！")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        time.sleep(3600) # 每 1 小時更新一次