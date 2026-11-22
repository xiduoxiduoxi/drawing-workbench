# -*- coding: utf-8 -*-
"""
数据管线：把 Prompt Forge(HTML) + 阿撒托斯之梦(JSON) 合成工作台 V2 的数据层
输出：工作台V2/data/{tags,templates,presets,characters}.js + 清洗报告.md
"""
import json, re, io, sys, os, time
from collections import Counter, OrderedDict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC_HTML = r'F:\AI下载\提示词生成器.html'
SRC_JSON = r'E:\迅雷下载\st_chatu8_test_context_anima自然语言生图变量.json'
OUT_DIR = r'C:\Users\45168\WorkBuddy\AI绘图\工作台V2\data'
REPORT = r'C:\Users\45168\WorkBuddy\AI绘图\工作台V2\清洗报告.md'

os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------- 分类表
# id, 名称, 图标, 分组, 是否 NSFW
CATS = [
    ('style',       '质量与风格',   '✦',  '基础', False),
    ('artist',      '画师风格',     '🎨', '基础', False),
    ('composition', '构图取景',     '🖼', '基础', False),
    ('camera',      '镜头渲染',     '📷', '基础', False),
    ('lighting',    '光影氛围',     '💡', '基础', False),
    ('base',        '人物基础',     '👤', '外观', False),
    ('body',        '身材体型',     '📐', '外观', False),
    ('hair',        '发型发色',     '💇', '外观', False),
    ('face',        '面部特征',     '👁', '外观', False),
    ('expression',  '表情情绪',     '😊', '外观', False),
    ('clothing',    '服饰',         '👗', '服装', False),
    ('accessory',   '配饰',         '🎀', '服装', False),
    ('extra',       '服饰道具补充', '👗', '服装', False),
    ('wear',        '穿着状态',     '🧥', '服装', False),
    ('wearact',     '衣服交互',     '🪢', '服装', False),
    ('pose',        '姿势动作',     '🤸', '动作', False),
    ('posebase',    '姿态基础',     '🧎', '动作', False),
    ('action',      '手部头部动作', '✋', '动作', False),
    ('view',        '视角与焦点',   '🎥', '动作', False),
    ('relation',    '人物关系',     '👥', '动作', False),
    ('interact',    '双人互动',     '🤝', '动作', False),
    ('environment', '场景',         '🏙', '场景', False),
    ('weather',     '天气',         '🌤', '场景', False),
    ('props',       '道具',         '🎒', '场景', False),
    ('special',     '特殊场景',     '✨', '场景', False),
    ('sexact',      '性爱体位',     '🛏', 'NSFW', True),
    ('oral',        '口交',         '👄', 'NSFW', True),
    ('handjob',     '手交',         '✊', 'NSFW', True),
    ('paizuri',     '乳交',         '🍼', 'NSFW', True),
    ('footjob',     '足交',         '🦶', 'NSFW', True),
    ('masturbation','自慰',         '🖐', 'NSFW', True),
    ('cum',         '精液与体液',   '💧', 'NSFW', True),
    ('yuri',        '百合',         '👭', 'NSFW', True),
    ('after',       '事后',         '🌙', 'NSFW', True),
    ('text',        '文本提示词',   '📝', '其他', False),
    ('negative',    '负面',         '⛔', '其他', False),
]
CAT_IDS = {c[0] for c in CATS}
NSFW_CATS = {c[0] for c in CATS if c[4]}

# ---------------------------------------------------------------- 清洗工具
TYPO = {
    'aheago': 'ahegao',
    'acompletely nude': 'completely nude',
    'ront-to-back': 'front-to-back',
    '1grl': '1girl',
    'areala slip': 'areola slip',
    'hight different': 'height difference',
    'tose': 'toes',
    'arm arm support': 'arm support',
    'breast suppress': 'breast press',
    'arealoe': 'areolae',
    'niple': 'nipple',
    'panty shot': 'pantyshot',
    'gril': 'girl',
    'yuri ': 'yuri',
    'areloa': 'areola',
    'upshort ': 'upshorts ',
}

STOPWORD_SENT = re.compile(r"\b(the|is|are|was|were|and|with|his|her|she|he|that|this|from the|of the)\b", re.I)
CJK = re.compile(r'[\u4e00-\u9fff]')
NSFW_RE = re.compile(
    r'\b(nude|naked|topless|bottomless|nipples?|areola|areolae|pussy|vagina|vaginal|penis|penile|'
    r'anus|anal|anus|cum|semen|sperm|fellatio|blowjob|handjob|paizuri|footjob|masturbation|'
    r'sex|doggystyle|missionary|cowgirl|ahegao|pubic|clitoris|clitoral|uterus|cervix|urethra|'
    r'ejaculat\w*|orgasm|hymen|labia|testicles|scrotum|glans|boobjob|buttjob|tailjob)\b', re.I)


