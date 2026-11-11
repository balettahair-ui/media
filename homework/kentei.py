# -*- coding: utf-8 -*-
"""Notion「🎓 カリキュラム進行表」で「合格」が付いたら、LINE WORKS のグループに知らせる。

GitHub Actions から15分おきに呼ばれます。
一度知らせた行は homework/kentei_seen.json に残すので、二度は飛びません。
"""
import json, os, sys, time, urllib.request, urllib.parse

DB_ID      = '27bb2a57-9f2a-49cf-b792-3efc60e19253'   # 🎓 カリキュラム進行表
PEOPLE     = ['仙波洸', '中尾心音', '佐藤大佳']        # 受講者の列。増えたらここに足す
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


def all_rows():
    """進行表の全行を取る"""
    body = json.dumps({'page_size': 100}).encode()
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

    rows = all_rows()

    # 「◯◯さんの△△が合格」を1件とみなす。鍵は 行ID:氏名
    passed = []
    for r in rows:
        p = r['properties']
        item = plain(p.get('項目')) or '（項目が空）'
        for who in PEOPLE:
            if plain(p.get(who)) == '○合格':
                passed.append(('%s:%s' % (r['id'], who), who, item))

    fresh = [x for x in passed if x[0] not in seen]

    def save():
        ids = [x[0] for x in passed] + list(seen)
        with open(SEEN, 'w', encoding='utf-8') as fh:
            json.dump(sorted(set(ids))[:2000], fh, ensure_ascii=False, indent=0)

    if INIT:
        save()
        print('今「○合格」の %d 件を通知済みにしました。' % len(passed))
        return

    if not fresh:
        print('新しい合格はありません。')
        return

    msgs = []
    for _, who, item in fresh:
        msgs.append('🎉 %sさん、%s 検定 合格おめでとうございます！' % (who, item))

    text = '\n\n―――\n\n'.join(msgs)

    if DRY:
        print('--- 送る本文 ---\n%s\n※ --dry-run のため送信していません。' % text)
        return

    send(get_token(), text)
    print('送信しました：%d件' % len(fresh))
    save()


if __name__ == '__main__':
    main()
