# -*- coding: utf-8 -*-
"""build_moss_lib.py —— 把 prompt-workbench 的 MOSS 词库并成工作台可直接加载的 data/mosslib.js

数据来源（MIT · Overstar66/prompt-workbench）：
  tags_cn.json    18250 条 {zh,en,cat,sub,nsfw,app}
  chars_app.json   角色外观表（含 hair_en / eyes_en / outfit_en 英文标签）
  chars_extra.json 补充词条（结构同 tags 数组）

三份源 json 与 LICENSE 已随包固化在 tools/mosssrc/，默认直接读这里，
不再依赖工作台目录之外的 _scratch 克隆。换新版上游数据时可传目录参数覆盖：
  python tools/build_moss_lib.py <prompt-workbench 目录>

产出 data/mosslib.js：window.WB_MOSSLIB
  g: 按粗分类分组的中文词表，每条 [zh, en, nsfw]        —— 底稿拼句子用
  c: 角色外观表 { 中文名: [en, hair, eyes, outfit, body, chest, hair_en, eyes_en, outfit_en] }
  x: en → [zh, groupIdx] 索引                            —— 运行时反查用

为什么不合并进 tags.js：
  现有 tags.js 是 4619 条 / 36 个精细分类，喂 search_tags 的；
  这 18250 条是 7 个粗分类（外形/服装/动作/道具/场景），专门服务「按句子成分拼组」。
  两套各司其职，互不污染。改源数据重跑本脚本即可。
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'mosssrc')
OUT = os.path.join(ROOT, 'data', 'mosslib.js')

# 粗分类顺序＝MOSS 句子里的落位顺序（外形 → 服装 → 动作 → 道具 → 场景）
GROUP_ORDER = ['外形', '服装', '动作', '道具', '场景', '角色', '风格']
# 原库把质量/画风词放在「自定义」里；MOSS 禁质量词，单独归「风格」，底稿默认不拼
CAT_MAP = {'外形': '外形', '服装': '服装', '动作': '动作', '道具': '道具',
           '场景': '场景', '角色': '角色', '自定义': '风格'}


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def main():
    src = os.path.abspath(SRC)
    tags_path = os.path.join(src, 'tags_cn.json')
    if not os.path.exists(tags_path):
        raise SystemExit('找不到词库：%s\n用法：python tools/build_moss_lib.py <prompt-workbench 目录>' % tags_path)

    raw = load_json(tags_path)
    entries = raw.get('tags') if isinstance(raw, dict) else raw
    extra_path = os.path.join(src, 'chars_extra.json')
    if os.path.exists(extra_path):
        extra = load_json(extra_path)
        if isinstance(extra, list):
            entries = entries + extra
            print('chars_extra.json：并入 %d 条' % len(extra))

    groups = {g: [] for g in GROUP_ORDER}
    seen = set()
    chars = {}
    skipped = 0

    for e in entries:
        zh = str(e.get('zh') or '').strip()
        en = str(e.get('en') or '').strip()
        if not zh or not en:
            skipped += 1
            continue
        cat = CAT_MAP.get(e.get('cat') or '', '')
        if not cat:
            skipped += 1
            continue
        nsfw = 1 if e.get('nsfw') else 0

        app = e.get('app') or {}
        if cat == '角色' and app:
            key = zh
            if key not in chars:
                chars[key] = [
                    en,
                    str(app.get('hair') or '').strip(),
                    str(app.get('eyes') or '').strip(),
                    str(app.get('outfit') or '').strip(),
                    str(app.get('body') or '').strip(),
                    str(app.get('chest') or '').strip(),
                    [],          # aen：中文外观 → 英文标签，最后统一回填
                ]

        k = (cat, zh)
        if k in seen:
            continue
        seen.add(k)
        groups[cat].append([zh, en, nsfw])

    # chars_app.json：英文标签补充（entries 里的 app 通常没有 *_en 三个字段）
    app_path = os.path.join(src, 'chars_app.json')
    direct_en = {}
    if os.path.exists(app_path):
        appd = load_json(app_path)
        filled = 0
        for en_key, v in appd.items():
            zh = str(v.get('zh') or '').strip()
            if not zh:
                continue
            cur = chars.get(zh)
            if cur is None:
                chars[zh] = [en_key,
                             str(v.get('hair') or '').strip(), str(v.get('eyes') or '').strip(),
                             str(v.get('outfit') or '').strip(), str(v.get('body') or '').strip(),
                             str(v.get('chest') or '').strip(), []]
                cur = chars[zh]
                filled += 1
            else:
                for i, f in enumerate(('hair', 'eyes', 'outfit', 'body', 'chest')):
                    if not cur[i + 1] and v.get(f):
                        cur[i + 1] = str(v[f]).strip()
                filled += 1
            tags = []
            for k in ('hair_en', 'eyes_en', 'outfit_en'):
                for t in (v.get(k) or []):
                    if t and t not in tags:
                        tags.append(t)
            if tags:
                direct_en[zh] = tags
        print('chars_app.json：补全 %d 个角色外观（其中 %d 个自带英文标签）'
              % (filled, len(direct_en)))

    # 中文外观 → 英文标签：把 hair/eyes/outfit 三段按最长匹配切开（同 gen_mod._app_en 的思路）
    zh2en = {}
    for g in GROUP_ORDER:
        if g == '角色':
            continue
        for zh, en, _n in groups[g]:
            if len(zh) >= 2 and zh not in zh2en:
                zh2en[zh] = en
    tags_js = os.path.join(ROOT, 'data', 'tags.js')
    if os.path.exists(tags_js):
        m = re.search(r'window\.WB_TAGS\s*=\s*(\[.*?\]);', open(tags_js, encoding='utf-8').read(), re.S)
        if m:
            for x in json.loads(m.group(1)):
                z, e = str(x.get('zh') or ''), str(x.get('en') or '')
                if len(z) >= 2 and e and z not in zh2en:
                    zh2en[z] = e
    zh_keys = sorted(zh2en, key=len, reverse=True)

    def to_en(text):
        """长词优先、不重叠命中；返回英文标签数组（保序去重）"""
        out, used = [], [False] * len(text)
        for z in zh_keys:
            if len(out) >= 12:
                break
            i = text.find(z)
            if i < 0 or any(used[i:i + len(z)]):
                continue
            for k in range(i, i + len(z)):
                used[k] = True
            e = zh2en[z]
            if e not in out:
                out.append(e)
        return out

    # 词库只有「长发 / 双马尾」这种整词时，长词优先会把颜色吃掉
    # （「黑色长发」命中「长发」，黑就丢了）。这里按「颜色 + 发/眼」补一次。
    COLOR_EN = {'黑': 'black', '棕': 'brown', '金': 'blonde', '银': 'silver', '白': 'white',
                '红': 'red', '蓝': 'blue', '粉': 'pink', '紫': 'purple', '灰': 'grey',
                '橙': 'orange', '绿': 'green', '青': 'aqua', '栗': 'brown', '褐': 'brown'}
    COLOR_CLS = ''.join(COLOR_EN)
    HAIR_COLOR_RE = re.compile('([' + COLOR_CLS + '])色?(?:的)?(?:超长|中长|长|短|卷|直)?(?:头发|发)')
    EYE_COLOR_RE = re.compile('([' + COLOR_CLS + '])色?(?:的)?(?:眼睛|眼眸|眼|瞳)')

    def add_color(text, tags, kinds):
        """kinds：本段只允许补哪几种颜色标签（hair / eyes），避免发色段补出 *_eyes"""
        names = '|'.join(sorted(set(COLOR_EN.values())))
        for rx, suffix in ((HAIR_COLOR_RE, 'hair'), (EYE_COLOR_RE, 'eyes')):
            if suffix not in kinds:
                continue
            # 只有「颜色词」缺席才补；long_hair / twintails 这类不含颜色，照补不误
            if re.search(r'(?:^|,)(?:%s)_%s(?:,|$)' % (names, suffix), ','.join(tags)):
                continue
            m = rx.search(text)
            if not m:
                continue
            e = COLOR_EN[m.group(1)] + '_' + suffix
            if e not in tags:
                tags = tags + [e]
        return tags

    # 外观分三组存：[发, 眼, 服装]，各自英文化 —— 拼英文底稿时才能「哪类缺补哪类」，
    # 混成一串会导致「补发色时把服装也重复带一遍」
    derived = fallback = 0
    for zh, row in chars.items():
        hair, eyes, outfit = row[1], row[2], row[3]
        tri = [add_color(hair, to_en(hair), ('hair',)) if hair else [],
               add_color(eyes, to_en(eyes), ('eyes',)) if eyes else [],
               to_en(outfit) if outfit else []]
        # 上游自带的 *_en 有错（博丽灵梦写成 brown_hair，实为黑发红眼），
        # 所以中文转写优先，整段都转不出来才退回自带
        if not any(tri) and zh in direct_en:
            fb = direct_en[zh]
            low = [t.lower() for t in fb]
            tri = [[t for t in fb if re.search(r'_hair$', t.lower())],
                   [t for t in fb if re.search(r'_eyes?$', t.lower())],
                   [t for t in fb if not re.search(r'_hair$|_eyes?$', t.lower())]]
            if not any(tri):
                tri = [fb, [], []]
            fallback += 1
        row[6] = tri
        if any(tri):
            derived += 1
    print('外观英文化：%d 个角色拿到英文标签（其中 %d 个靠自带兜底）' % (derived, fallback))

    # en → [zh, groupIdx]，供运行时反查（角色表不参与，避免角色名污染普通标签）
    # 只登记空格版：界面上的 tag 一律空格分隔，库里存的是下划线（silver_hair）；
    # 运行时把查询词的下划线换成空格即可，key 少一半、文件小一半
    index = {}
    for gi, g in enumerate(GROUP_ORDER):
        for zh, en, _n in groups[g]:
            if g == '角色':
                continue
            index.setdefault(en.replace('_', ' ').lower(), [zh, gi])

    out = {
        'v': 1,
        'src': 'prompt-workbench (MIT) · Overstar66',
        'ts': time.strftime('%Y-%m-%d %H:%M'),
        'order': GROUP_ORDER,
        'g': groups,
        'c': chars,
        'x': index,
    }

    body = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    head = ('/* MOSS 词库 · 移植自 Overstar66/prompt-workbench（MIT）\n'
            '   由 tools/build_moss_lib.py 于 %s 自动生成，请勿手改；换数据请重跑脚本\n'
            '   g＝按粗分类分组的中文词表（每条 [中文, 英文, 是否NSFW]）；'
            'c＝角色外观表；x＝英文 → [中文, 组号] 索引 */\n'
            % out['ts'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(head + 'window.WB_MOSSLIB = ' + body + ';\n')

    size = os.path.getsize(OUT)
    print('写出 %s  %.1f KB' % (OUT, size / 1024.0))
    print('词条合计 %d（跳过 %d）：' % (sum(len(v) for v in groups.values()), skipped))
    for g in GROUP_ORDER:
        print('  %-4s %5d  例：%s' % (g, len(groups[g]),
                                   '、'.join(x[0] for x in groups[g][:6])))
    print('角色外观 %d 个（含英文标签 %d 个）'
          % (len(chars), sum(1 for v in chars.values() if v[6])))
    print('反查索引 %d 条' % len(index))

    # 与现有 tags.js 比对：有多少条是新的
    tags_js = os.path.join(ROOT, 'data', 'tags.js')
    if os.path.exists(tags_js):
        txt = open(tags_js, encoding='utf-8').read()
        m = re.search(r'window\.WB_TAGS\s*=\s*(\[.*?\]);', txt, re.S)
        if m:
            old = {x.get('en') for x in json.loads(m.group(1)) if x.get('en')}
            new = set(index)
            print('现有 tags.js %d 条；本次新增 %d 条，重合 %d 条'
                  % (len(old), len(new - old), len(new & old)))


if __name__ == '__main__':
    main()
