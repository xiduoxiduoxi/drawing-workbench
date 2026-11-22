# -*- coding: utf-8 -*-
"""build_positions.py —— 把「体位库」并成工作台可直接加载的 data/positions.js

数据来源（本机抓取，脚本在工作区根的 _scratch 里，可随时重跑）：
  ../体位库/positions.json   754 条 {en, zh, group, tags, level}
  来源站：sexinfo101.com（263 条，官方简体中文）+ sexpositions.club（519 条，英文）
  去重口径：英文名归一化（小写 / 去标点 / & → and）后唯一，754 条。

换数据目录可以传参：
  python tools/build_positions.py <positions.json 路径>

产出 data/positions.js：window.WB_POSITIONS
  order: 分类顺序（12 类，按 MOSS 句子里的常见程度排）
  g:     { 分类: [[英文, 中文, 标签串, 难度], ...] }
  x:     英文（小写空格版）→ [中文, 分类] 索引
  n:     总条数

为什么单独一份库：mosslib 是 1.8 万条通用词条（外形/服装/动作/道具/场景/角色），
tags.js 是 4619 条精细标签；体位是「身体怎么摆、谁碰谁」这一维，两套库都没覆盖，
而且体位名大量是比喻（Zombie / Tulip / Abyss），名字本身不携带姿势信息，
所以每条都带中文名 + 分类 + 站方标签，喂 search_positions 时一并返回。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(
    os.path.join(ROOT, '..', '体位库', 'positions.json'))
OUT = os.path.join(ROOT, 'data', 'positions.js')

# 分类顺序＝检索时的默认落位（先方向类，再姿态类，最后行为类）
GROUP_ORDER = ['面对面', '后入', '骑乘', '站立', '坐姿', '跪姿', '躺卧',
               '口交', '舔阴', '69', '肛交', '其他']
LEVEL_ZH = {1: '简单', 2: '中等', 3: '危险'}


def main():
    if not os.path.exists(SRC):
        raise SystemExit('找不到体位库：%s\n用法：python tools/build_positions.py <positions.json>' % SRC)
    with open(SRC, encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get('entries') or raw.get('positions') or []

    groups = {g: [] for g in GROUP_ORDER}
    index = {}
    skipped = 0
    for e in raw:
        en = str(e.get('en') or '').strip()
        zh = str(e.get('zh') or '').strip()
        if not en or not zh:
            skipped += 1
            continue
        g = e.get('group') if e.get('group') in groups else '其他'
        tags = e.get('tags') or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]
        lv = e.get('level')
        lv = int(lv) if lv in (1, 2, 3, '1', '2', '3') else 0
        groups[g].append([en, zh, ', '.join(tags), lv])
        k = ' '.join(en.lower().replace('_', ' ').split())
        if k not in index:
            index[k] = [zh, g]

    order = [g for g in GROUP_ORDER if groups[g]]
    out = {
        'v': 1,
        'src': 'sexinfo101.com + sexpositions.club',
        'ts': time.strftime('%Y-%m-%d %H:%M'),
        'n': sum(len(v) for v in groups.values()),
        'order': order,
        'g': {g: groups[g] for g in order},
        'x': index,
    }
    body = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    head = ('/* 体位库 · sexinfo101.com（官方中文 263 条）+ sexpositions.club（519 条）\n'
            '   由 tools/build_positions.py 于 %s 自动生成，请勿手改；换数据请重跑脚本\n'
            '   g＝按分类分组的体位表（每条 [英文, 中文, 标签, 难度]）；x＝英文 → [中文, 分类] 索引 */\n'
            % out['ts'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(head + 'window.WB_POSITIONS = ' + body + ';\n')

    print('写出 %s  %.1f KB' % (OUT, os.path.getsize(OUT) / 1024.0))
    print('体位合计 %d（跳过 %d），分类 %d 个：' % (out['n'], skipped, len(order)))
    for g in order:
        print('  %-4s %4d  例：%s' % (g, len(groups[g]),
                                   '、'.join(x[1] for x in groups[g][:6])))


if __name__ == '__main__':
    main()
