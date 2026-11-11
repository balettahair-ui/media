# -*- coding: utf-8 -*-
"""アカデミーの宿題リマインダーを LINE WORKS で個別に送る。

考え方：きょう（日本時間）から7日前にアカデミーがあれば、その回の宿題を受講者へ送る。
GitHub Actions から毎朝1回呼ばれます。アカデミーのない日は何もしません。

読むファイル
  homework/reminder_schedule.csv   開催日・コース・宿題
  homework/reminder_people.csv     氏名・コース・LINE WORKS ID
認証情報は環境変数（GitHub の Secrets）から読みます。
"""
import csv, datetime, io, json, os, sys, time, urllib.request, urllib.parse

HERE   = os.path.dirname(__file__)
SCHED  = os.path.join(HERE, 'reminder_schedule.csv')
PEOPLE = os.path.join(HERE, 'reminder_people.csv')
NOTION_URL = 'https://app.notion.com/p/aaba4eb8935a44ed8a030e68ac9d0b57'
DRY = '--dry-run' in sys.argv


def env(k):
    v = os.environ.get(k, '').strip()
    if not v:
        sys.exit('環境変数 %s がありません。GitHub の Secrets を確認してください。' % k)
    return v


def rows(path):
    with io.open(path, encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


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
    target = today - datetime.timedelta(days=7)

    sched = [r for r in rows(SCHED) if r['開催日'] == target.isoformat()]
    if not sched:
        print('%s の7日前（%s）にアカデミーはありません。何もしません。' % (today, target))
        return

    people = rows(PEOPLE)
    msgs = []
    for s in sched:
        if '送信しない' in (s.get('確認') or ''):
            print('%s %s は送信対象外です（%s）' % (s['開催日'], s['コース'], s['確認']))
            continue
        hw = (s.get('宿題') or '').strip()
        if not hw:
            print('⚠ %s %s の宿題が予定表に入っていません。送信を見送ります。'
                  % (s['開催日'], s['コース']))
            continue
        for p in people:
            if p['コース'] != s['コース'] or p['送る'] != 'はい':
                continue
            if not p['LINEWORKS_ID'].strip():
                print('⚠ %s のLINE WORKS IDが空です。送れません。' % p['氏名'])
                continue
            text = (
                '{name}さん\n'
                'アカデミー（{d}・{course}）の宿題のリマインドです。\n\n'
                '■ {hw}\n\n'
                '提出はこちらから\n{url}\n\n'
                '間に合わないときは、早めに声をかけてください。'
            ).format(name=p['氏名'], d=s['開催日'].replace('-', '/'),
                     course=s['コース'], hw=hw.replace('／', '\n■ '), url=NOTION_URL)
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
