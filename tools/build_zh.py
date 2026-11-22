#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""为 animadex 全站 36,488 个角色 + 3,702 个作品生成中文名。

来源优先级：
  1. tools/zh_dict.json            —— 人工词典（最高，可持续补）
  2. _scratch/zhsrc/character.csv   —— HF ame-la/danbooru-tags-data-zh（35,384 条，带别名/说明）
     _scratch/zhsrc/copyright.csv   —— 同数据集的作品表（8,414 条）
  3. 规范化（ou→o / uu→u / 双写收单 / 去下划线）+ 别名表
  4. 作品校验的变体匹配：数据集把作品名也译在括号里（leafa_(sao) → 莉法（刀剑神域）），
     而站点 slug 把作品后缀去掉了，所以先按作品中文名把候选缩到同一作品，再比基础名
  5. _scratch/zhsrc/tagzh_chars.csv —— danbooru-tag-zh（DeepSeek 译，质量参差，低优先）
  6. 基础名中文 + 修饰词拼装（swimsuit→泳装 / first_ascension→第一再临 …）
  7. Google 机翻（长尾音译；原名原样返回的视为失败，保留英文）

关键约束：基础名匹配必须通过作品校验，否则会跨作品误配
（如 genshin 的 melusine 被配成 Fate 的美露莘）。

用法：python tools/build_zh.py [--no-mt] [--limit-mt N]
输出：tools/zh_map.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = os.path.join(ROOT, 'animadex_角色标签', 'characters_tags.json')
ZHSRC = os.path.join(HERE, 'zhsrc')
DICT = os.path.join(HERE, 'zh_dict.json')
OUT = os.path.join(HERE, 'zh_map.json')
MTCACHE = os.path.join(ZHSRC, 'mt_cache.json')

CJK = re.compile(r'[\u3400-\u9fff]')
PAREN = re.compile(r'（([^（）]*)）')
TAGPAREN = re.compile(r'\(([^()]*)\)')


def has_cjk(s: str) -> bool:
    return bool(CJK.search(s or ''))


def norm(s: str) -> str:
    """罗马字变体折叠：ou/oo→o、uu→u、双写字母收一个、去分隔符。"""
    s = (s or '').lower()
    s = re.sub(r'[_\-\.\s\'’]', '', s)
    s = s.replace('ou', 'o').replace('oo', 'o').replace('uu', 'u')
    s = re.sub(r'(.)\1+', r'\1', s)
    return s


def clean_zh(z: str) -> str:
    z = (z or '').strip().replace('(', '（').replace(')', '）')
    return re.sub(r'\s+', '', z)


def split_zh(z: str):
    z = clean_zh(z)
    return PAREN.sub('', z).strip(), PAREN.findall(z)


@lru_cache(maxsize=200000)
def work_key(x: str) -> str:
    x = clean_zh(x)
    x = PAREN.sub('', x)
    x = re.sub(r'(系列|series|project|franchise)$', '', x, flags=re.I)
    return re.sub(r'[\s·・_\-]', '', x).lower()


@lru_cache(maxsize=200000)
def work_eq(a: str, b: str) -> bool:
    ka, kb = work_key(a), work_key(b)
    if not ka or not kb:
        return False
    return ka == kb or (len(ka) > 1 and ka in kb) or (len(kb) > 1 and kb in ka)