def strip_weight(s):
    s = re.sub(r'\(([^():]*?):\s*[-\d.]+\)', r'\1', s)
    s = re.sub(r'\[\s*([^\[\]:]+?)\s*(?::\s*[-\d.]+)?\s*\]', r'\1', s)
    s = s.replace('{', '').replace('}', '')
    s = re.sub(r':\s*[-\d.]+$', '', s)
    return s


def clean_en(s):
    """纯英文 tag 归一条"""
    t = str(s or '')
    t = t.strip().strip('"\'')
    t = t.replace('\u2019', "'").replace('\u2018', "'").replace('\u201c', '"').replace('\u201d', '"')
    t = t.lstrip('-*·?+').strip()
    t = re.sub(r'^#+\s*', '', t)
    t = re.sub(r'^\d+[.、)]\s*', '', t)
    t = t.replace('\\(', '(').replace('\\)', ')')
    t = re.sub(r'^(source|target)\s*#\s*', '', t)   # 角色卡通配符语法，去掉前缀仍是可用 tag
    t = strip_weight(t)
    t = t.replace('_', ' ')
    t = t.replace('+', ' ').replace('?', ' ')
    t = t.replace('】', '').replace('」', '').replace('）', '')
    t = re.sub(r'\s+', ' ', t).strip(' ,.;:|')
    t = t.lower()
    t = TYPO.get(t, t)
    return t


def is_garbage(t):
    if not t or len(t) < 2:
        return True
    if not re.search(r'[a-z]', t):
        return True
    if re.fullmatch(r'[a-z]', t):
        return True
    return False


def is_sentence(t, max_words=7):
    if not t:
        return True
    if CJK.search(t):
        return True
    if t.endswith('.'):
        return True
    words = t.split()
    if len(words) > max_words:
        return True
    if len(words) >= 5 and STOPWORD_SENT.search(t):
        return True
    if not re.match(r'^[a-z0-9]', t):
        return True
    return False


def split_multi(raw):
    """'全裸 | nude | completely nude' -> [('nude','全裸'), ('completely nude','全裸')]"""
    parts = [p.strip() for p in raw.split('|')]
    if len(parts) <= 1:
        return [(parts[0], '')] if parts[0] else []
    if CJK.search(parts[0]):        # 中文在前
        zh = parts[0]
        return [(p, zh) for p in parts[1:] if p]
    zh = parts[-1] if CJK.search(parts[-1]) else ''
    ens = [p for p in parts if not CJK.search(p)]
    return [(p, zh) for p in ens]


# ---------------------------------------------------------------- 1. HTML 词库
html = open(SRC_HTML, encoding='utf-8').read()
raw_tags = []   # (en, zh, cat, group)
dropped = []    # (来源, 原文, 原因)

CAT_PAT = re.compile(
    r"id:\s*['\"]([\w-]+)['\"],\s*name:\s*['\"]([^'\"]+)['\"],\s*icon:\s*['\"]([^'\"]*)['\"],\s*tags:\s*`([^`]*)`",
    re.S)
html_lines = 0
for m in CAT_PAT.finditer(html):
    cid, cname, icon, body = m.group(1), m.group(2), m.group(3), m.group(4)
    cat = cid if cid in CAT_IDS else 'extra'
    for line in body.split('\n'):
        line = line.strip()
        if not line:
            continue
        html_lines += 1
        for en, zh in split_multi(line):
            e = clean_en(en)
            if not e:
                dropped.append(('html', line, '空'))
                continue
            # text 分类本来就是自然语言短句，保留
            if is_garbage(e):
                dropped.append(('html', line, '碎片'))
                continue
            if cat != 'text' and is_sentence(e, 9):
                dropped.append(('html', line, '整句/超长'))
                continue
            raw_tags.append((e, zh.strip(), cat, ''))

html_tag_count = len(raw_tags)
print('HTML：%d 个分类 / %d 行 → 收 %d 条，丢 %d' %
      (len(CAT_PAT.findall(html)), html_lines, html_tag_count, len(dropped)))

# ---------------------------------------------------------------- 2. JSON 标签库
J = json.load(open(SRC_JSON, encoding='utf-8'))
entries = J['anima自然语言生图变量']['entries']

