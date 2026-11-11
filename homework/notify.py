# -*- coding: utf-8 -*-
"""Notion「📤 宿題の提出」の新着を LINE WORKS のグループトークに報告する。

GitHub Actions から15分おきに呼ばれます。
送信済みの控えは homework/seen.json に残し、ワークフローが commit し直します。
認証情報はすべて環境変数（GitHub の Secrets）から読みます。
"""
import json, os, sys, time, urllib.request, urllib.parse

DB_ID      = 'aaba4eb8-935a-44ed-8a03-0e68ac9d0b57'
CHANNEL_ID = '43ab6be2-f5cf-34e1-2dcb-a83f64d7d2ee'   # グループトーク「アカデミー」
SEEN       = os.path.join(os.path.dirname(__file__), 'seen.json')
INIT       = '--init' in sys.argv


def env(k):
    v = os.environ.get(k, '').strip()
    if not v:
        sys.exit('環境変数 %s がありません。GitHub の Secrets を確認してください。' % k)
    return v


# ---------- Notion ----------
def notion_rows():
    body = json.dumps({
        'sorts': [{'timestamp': 'created_time', 'direction': 'descending'}],
        'page_size': 50}).encode()
    req = urllib.request.Request(
        'https://api.notion.com/v1/databases/%s/query' % DB_ID, data=body,
        headers={'Authorization': 'Bearer ' + env('NOTION_TOKEN'),
                 'Notion-Version': '2022-06-28',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['results']


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
    if t == 'files':
        return str(len(p['files']))
    return ''


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

    rows = notion_rows()
    fresh = [r for r in rows if r['id'] not in seen]

    def save():
        ids = [r['id'] for r in rows] + [i for i in seen]
        with open(SEEN, 'w', encoding='utf-8') as fh:
            json.dump(ids[:500], fh, ensure_ascii=False, indent=0)

    if INIT:
        save()
        print('今ある %d 件を送信済みにしました。' % len(rows))
        return

    if not fresh:
        print('新しい提出はありません。')
        return

    msgs = []
    for r in fresh:
        p = r['properties']
        name = plain(p.get('提出者')) or '（提出者が空）'
        task = plain(p.get('課題名')) or '（課題名が空）'
        cnt = plain(p.get('回数'))
        date = plain(p.get('提出日')) or r['created_time'][:10]
        files = plain(p.get('動画・写真'))
        line = '📤 %sさんが宿題を提出しました\n\n■ %s' % (name, task)
        if cnt:
            line += '（%s回目）' % cnt
        line += '\n提出日：%s' % date.replace('-', '/')
        if files and files != '0':
            line += '\n動画・写真：%s件' % files
        line += '\n\n確認はこちらから\n%s' % r['url']
        msgs.append(line)

    send(get_token(), '\n\n―――\n\n'.join(msgs))
    print('送信しました：%d件' % len(fresh))
    save()


if __name__ == '__main__':
    main()