# 形态/职阶/服装等修饰词
QUAL = {
    'swimsuit': '泳装', 'summer': '夏日', 'alter': '黑化', 'young': '幼年', 'old': '老年',
    'female': '女', 'male': '男', 'child': '幼年', 'adult': '成年', 'baby': '婴儿',
    'lancer': '枪兵', 'saber': '剑士', 'archer': '弓兵', 'rider': '骑阶', 'caster': '术阶',
    'assassin': '暗杀者', 'berserker': '狂战士', 'ruler': '裁定者', 'avenger': '复仇者',
    'foreigner': '降临者', 'pretender': '伪装者', 'mooncancer': '月之癌', 'beast': '兽',
    'shielder': '盾兵', 'gunner': '枪手', 'archer_alter': '弓兵黑化',
    'first_ascension': '第一再临', 'second_ascension': '第二再临', 'third_ascension': '第三再临',
    'casual': '便服', 'casual_wear': '便服', 'school_uniform': '校服', 'uniform': '制服',
    'yukata': '浴衣', 'kimono': '和服', 'halloween': '万圣节', 'christmas': '圣诞',
    'new_year': '新年', 'valentine': '情人节', 'maid': '女仆装', 'bunny': '兔女郎',
    'bride': '新娘', 'wedding': '婚礼', 'idol': '偶像', 'princess': '公主', 'knight': '骑士',
    'armor': '铠甲', 'armed': '武装', 'robot': '机器人', 'dancer': '舞者', 'pajamas': '睡衣',
    'dress': '礼服', 'retrofit': '改造', 'champion': '冠军', 'elite_ii': '精英二',
    'muse': 'μ兵装', 'special_costume': '特别服装', '1st_costume': '第一套服饰',
    'streetwear': '街头装', 'suit': '西装', 'nurse': '护士', 'police': '警察',
    'military': '军装', 'gym': '体操服', 'cheerleader': '啦啦队', 'santa': '圣诞老人',
    'oni': '鬼', 'king': '王', 'queen': '女王', 'school': '校服', 'training': '特训',
    'ceremonial': '礼服', 'formal': '正装', 'cyber': '赛博', 'swimwear': '泳装',
    'vtuber': '虚拟主播', 'tallman': '长身人', 'chimera': '奇美拉形态', 'stand': '替身',
    'character': '角色', 'ghost': '幽灵', 'shadow': '暗影', 'dark': '暗黑', 'light': '光明',
    'evil': '邪恶', 'holy': '神圣', 'black': '黑衣', 'white': '白衣', 'red': '红衣',
    'blue': '蓝衣', 'gold': '金装', 'silver': '银装', 'night': '夜晚', 'day': '白天',
    'beach': '沙滩', 'pool': '泳池', 'rain': '雨', 'snow': '雪', 'rainy': '雨天',
    'doll': '人偶', 'cat': '猫', 'dog': '狗', 'fox': '狐', 'wolf': '狼', 'bunnygirl': '兔女郎',
}


def qual_zh(groups: list[str]) -> list[str]:
    out = []
    for g in groups:
        g = g.strip()
        if not g:
            continue
        m = re.match(r'^(\d)(st|nd|rd|th)_costume$', g)
        if m:
            out.append('第%s套服饰' % m.group(1))
            continue
        if g in QUAL:
            out.append(QUAL[g])
            continue
        parts = [p for p in re.split(r'[_/]', g) if p]
        seg = [QUAL.get(p) for p in parts]
        if seg and all(seg):
            out.append(''.join(seg))
            continue
        # 部分可译：只保留译出的部分，避免中文名里混英文
        got = ''.join(x for x in seg if x)
        if got:
            out.append(got)
    return out


def compose(base_zh: str, quals: list[str]) -> str:
    if base_zh[:1] in ('女', '男') and any(q in ('male', 'female') for q in quals):
        base_zh = base_zh[1:]
    q = qual_zh(quals)
    q = [x.replace('（', '').replace('）', '') for x in q if x]
    return base_zh + ('（' + '·'.join(q) + '）' if q else '')


# ---------------------------------------------------------------- 词表
def load_csv(path: str) -> list[dict]:
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def load_tagzh(path: str) -> dict[str, str]:
    """danbooru-tag-zh：tag,cat,count,\"别名…,中文名-作品-日文\"。"""
    out: dict[str, str] = {}
    with io.open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                parts = next(csv.reader([line]))
            except Exception:
                continue
            if len(parts) < 4:
                continue
            tag, payload = parts[0].strip(), parts[3]
            head = payload.split('-')[0]
            zh = ''
            for s in reversed([x.strip() for x in head.split(',')]):
                if has_cjk(s):
                    zh = s
                    break
            zh = re.sub(r'[（(]\s*all\s*[）)]', '', zh).strip()
            if zh and has_cjk(zh) and '/' not in zh[:2]:
                out.setdefault(tag, zh)
    return out


MTC: dict[str, str] = {}


def load_cache() -> None:
    global MTC
    if os.path.exists(MTCACHE):
        try:
            MTC = json.load(open(MTCACHE, encoding='utf-8'))
            print('机翻缓存 %d 条' % len(MTC))
        except Exception:
            MTC = {}