LIB_S = [i for i, e in enumerate(entries) if e['name'] == '--------标签库'][0]
LIB_E = [i for i, e in enumerate(entries) if e['name'] == '--------/标签库'][0]
TPL_S = [i for i, e in enumerate(entries) if e['name'] == '--------Tag模板库'][0]
TPL_E = [i for i, e in enumerate(entries) if e['name'] == '---------/Tag模板库'][0]

LIB_CAT = {
    '位置关系（新）': 'environment',
    '整体穿着状况（新）': 'wear',
    '构图（新）': 'composition',
    '背景类(人物)': 'base',
    '下装穿着状况（新）': 'wear',
    '上衣穿着状况（新）': 'wear',
    '人物关系（新）': 'relation',
    '男性配角（新）': 'relation',
    '人物视线（new）': 'view',
    '时间（new）': 'environment',
    '基本动作': 'posebase',
    '表情': 'expression',
    '衣服交互（新）': 'wearact',
    '服饰透视（新）': 'wear',
    '头部动作': 'action',
    '性爱（新）': 'sexact',
    '胸部动作': 'action',
    '足交': 'footjob',
    '手动作': 'action',
    '头发互动': 'action',
    '双人互动': 'interact',
    '手交': 'handjob',
    '自慰': 'masturbation',
    '口交': 'oral',
    '站姿': 'posebase',
    '射精': 'cum',
    '躺姿': 'posebase',
    '趴姿': 'posebase',
    '坐姿': 'posebase',
    '跪姿': 'posebase',
    '倾靠': 'posebase',
    '倒立': 'posebase',
    '造型': 'pose',
    '手臂动作': 'pose',
    '腿部动作': 'pose',
    '胸部动作与互动': 'action',
    '引导动作/抓动作': 'interact',
    '胸部状态与液体': 'body',
    '乳交': 'paizuri',
    '普通互动': 'interact',
}

json_tag_count = 0
for i in range(LIB_S + 1, LIB_E):
    e = entries[i]
    cat = LIB_CAT.get(e['name'], 'special')
    group = ''
    for line in e['content'].split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        # 中文分组标题（整行没有英文）
        if CJK.search(line) and not re.search(r'[A-Za-z]{2,}', line.replace('+', '')):
            group = line.lstrip('-*·# ').strip()
            continue
        # 行内可能是 "中文 | en | en" 或 纯英文
        if '|' in line and CJK.search(line):
            pairs = split_multi(line)
            for en, zh in pairs:
                e2 = clean_en(en)
                if not e2 or is_garbage(e2) or is_sentence(e2):
                    continue
                raw_tags.append((e2, zh.strip(), cat, group))
                json_tag_count += 1
            continue
        # "imminent+?（即将被什么）" 这类说明性行
        if re.search(r'\(\s*[^)]*[\u4e00-\u9fff]', line):
            line = re.sub(r'[（(][^）)]*[）)]', '', line)
        for piece in re.split(r'[,/、，]|(?<=[a-z])\s{2,}', line):
            en = clean_en(piece)
            if not en or is_garbage(en) or is_sentence(en):
                continue
            raw_tags.append((en, '', cat, group))
            json_tag_count += 1

# ---------------------------------------------------------------- 3. 合并去重（延后到模板解析之后，模板里的 tag 也入库）

# ---------------------------------------------------------------- 4. 模板库
TPL_CAT_RULES = [
    (('口交',), 'oral'),
    (('手交',), 'handjob'),
    (('乳交', '抓乳', '揉胸', '双飞', '胸部拔剑'), 'paizuri'),
    (('足交',), 'footjob'),
    (('自慰', '开门自慰'), 'masturbation'),
    (('颜射', '精液组件', '事后性爱'), 'cum'),
    (('百合',), 'yuri'),
    (('接吻', '亲密交互', '捏脸', '打屁股', '被口'), 'interact'),
    (('服装', '圣诞服装', '展示衣物', '脱衣', '掀起裙子', '拉衬衫', '看到内裤', '哺乳', '涂抹'), 'clothing'),
    (('后入位', '正常位', '站立位', '坐姿体位', '侧入位', '女上位', '火车便当', '肛交', '素股',
      '腿交', '臀交', '尾交', '颜面骑乘', '掰开小穴', '处女膜', '69', '修女性爱'), 'sexact'),
    (('跑步', '起床', '电梯', '洗车', '办公室', '教室', '温泉', '浴室', '做饭', '健身',
      '沙滩', '泳装', '喝酒', '电车', '卡在洗衣机', '泡泡浴', '共浴', '睡眠'), 'environment'),
    (('自拍', '照片', '直播', '聊天记录', '角色界面', 'Uno', '吃水果', '吃冰棒', '吃热狗',
      '偶像', '啦啦队长', '钢管舞', '魔法少女', '拇指姑娘', '攻守反转', '意外', '透视眼镜'), 'special'),
]


