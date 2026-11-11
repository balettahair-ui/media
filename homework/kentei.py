# -*- coding: utf-8 -*-
"""Notion「🎓 カリキュラム進行表」で「合格」が付いたら、LINE WORKS のグループに知らせる。

GitHub Actions から15分おきに呼ばれます。
一度知らせた行は homework/kentei_seen.json に残すので、二度は飛びません。
"""
import json, os, sys, time, urllib.request, urllib.parse

DB_ID      = 'daf00cc1-a35f-4ad8-9f0e-c76b09e36c6c'   # 🎓 カリキュラム進行表
CHANNEL_ID = '43ab6be2-f5cf-34e1-2dcb-a83f64d7d2ee'   # グループトーク「アカデミー」
SEEN       = os.path.join(os.path.dirname(__file__), 'kentei_seen.json')
INIT       = '--init' in sys.argv
DRY        = '--dry-run' in sys.argv


def env(k):
    v = os.environ.get(k, '').strip()
    if not v:
        sys.exit('環境変数 %s がありません。GitHub の Secrets を確認してください。' % k)
    return v


def plain(p):
    if p is None:
        return ''
    t = p.get('type')
    if t in ('title', 'rich_text'):
        return ''.join(x.get('plain_text', '') for x in p[t])
    if t == 'select':
        return (p['select'] or {}).get('name', '')
    if t == 'number':
        return '' if p['number'] is None else str(p['number'])
    if t == 'date':
        return (p['date'] or {}).get('start', '') or ''
    return ''


def passed_rows():
    """状態が「合格」の行を取る"""
    body = json.dumps({
        'filter': {'property': '状態', 'select': {'equals': '合格'}},
        'page_size': 100}).encode()
    req = urllib.request.Request(
        'https://api.notion.com/v1/databases/%s/query' % DB_ID, data=body,
        headers={'Authorization': 'Bearer ' + env('NOTION_TOKEN'),
                 'Notion-Version': '2022-06-28',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['results']


# ---------- LINE WORKS ----------
def jwt_assertion():
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b'=')
    now = int(time.time())
    head = b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
    pay = b64(json.dumps({'iss': env('LW_CLIENT_ID'), 'sub': env('LW_SERVICE_ACCOUNT'),
                          'iat': now, 'exp': now + 3600}).encode())
    si = head + b'.' + pay
    key = serialization.load_pem_private_key(
        env('LW_PRIVATE_KEY').replace('\\n', '\n').encode(), password=None)
    return (si + b'.' + b64(key.sign(si, padding.PKCS1v15(), hashes.SHA256()))).decode()


def get_token():
    body = urllib.parse.urlencode({
        'assertion': jwt_assertion(),
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'client_id': env('LW_CLIENT_ID'),
        'client_secret': env('LW_CLIENT_SECRET'),
        'scope': 'bot.message'}).encode()
    req = urllib.request.Request('https://auth.worksmobile.com/oauth2/v2.0/token',
        data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']


def send(token, text):
    url = 'https://www.worksapis.com/v1.0/bots/%s/channels/%s/messages' % (
        env('LW_BOT_ID'), CHANNEL_ID)
    req = urllib.request.Request(url,
        data=json.dumps({'content': {'type': 'text', 'text': text}}).encode(),
        headers={'Authorization': 'Bearer ' + token,
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


# ---------- 本体 ----------
def main():
    seen = set()
    if os.path.exists(SEEN):
        with open(SEEN, encoding='utf-8') as fh:
            seen = set(json.load(fh))

    rows = passed_rows()
    fresh = [r for r in rows if r['id'] not in seen]

    def save():
        ids = [r['id'] for r in rows] + list(seen)
        with open(SEEN, 'w', encoding='utf-8') as fh:
            json.dump(ids[:1000], fh, ensure_ascii=False, indent=0)

    if INIT:
        save()
        print('今「合格」の %d 件を通知済みにしました。' % len(rows))
        return

    if not fresh:
        print('新しい合格はありません。')
        return

    msgs = []
    for r in fresh:
        p = r['properties']
        name = plain(p.get('受講者')) or '（受講者が空）'
        item = plain(p.get('項目'))   or '（項目が空）'
        date = plain(p.get('合格日'))
        judge = plain(p.get('検定員'))
        line = '🎉 %sさん、%s 検定 合格おめでとうございます！' % (name, item)
        if date:
            line += '\n\n合格日：%s' % date.replace('-', '/')
        if judge:
            line += '\n検定員：%s' % judge
        msgs.append(line)

    text = '\n\n―――\n\n'.join(msgs)

    if DRY:
        print('--- 送る本文 ---\n%s\n※ --dry-run のため送信していません。' % text)
        return

    send(get_token(), text)
    print('送信しました：%d件' % len(fresh))
    save()


if __name__ == '__main__':
    main()
