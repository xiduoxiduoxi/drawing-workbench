#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 animadex 全站数据生成工作台的角色库 data/characters.js

源：../../animadex_角色标签/characters_tags.json（由 _scratch/animadex/export.py 产出）
出：../data/characters.js

为控制体积（36,488 个角色），采用字典压缩：
  { v:2, src, ts, total,
    cp: [[中文, English] , ...],   // 3,708 个版权；中文缺失时为空串
    tg: [tag 字符串...],            // 6,285 个
    c:  [ [name, cpIdx, trigger, [tgIdx...], 中文名(可缺)], ... ] }

中文名来自同目录 zh_map.json（由 build_zh.py 生成：人工词典 + 开源中文词表 +
作品校验的变体匹配 + 机翻兜底）；zh_map.json 缺失时退回 zh_dict.json。

为什么不用旧的对象数组：36k × {game,gameTag,name,tag,zh,auto:[{en,zh}]}
≈ 14 MB，压缩后约 4 MB，且 tag 字符串只存一份。
"""
from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, '..', '..', 'animadex_角色标签', 'characters_tags.json'))
ZH = os.path.join(HERE, 'zh_dict.json')
ZH_MAP = os.path.join(HERE, 'zh_map.json')
OUT = os.path.abspath(os.path.join(HERE, '..', 'data', 'characters.js'))


def main() -> None:
    rows = json.load(open(SRC, encoding='utf-8'))
    if os.path.exists(ZH_MAP):
        m = json.load(open(ZH_MAP, encoding='utf-8'))
        zh_cp = m.get('copyright') or {}
        zh_ch = m.get('character') or {}
        zh_src = 'zh_map.json (%s)' % m.get('date', '')
    else:
        zh = json.load(open(ZH, encoding='utf-8'))
        zh_cp = zh.get('copyright') or {}
        zh_ch = zh.get('character') or {}
        zh_src = 'zh_dict.json'
    print('源数据 %d 个角色；中文词表 %s：版权 %d 条 / 角色 %d 条'
          % (len(rows), zh_src, len(zh_cp), len(zh_ch)))

    rows.sort(key=lambda r: (-int(r.get('danbooru_posts') or 0), r['name'].lower()))

    cp_idx: dict[str, int] = {}
    cp_list: list[list[str]] = []
    tg_idx: dict[str, int] = {}
    tg_list: list[str] = []

    chars = []
    cp_hit = ch_hit = 0
    for r in rows:
        cp = r.get('copyright_name') or r.get('copyright') or ''
        if cp not in cp_idx:
            czh = zh_cp.get(r.get('copyright') or '', '')
            if czh:
                cp_hit += 1
            cp_idx[cp] = len(cp_list)
            cp_list.append([czh, cp])

        idx = []
        for t in r.get('tags') or []:
            t = t.strip()
            if not t:
                continue
            if t not in tg_idx:
                tg_idx[t] = len(tg_list)
                tg_list.append(t)
            idx.append(tg_idx[t])

        rec = [r['name'], cp_idx[cp], r.get('trigger') or r['name'].lower(), idx]
        czh = (zh_ch.get(r.get('slug') or '') or zh_ch.get(r.get('trigger_char') or '')
               or zh_ch.get((r.get('trigger_char') or '').replace('_', ' ')) or '')
        if czh:
            rec.append(czh)
            ch_hit += 1
        chars.append(rec)

    payload = {
        'v': 2,
        'src': 'animadex.net',
        'ts': time.strftime('%Y-%m-%d'),
        'total': len(chars),
        'cp': cp_list,
        'tg': tg_list,
        'c': chars,
    }

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('/* 角色库 · 来源 animadex.net（%d 个角色 / %d 个 tag / %d 个版权）\n'
                '   由 tools/build_chars.py 于 %s 自动生成，请勿手改；换数据请重跑脚本，'
                '重跑：python tools/build_chars.py */\n'
                % (len(chars), len(tg_list), len(cp_list), time.strftime('%Y-%m-%d %H:%M')))
        f.write('window.WB_CHARACTERS = ')
        f.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        f.write(';\n')

    size = os.path.getsize(OUT)
    print('写入 %s  %.2f MB' % (OUT, size / 1048576))
    print('角色 %d / tag 字典 %d / 版权 %d' % (len(chars), len(tg_list), len(cp_list)))
    avg = sum(len(c[3]) for c in chars) / max(len(chars), 1)
    print('人均 tag %.1f 个；无 tag 角色 %d 个'
          % (avg, sum(1 for c in chars if not c[3])))
    print('中文覆盖：角色 %d (%.1f%%) / 版权 %d (%.1f%%)'
          % (ch_hit, ch_hit / len(chars) * 100, cp_hit, cp_hit / len(cp_list) * 100))


if __name__ == '__main__':
    main()