def tpl_cat(family):
    for keys, cat in TPL_CAT_RULES:
        if any(k in family for k in keys):
            return cat
    return 'special'


def family_name(n):
    n = re.sub(r'[-－\s]?new\s*$', '', n, flags=re.I)
    n = n.replace('(新)', '').replace('（新）', '').strip()
    # "后入位-后入位" / "手交-手交" → 去掉重复段
    if '-' in n:
        ps = [p.strip() for p in n.split('-') if p.strip()]
        if len(ps) == 2 and ps[0] == ps[1]:
            n = ps[0]
        elif len(ps) == 2 and ps[1] in ps[0]:
            n = ps[1]
    return n.strip()


templates = []
tpl_raw_blocks = 0
for i in range(TPL_S + 1, TPL_E):
    e = entries[i]
    fam = family_name(e['name'])
    cat = tpl_cat(fam)
    label = ''
    buf = []

    def flush():
        global tpl_raw_blocks
        if not buf:
            return
        raw = ' '.join(buf)
        raw = re.sub(r'\s+', ' ', raw).strip(' ,')
        toks = []
        for piece in re.split(r'[,，]', raw):
            en = clean_en(piece)
            if not en or is_garbage(en) or is_sentence(en, 9):
                continue
            toks.append(en)
        if toks:
            tpl_raw_blocks += 1
            templates.append({
                'id': 't%03d_%d' % (i, len(templates)),
                'family': fam,
                'name': label or '默认',
                'cat': cat,
                'tags': toks,
                'raw': raw,
                'src': 'json:%d' % i,
            })

    for line in e['content'].split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        cjk = bool(CJK.search(line))
        latin_words = len(re.findall(r'[A-Za-z]{2,}', line))
        if cjk and latin_words <= 1:
            flush()
            label = line.strip(' ,，')
            buf = []
        else:
            buf.append(line)
    flush()

fam_counter = Counter(t['family'] for t in templates)
print('\n模板：%d 段，%d 个动作族' % (len(templates), len(fam_counter)))

# ---------------------------------------------------------------- 3b. 合并去重
merged = OrderedDict()
dups = 0
conflict = 0

for en, zh, cat, group in raw_tags:
    if en in merged:
        dups += 1
        old = merged[en]
        if zh and not old['zh']:
            old['zh'] = zh
        if cat != old['cat'] and len(old.get('cats', [])) < 2:
            old.setdefault('cats', [old['cat']])
            if cat not in old['cats']:
                old['cats'].append(cat)
        if group and not old.get('group'):
            old['group'] = group
        continue
    merged[en] = {'en': en, 'zh': zh, 'cat': cat, 'group': group}

curated_n = len(merged)

