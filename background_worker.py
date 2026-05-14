import json
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from app import fetch_data, calc_indicators, FUGLE_API_KEY

TW_TZ = timezone(timedelta(hours=8))

# 建立觀測池：直接綁定中文名稱，避免 yfinance 吐出英文
UNIVERSE = {
    "個股": {
        "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", 
        "2382.TW": "廣達", "2308.TW": "台達電", "2603.TW": "長榮", 
        "3231.TW": "緯創", "2356.TW": "英業達", "2327.TW": "國巨", 
        "2492.TW": "華新科"
    },
    "被動式ETF": {
        "0050.TW": "元大台灣50", "0056.TW": "元大高股息", "00878.TW": "國泰永續高息", 
        "00929.TW": "復華台灣科技優息", "006208.TW": "富邦台50", 
        "00713.TW": "元大台灣高息低波", "00679B.TWO": "元大美債20年"
    },
    "主動式ETF": {
        "00928.TWO": "中信上櫃ESG30", "00933B.TW": "國泰10Y+金融債", 
        "00915.TW": "凱基優選高股息30"
    }
}

def analyze_asset(sym, name, category):
    h, info, err = fetch_data(sym, "6mo")
    if err or h is None or h.empty: 
        print(f"  [跳過] {sym} 數據抓取失敗: {err}")
        return None
    
    ind = calc_indicators(h)
    
    # 維度獨立評分 (滿分各 100)
    dt_score = min(100, int((ind["vol_ratio"] / 2.5 * 40) + (20 if ind["price"] > ind["vwap"] else 0) + (ind["rsi"] * 0.4)))
    st_score = min(100, int((30 if ind["ma5"] > ind["ma20"] else 0) + (30 if ind["macd_hist"] > 0 else 0) + (ind["stoch_k"] * 0.4)))
    lt_score = min(100, int((40 if ind["price"] > ind["ma60"] else 0) + (30 if 30 <= ind["position_52w"] <= 70 else 10) + (30 if ind["ma20"] > ind["ma60"] else 0)))
    
    total_score = round(dt_score * 0.2 + st_score * 0.4 + lt_score * 0.4, 1)
    
    reason = []
    if dt_score > 75: reason.append(f"量能放大({ind['vol_ratio']:.1f}x)")
    if st_score > 75: reason.append("短線均線多頭")
    if lt_score > 75: reason.append("站穩季線支撐")
    if not reason: reason.append("震盪盤整中")

    return {
        "sym": sym.replace(".TW", "").replace(".TWO", ""),
        "name": name,
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
    if FUGLE_API_KEY:
        print("🟢 已啟用 富果 (Fugle) API 模式")
        
    all_results = {"個股": [], "被動式ETF": [], "主動式ETF": []}
    
    for category, symbols_dict in UNIVERSE.items():
        print(f"掃描 {category}...")
        for sym, name in symbols_dict.items():
            res = analyze_asset(sym, name, category)
            if res: all_results[category].append(res)
            time.sleep(1.5) # 遵守 API 速率限制
            
    final_lb = {}
    for cat, items in all_results.items():
        final_lb[cat] = sorted(items, key=lambda x: x["score"], reverse=True)[:10]
        
    with open("leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(final_lb, f, ensure_ascii=False, indent=4)
    print("✅ 全分類排行榜更新完成！")

if __name__ == "__main__":
    while True:
        generate_leaderboard()
        time.sleep(10800) # 每 3 小時更新一次