def save_cache() -> None:
    json.dump(MTC, open(MTCACHE, 'w', encoding='utf-8'), ensure_ascii=False)


def mt(texts: list[str], batch: int = 40) -> dict[str, str]:
    """Google 机翻（en→zh-CN），带磁盘缓存，重跑不再重复请求。"""
    out = {t: MTC[t] for t in texts if t in MTC}
    todo = [t for t in texts if t not in MTC]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        url = ('https://translate.googleapis.com/translate_a/single?client=gtx'
               '&sl=en&tl=zh-CN&dt=t&q=' + urllib.parse.quote('\n'.join(chunk)))
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                d = json.load(urllib.request.urlopen(req, timeout=30))
                lines = ''.join(x[0] for x in d[0] if x and x[0]).split('\n')
                if len(lines) != len(chunk):
                    break
                for a, b in zip(chunk, lines):
                    b = (b or '').strip()
                    # 原样返回、或没译出中文，都记成空，避免下次重复请求
                    MTC[a] = b if (b and has_cjk(b) and norm(b) != norm(a)) else ''
                break
            except Exception as e:
                if attempt == 2:
                    print('  ! MT 批失败: %s' % e, file=sys.stderr)
                time.sleep(1.5)
        if len(MTC) % 800 < batch:
            print('  mt 缓存 %d 条' % len(MTC), flush=True)
            save_cache()
    save_cache()
    for t in texts:
        if MTC.get(t):
            out[t] = MTC[t]
    return out


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-mt', action='store_true')
    ap.add_argument('--limit-mt', type=int, default=0)
    args = ap.parse_args()

    load_cache()
    rows = json.load(open(SRC, encoding='utf-8'))
    manual = json.load(open(DICT, encoding='utf-8'))
    man_ch, man_cp = manual.get('character', {}), manual.get('copyright', {})
    print('角色 %d 个' % len(rows))

    chars = load_csv(os.path.join(ZHSRC, 'character.csv'))
    cps = load_csv(os.path.join(ZHSRC, 'copyright.csv'))
    tagzh = load_tagzh(os.path.join(ZHSRC, 'tagzh_chars.csv'))
    print('词表 character %d / copyright %d / tagzh %d' % (len(chars), len(cps), len(tagzh)))

    # ---------------- 作品中文
    cp_exact = {r['tag']: clean_zh(r['zh']) for r in cps if r['zh']}
    cp_idx: dict[str, list[tuple[str, str]]] = {}
    for r in cps:
        if not r['zh']:
            continue
        for k in [r['tag']] + (r['aliases'] or '').split('|'):
            k = k.strip()
            if k:
                cp_idx.setdefault(norm(k), []).append((r['tag'], clean_zh(r['zh'])))

    our_cps = sorted({r['copyright'] for r in rows if r.get('copyright')})
    cp_zh: dict[str, str] = {}
    cp_tier: dict[str, str] = {}
    for c in our_cps:
        if c in man_cp:
            cp_zh[c], cp_tier[c] = man_cp[c], 'manual'
        elif c in cp_exact:
            cp_zh[c], cp_tier[c] = cp_exact[c], 'dict'
        elif norm(c) in cp_idx:
            best = max(cp_idx[norm(c)],
                       key=lambda x: SequenceMatcher(None, norm(x[0]), norm(c)).ratio())
            cp_zh[c], cp_tier[c] = best[1], 'norm'

    # ---------------- 角色词表：拆成 (base_zh, 修饰词, 作品)
    # entry: tag -> (base_zh, zh_quals, work_tag, work_zh)
    entry: dict[str, tuple[str, list[str], str, str]] = {}
    by_base: dict[str, list[str]] = {}          # norm(base) -> [tag]
    by_prefix: dict[str, set[str]] = {}         # norm(base)[:2] -> {norm(base)}
    for r in chars:
        if not r['zh']:
            continue
        tag = r['tag']
        z = clean_zh(r['zh'])
        b, zg = split_zh(z)
        tgroups = TAGPAREN.findall(tag)
        base = TAGPAREN.sub('', tag).strip('_')
        work_tag = tgroups[-1] if tgroups else ''
        # 作品 tag 可能是缩写/别名（sao、fgo、kancolle），先查别名索引
        work_zh = cp_exact.get(work_tag) or (
            max(cp_idx[norm(work_tag)], key=lambda x: len(x[1]))[1]
            if norm(work_tag) in cp_idx else '')
        # 判断 zh 里最后一段括号是不是作品名
        if zg and work_zh and work_eq(zg[-1], work_zh):
            zq = zg[:-1]
        elif zg and len(zg) == len(tgroups) and tgroups and not (
                len(tgroups) == 1 and tgroups[0] in QUAL):
            zq = zg[:-1]
        else:
            zq = zg
        entry[tag] = (b, zq, work_tag, work_zh)
        keys = {norm(base)}
        for al in (r['aliases'] or '').split('|'):
            al = al.strip()
            # 别名里既有罗马字也有中日文，只收 ASCII 罗马字
            if al and all(ord(c) < 128 for c in al):
                keys.add(norm(TAGPAREN.sub('', al).strip('_')))
        for k in keys:
            by_base.setdefault(k, []).append(tag)
            by_prefix.setdefault(k[:2], set()).add(k)

    # ---------------- 解析单个角色
    def work_ok(t: str, cp: str, cpname: str) -> bool:
        """词条作品与角色作品是否同一部：作品 tag（含缩写）或作品中文名命中即可。"""
        _, _, wt, wz = entry[t]
        if cp and work_eq(wt, cp):
            return True
        if cpname and wz and work_eq(wz, cpname):
            return True
        return False

    def is_work_group(g: str, cp: str, cpname: str) -> bool:
        return work_eq(g, cpname or '') or norm(g) == norm(cp) or work_eq(g, cp)

    def resolve(slug: str, cp: str, cpname: str):
        base = TAGPAREN.sub('', slug).strip('_')
        tgroups = TAGPAREN.findall(slug)
        quals = [g for g in tgroups if not is_work_group(g, cp, cpname)]

        # 1 完全命中（含补作品后缀）
        for cand in (slug, base + '_(' + cp + ')', base + '_(' + (cpname or cp) + ')'):
            if cand in entry:
                b, zq, wt, wz = entry[cand]
                # 只有该词条的作品与角色一致时才用它的修饰词
                return compose(b, quals or zq), 'dict'
        # 2 别名 / 规范化
        hits = by_base.get(norm(slug))
        if hits:
            cands = [t for t in dict.fromkeys(hits)]
            ok = [t for t in cands if work_ok(t, cp, cpname)]
            if ok:
                best = max(ok, key=lambda t: (-len(TAGPAREN.findall(t)), len(t)))
                return compose(entry[best][0], quals or entry[best][1]), 'norm'
            plain = [t for t in cands if not TAGPAREN.findall(t)]
            if len(plain) == 1:
                return compose(entry[plain[0]][0], quals), 'norm'
            if not plain and len({entry[t][0] for t in cands}) == 1 and len(cands) == 1:
                return compose(entry[cands[0]][0], quals), 'norm'
        # 3 同作品内按基础名匹配（处理变体、缩写作品名、裸名）
        hb = by_base.get(norm(base), [])
        ok = [t for t in hb if work_ok(t, cp, cpname)]
        if ok:
            best = max(ok, key=lambda t: (-len(TAGPAREN.findall(t)), len(t)))
            return compose(entry[best][0], quals), 'work'
        if tgroups:
            # 基础名轻微拼写差异：按前缀分桶，长度差 ≤3 才比（避免全表比对）
            nb0 = norm(base)
            best, bs = None, 0.0
            bucket = by_prefix.get(nb0[:2], ())
            for nb in bucket:
                if abs(len(nb) - len(nb0)) > 3:
                    continue
                ratio = SequenceMatcher(None, nb, nb0).ratio()
                if ratio < 0.9:
                    continue
                for t in by_base[nb]:
                    if work_ok(t, cp, cpname) and ratio > bs:
                        best, bs = t, ratio
            if best:
                return compose(entry[best][0], quals), 'work'
        # 4 全局基础名：唯一、或无括号的通用词条（hoshino_ai 这类只收一个基名）
        plain_all = [t for t in hb if not TAGPAREN.findall(t)]
        if len(plain_all) == 1:
            return compose(entry[plain_all[0]][0], quals), 'base'
        if len(hb) == 1 and not tgroups:
            return entry[hb[0]][0], 'base'
        # 5 第二源（仅整条 tag 命中，不做无校验的基础名回退，避免跨作品误配）
        if slug in tagzh:
            return tagzh[slug], 'tagzh'
        return None, None

    ch_zh: dict[str, str] = {}
    ch_tier: dict[str, str] = {}
    for r in rows:
        slug, cp = r['slug'], r.get('copyright') or ''
        cpname = cp_zh.get(cp, '')
        if slug in man_ch:
            ch_zh[slug], ch_tier[slug] = man_ch[slug], 'manual'
            continue
        sp = slug.replace('_', ' ')
        if sp in man_ch:
            ch_zh[slug], ch_tier[slug] = man_ch[sp], 'manual'
            continue
        z, t = resolve(slug, cp, cpname)
        if z:
            ch_zh[slug], ch_tier[slug] = z, t

    # ---------------- 机翻兜底
    miss = [r['slug'] for r in rows if r['slug'] not in ch_zh]
    if not args.no_mt:
        todo_cp = [c for c in our_cps if c not in cp_zh]
        if todo_cp:
            print('作品机翻 %d 条 …' % len(todo_cp))
            got = mt([c.replace('_', ' ') for c in todo_cp[:args.limit_mt or None]])
            for c in todo_cp:
                if c.replace('_', ' ') in got:
                    cp_zh[c], cp_tier[c] = got[c.replace('_', ' ')], 'mt'
        if miss:
            # 只翻基础名：整串翻会把作品名一起带进来（"key (blue archive)" → "<key>（蓝色档案）"）
            bases = sorted({TAGPAREN.sub('', s).strip('_').replace('_', ' ') for s in miss})
            print('角色机翻 %d 条基础名（覆盖 %d 个角色）…' % (len(bases), len(miss)))
            got = mt(bases)
            for r in rows:
                s = r['slug']
                if s in ch_zh:
                    continue
                cp = r.get('copyright') or ''
                cpname = cp_zh.get(cp, '')
                base = TAGPAREN.sub('', s).strip('_')
                z = got.get(base.replace('_', ' '))
                if not z:
                    continue
                quals = [g for g in TAGPAREN.findall(s)
                         if not (work_eq(g, cpname) or norm(g) == norm(cp))]
                ch_zh[s], ch_tier[s] = compose(z, quals), 'mt'

    # ---------------- 统计与落盘
    print('\n角色来源：', dict(Counter(ch_tier.values())))
    print('角色覆盖 %d / %d = %.1f%%' % (len(ch_zh), len(rows), len(ch_zh) / len(rows) * 100))
    print('作品覆盖 %d / %d = %.1f%%' % (len(cp_zh), len(our_cps), len(cp_zh) / len(our_cps) * 100))

    payload = {
        'v': 1,
        'date': time.strftime('%Y-%m-%d'),
        'note': '由 tools/build_zh.py 生成；人工修正改 zh_dict.json 后重跑',
        'copyright': cp_zh,
        'character': ch_zh,
        'tier': ch_tier,
        'stat': {'char_total': len(rows), 'char_zh': len(ch_zh),
                 'cp_total': len(our_cps), 'cp_zh': len(cp_zh),
                 'tiers': dict(Counter(ch_tier.values()))},
    }
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    print('写出 %s  %.1f KB' % (OUT, os.path.getsize(OUT) / 1024))

    # 分层抽样 + 未覆盖清单（供人工抽查）
    smp = {}
    for tier in ('work', 'base', 'tagzh', 'mt', 'norm', 'dict'):
        ids = [r['slug'] for r in rows if ch_tier.get(r['slug']) == tier]
        smp[tier] = [(s, ch_zh.get(s, '')) for s in ids[:80]]
    json.dump(smp, open(os.path.join(ZHSRC, 'sample_tiers.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    left = [{'slug': r['slug'], 'name': r['name'], 'cp': r.get('copyright'),
             'cp_zh': cp_zh.get(r.get('copyright') or '', ''),
             'posts': r.get('danbooru_posts')} for r in rows if r['slug'] not in ch_zh]
    left.sort(key=lambda x: -int(x['posts'] or 0))
    json.dump(left, open(os.path.join(ZHSRC, 'left_chars.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('仍未命名 %d 个' % len(left))


if __name__ == '__main__':
    main()