# 模板里的 tag 也入库：库里已有的沿用原分类，没有的按关键词猜分类（不整体继承模板类目）
GUESS = [
    (r'\b(cum|semen|sperm|ejaculat\w*)\b', 'cum'),
    (r'\b(fellatio|blowjob|deepthroat|irrumatio|cunnilingus|oral|licking penis|penis in mouth|anilingus)\b', 'oral'),
    (r'\b(paizuri|breast feeding|milk|areola|nipples?)\b', 'paizuri'),
    (r'\b(handjob|fingering|hand ?job)\b', 'handjob'),
    (r'\b(footjob|foot worship|soles|toes|feet)\b', 'footjob'),
    (r'\b(sex|doggystyle|missionary|cowgirl|straddling|penis|pussy|vagina|anal|penetrat\w*|creampie|missionary|frottage|thigh sex|grinding)\b', 'sexact'),
    (r'\b(masturbat\w*|dildo|vibrator|crotch rub)\b', 'masturbation'),
    (r'\b(selfie|photo|photograph|screenshot|interface|chat log)\b', 'special'),
    (r'\b(hair|twintails|ponytail|braid|bangs|ahoge|sidelocks)\b', 'hair'),
    (r'\b(eyes|eyelash|pupils|heterochromia|freckles|mole|fang|teeth)\b', 'face'),
    (r'\b(breasts?|thighs?|hips?|waist|abs|muscular|skinny|chubby|tall|short stature|skin|navel)\b', 'body'),
    (r'\b(smile|blush|tears|ahegao|expression|eyebrows|parted lips|open mouth|closed eyes|sweat|saliva)\b', 'expression'),
    (r'\b(bra|panties|shirt|skirt|dress|kimono|yukata|uniform|bikini|swimsuit|leotard|apron|coat|jacket|pants|shorts|socks|stockings|pantyhose|thighhighs|boots|shoes|heels|gloves|veil|cape|hat|ribbon|necktie|scarf|belt|thong|lingerie|corset|garter|jewelry|earrings|necklace|choker|glasses|mask)\b', 'clothing'),
    (r'\b(holding|grabbing|hand on|arm|hands?|hug|embrace|grab|pinch|pat|touch)\b', 'action'),
    (r'\b(sitting|standing|lying|kneel\w*|squat\w*|crawl\w*|bent over|spread legs|legs? (up|apart|together)|on (back|side|stomach|all fours)|leaning|jumping|running|walking|pose)\b', 'posebase'),
    (r'\b(room|bed|wall|floor|ceiling|window|door|desk|chair|table|street|outdoor|indoor|sky|water|sand|snow|forest|garden|bath|onsen|pool|beach|classroom|office|car|train|interior|background|city|building|tree|grass|road|stairs|roof)\b', 'environment'),
    (r'\b(light|lighting|shadow|glow|sunset|sunrise|night|day|dusk|dawn|rain|snow|fog|wind|cloud|storm)\b', 'environment'),
    (r'\b(close-?up|from (above|below|behind|side)|pov|angle|view|shot|focus|depth of field|bokeh|foreshortening|blurry|perspective|composition|framing)\b', 'composition'),
    (r'\b(lens|chromatic|film grain|grain|vignette|chromatic aberration|motion blur|speed lines)\b', 'camera'),
]


def guess_cat(tok):
    for pat, cat in GUESS:
        if re.search(pat, tok):
            return cat
    return ''


tpl_token_count = 0
for t in templates:
    for tg in t['tags']:
        tpl_token_count += 1
        if tg in merged:
            dups += 1
            continue
        g = guess_cat(tg) or ('special' if t['cat'] == 'special' else t['cat'])
        merged[tg] = {'en': tg, 'zh': '', 'cat': g, 'group': t['family']}

for t in merged.values():
    if t.get('cats'):
        conflict += 1
    t['nsfw'] = 1 if (t['cat'] in NSFW_CATS or any(c in NSFW_CATS for c in t.get('cats', []))
                      or NSFW_RE.search(t['en'])) else 0

tags = list(merged.values())
print('去重后单标签 %d 条（精选 %d + 模板补充 %d，合并重复 %d，跨类 %d）' %
      (len(tags), curated_n, len(tags) - curated_n, dups, conflict))
print('分类分布：')
for cid, name, ic, grp, nsfw in CATS:
    print('  %-13s %-12s %4d' % (cid, name, sum(1 for t in tags if t['cat'] == cid)))

# ---------------------------------------------------------------- 5. 预设 & 角色
presets = []
for m in re.finditer(r'\{name:"([^"]*)",\s*desc:"([^"]*)",\s*tags:"([^"]*)"\}', html):
    name, desc, body = m.group(1), m.group(2), m.group(3)
    ts = []
    for piece in body.split(';'):
        en, zh = (split_multi(piece) or [('', '')])[0]
        en = clean_en(en)
        if en and not is_sentence(en, 9):
            ts.append({'en': en, 'zh': zh})
    if ts:
        presets.append({'name': name, 'desc': desc, 'tags': ts})
print('预设：%d 套' % len(presets))

chars = []
for m in re.finditer(r'\{game:"([^"]*)",\s*gameTag:"([^"]*)",\s*name:"([^"]*)",\s*tag:"([^"]*)",\s*charZh:"([^"]*)",\s*auto:"([^"]*)"\}', html):
    game, gtag, name, tag, charZh, auto = m.groups()
    autos = []
    for piece in auto.split(';'):
        if not piece.strip():
            continue
        parts = piece.split('|')
        en = clean_en(parts[0])
        if en:
            autos.append({'en': en, 'zh': parts[1].strip() if len(parts) > 1 else ''})
    chars.append({'game': game, 'gameTag': gtag, 'name': name, 'tag': tag, 'zh': charZh, 'auto': autos})
print('角色：%d 个' % len(chars))

