# -*- coding: utf-8 -*-
"""アカデミーの宿題リマインダーを LINE WORKS で個別に送る。

考え方：きょう（日本時間）から7日前にアカデミーがあれば、その回の宿題を受講者へ送る。
GitHub Actions から毎朝1回呼ばれます。アカデミーのない日は何もしません。

予定と宿題は Notion の「📅 アカデミーの予定と宿題」を直接見ます。
Notionを書き換えれば、その日から反映されます。GitHubは触らなくて大丈夫です。
"""
import csv, datetime, io, json, os, sys, time, urllib.request, urllib.parse

HERE   = os.path.dirname(__file__)
PEOPLE = os.path.join(HERE, 'reminder_people.csv')
SCHED_DB   = '25129885-cba7-4036-a125-80e7337db424'   # 📅 アカデミーの予定と宿題
NOTION_URL = 'https://app.notion.com/p/aaba4eb8935a44ed8a030e68ac9d0b57'
DRY = '--dry-run' in sys.argv


def env(k):
    v = os.environ.get(k, '').strip()
    if not v:
        sys.exit('環境変数 %s がありません。GitHub の Secrets を確認してください。' % k)
    return v


# ---------- Notion ----------
def plain(p):
    if p is None:
        return ''
    t = p.get('type')
    if t in ('title', 'rich_text'):
        return ''.join(x.get('plain_text', '') for x in p[t])
    if t == 'select':
        return (p['select'] or {}).get('name', '')
    if t == 'checkbox':
        return p['checkbox']
    if t == 'date':
        return (p['date'] or {}).get('start', '') or ''
    return ''


def sessions_on(day):
    """その日に開催されたアカデミーの回を Notion から取る"""
    body = json.dumps({
        'filter': {'property': '開催日', 'date': {'equals': day}},
        'page_size': 20}).encode()
    req = urllib.request.Request(
        'https://api.notion.com/v1/databases/%s/query' % SCHED_DB, data=body,
        headers={'Authorization': 'Bearer ' + env('NOTION_TOKEN'),
                 'Notion-Version': '2022-06-28',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)['results']
    out = []
    for x in rows:
        p = x['properties']
        out.append({
            '内容':   plain(p.get('内容')),
            'コース': plain(p.get('コース')),
            '宿題':   plain(p.get('宿題')).strip(),
            '送らない': bool(plain(p.get('送らない'))),
        })
    return out


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


def send(token, user_id, text):
    url = 'https://www.worksapis.com/v1.0/bots/%s/users/%s/messages' % (
        env('LW_BOT_ID'), urllib.parse.quote(user_id, safe=''))
    req = urllib.request.Request(url,
        data=json.dumps({'content': {'type': 'text', 'text': text}}).encode(),
        headers={'Authorization': 'Bearer ' + token,
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


# ---------- 本体 ----------
def main():
    jst = datetime.timezone(datetime.timedelta(hours=9))
    today = datetime.datetime.now(jst).date()
    target = (today - datetime.timedelta(days=7)).isoformat()

    sched = sessions_on(target)
    if not sched:
        print('%s の7日前（%s）にアカデミーはありません。何もしません。' % (today, target))
        return

    with io.open(PEOPLE, encoding='utf-8') as fh:
        people = list(csv.DictReader(fh))

    msgs = []
    for s in sched:
        if s['送らない']:
            print('%s %s は「送らない」がチェックされています。' % (target, s['内容']))
            continue
        when = '%s・%s' % (target.replace('-', '/'), s['コース'])
        for p in people:
            if p['コース'] != s['コース'] or p['送る'] != 'はい':
                continue
            if not p['LINEWORKS_ID'].strip():
                print('⚠ %s のLINE WORKS IDが空です。送れません。' % p['氏名'])
                continue
            if s['宿題']:
                body = ('アカデミー（%s）の宿題のリマインドです。\n\n' % when
                        + '■ %s\n\n' % s['宿題'].replace('／', '\n■ '))
            else:
                # Notionに宿題が書かれていない回は、声かけだけ送る
                body = ('アカデミー（%s）から1週間がたちました。\n\n' % when
                        + '宿題は進みましたか。\n\n')
            text = ('%sさん\n' % p['氏名'] + body
                    + '提出はこちらから\n%s\n\n' % NOTION_URL
                    + '間に合わないときは、早めに声をかけてください。')
            msgs.append((p['氏名'], p['LINEWORKS_ID'].strip(), text))

    if not msgs:
        print('送る相手がいません。')
        return

    if DRY:
        for name, uid, text in msgs:
            print('--- %s 宛 ---\n%s\n' % (name, text))
        print('※ --dry-run のため送信していません。')
        return

    token = get_token()
    for name, uid, text in msgs:
        send(token, uid, text)
        print('送信：%s' % name)


if __name__ == '__main__':
    main()
