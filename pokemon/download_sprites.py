#!/usr/bin/env python3
"""一次性脚本：下载游戏所需宝可梦图片到 static/ 目录。
用法：python download_sprites.py
"""
import os, time, urllib.request, urllib.error

# 游戏中所有宝可梦的 ID（与 pokemon_english.html 中的 POKEMON_POOL 对应）
POKEMON_IDS = [
    1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,
    21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
    41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,
    63,79,92,94,104,113,131,133,143,144,145,146,147,149,150,151,778
]

SPRITE_URL  = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png"
ARTWORK_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{id}.png"

SPRITE_DIR  = os.path.join(os.path.dirname(__file__), "static", "sprites")
ARTWORK_DIR = os.path.join(os.path.dirname(__file__), "static", "artwork")

def download(url, dest):
    if os.path.exists(dest):
        return "skip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            with open(dest, "wb") as f:
                f.write(resp.read())
        return "ok"
    except Exception as e:
        return f"fail: {e}"

def main():
    os.makedirs(SPRITE_DIR,  exist_ok=True)
    os.makedirs(ARTWORK_DIR, exist_ok=True)

    total = len(POKEMON_IDS) * 2
    done = skip = fail = 0

    for pid in POKEMON_IDS:
        for url_tpl, folder, label in [
            (SPRITE_URL,  SPRITE_DIR,  "sprite"),
            (ARTWORK_URL, ARTWORK_DIR, "artwork"),
        ]:
            url  = url_tpl.format(id=pid)
            dest = os.path.join(folder, f"{pid}.png")
            result = download(url, dest)
            if result == "ok":
                done += 1
                print(f"✅ #{pid} {label}")
            elif result == "skip":
                skip += 1
            else:
                fail += 1
                print(f"❌ #{pid} {label}: {result}")
            time.sleep(0.05)  # 避免请求过快

    print(f"\n完成：下载 {done}，跳过 {skip}，失败 {fail}  / 共 {total} 张")

if __name__ == "__main__":
    main()