# ---------------------------------------------------------------- 6. 写文件
def dump_js(path, varname, data, note):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('/* %s\n   由 build_data.py 自动生成 %s，请勿手改；改源文件后重跑脚本 */\n' %
                (note, time.strftime('%Y-%m-%d %H:%M')))
        f.write('window.%s = ' % varname)
        f.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
        f.write(';\n')


dump_js(os.path.join(OUT_DIR, 'tags.js'), 'WB_CATS', [dict(id=c[0], name=c[1], icon=c[2], group=c[3], nsfw=c[4]) for c in CATS], '分类表')
with open(os.path.join(OUT_DIR, 'tags.js'), 'a', encoding='utf-8') as f:
    f.write('window.WB_TAGS = ')
    f.write(json.dumps(tags, ensure_ascii=False, separators=(',', ':')))
    f.write(';\n')
dump_js(os.path.join(OUT_DIR, 'templates.js'), 'WB_TEMPLATES', templates, '组合模板')
dump_js(os.path.join(OUT_DIR, 'presets.js'), 'WB_PRESETS', presets, '风格预设')
dump_js(os.path.join(OUT_DIR, 'characters.js'), 'WB_CHARACTERS', chars, '角色库')

# ---------------------------------------------------------------- 7. 报告
sizes = {f: os.path.getsize(os.path.join(OUT_DIR, f)) for f in
         ['tags.js', 'templates.js', 'presets.js', 'characters.js']}
nsfw_n = sum(1 for t in tags if t['nsfw'])
with open(REPORT, 'w', encoding='utf-8') as f:
    w = f.write
    w('# 数据清洗报告\n\n> 由 `tools/build_data.py` 生成，时间 %s\n\n' % time.strftime('%Y-%m-%d %H:%M'))
    w('## 汇总\n\n| 项 | 数值 |\n|---|---|\n')
    w('| 单词条（去重后） | **%d** |\n' % len(tags))
    w('| 其中带中文释义 | %d |\n' % sum(1 for t in tags if t['zh']))
    w('| 其中标记 NSFW | %d |\n' % nsfw_n)
    w('| 合并掉的重复 | %d |\n' % dups)
    w('| 组合模板 | **%d** 段 / %d 族 |\n' % (len(templates), len(fam_counter)))
    w('| 风格预设 | %d 套 |\n' % len(presets))
    w('| 角色 | %d 个 |\n\n' % len(chars))
    w('| 文件 | 体积 |\n|---|---|\n')
    for k, v in sizes.items():
        w('| %s | %.0f KB |\n' % (k, v / 1024))
    w('\n## 分类分布\n\n| 分类 | id | 条数 | NSFW |\n|---|---|---|---|\n')
    for cid, name, ic, grp, nsfw in CATS:
        n = sum(1 for t in tags if t['cat'] == cid)
        w('| %s %s | `%s` | %d | %s |\n' % (ic, name, cid, n, '是' if nsfw else ''))
    w('\n## 模板族\n\n')
    for fam, n in fam_counter.most_common():
        w('- %s（%d 段）\n' % (fam, n))
    w('\n## 清洗动作\n\n')
    w('1. **下划线 → 空格**：所有 tag 统一成空格写法（Anima 不识别下划线），原串保留在模板 `raw` 字段。\n')
    w('2. **权重语法剥离**：`(tag:1.2)` / `{tag}` / `[tag]` → 纯 tag。\n')
    w('3. **整句剔除**：含中文、超过 7 个词、或含 the/is/his 等虚词的长句不进标签层（模板层仍保留原文）。\n')
    w('4. **错拼纠正**：%s\n' % '、'.join('`%s`→`%s`' % (k, v) for k, v in list(TYPO.items())[:10]))
    w('5. **跨类合并**：同一 tag 在多个分类出现时，保留首个分类，其余记在 `cats`。共 %d 条。\n' % conflict)
    w('6. **NSFW 标记**：NSFW 分区全部标记；其他分区按关键词（nude/pussy/penis/cum…）命中标记。\n')
    w('\n## 抽查样本（随机 30 条）\n\n| en | zh | cat | nsfw |\n|---|---|---|---|\n')
    import random
    random.seed(7)
    for t in random.sample(tags, min(30, len(tags))):
        w('| `%s` | %s | %s | %d |\n' % (t['en'], t['zh'], t['cat'], t['nsfw']))

print('\n输出：')
for k, v in sizes.items():
    print('  %-16s %6.0f KB' % (k, v / 1024))
print('报告：', REPORT)
