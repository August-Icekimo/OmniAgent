"""reply-quick-options 手動測試：確認往返的同意／取消判斷（整句比對）與 /chat 回覆選項。

單元部分（不需容器）：
    python test_reply_options.py

端到端（需 brain 在跑；會建立/清除 user_id=rqo-test 的 confirm:pending）：
    python test_reply_options.py --e2e

Go 端（LINE quickReply／Telegram inline keyboard 只掛最後一則、callback 首次點擊才算）：
    cd omni-agent/gateway && go test ./internal/messenger/ ./internal/handler/
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath('omni-agent/brain') if os.path.isdir('omni-agent/brain') else '/app')

from agent.confirm import CONFIRM_OPTIONS, is_affirmative, is_cancel

AFFIRM = ['好', '好！', '  好的。', 'OK', 'Yes!', '可以', '確認', '繼續', 'go']
NOT_AFFIRM = ['不好', '不可以', '好像不太對', '好啊但是等一下', '我覺得可以再想想', '取消', '', '不要', '確認一下這是什麼']
CANCEL = ['取消', '不要', '算了', 'No', '不用了～', 'cancel']
NOT_CANCEL = ['不要取消', '好', '取消啦你很煩那個', '我不要這個顏色']


def unit():
    for t in AFFIRM:
        assert is_affirmative(t), f'should affirm: {t!r}'
    for t in NOT_AFFIRM:
        assert not is_affirmative(t), f'should NOT affirm: {t!r}'
    for t in CANCEL:
        assert is_cancel(t), f'should cancel: {t!r}'
    for t in NOT_CANCEL:
        assert not is_cancel(t), f'should NOT cancel: {t!r}'
    # 按鈕送出的文字必定被正確判斷
    yes, no = CONFIRM_OPTIONS
    assert is_affirmative(yes['text']) and is_cancel(no['text'])
    assert all(len(o['label']) <= 20 and len(o['text'].encode()) <= 64 for o in CONFIRM_OPTIONS)
    print(f'unit: {len(AFFIRM)}/{len(NOT_AFFIRM)} affirm, {len(CANCEL)}/{len(NOT_CANCEL)} cancel cases ok')


def chat(text, i):
    body = json.dumps({'id': f'rqo-{i}', 'message_type': 'text', 'user_id': 'rqo-test',
                       'platform': 'test', 'text': text}).encode()
    req = urllib.request.Request('http://localhost:8000/chat', body, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=290) as r:
        return json.load(r)


def e2e():
    long_video = '看一下這支 https://www.youtube.com/watch?v=aqz-KE-bpKQ'  # 10:35 → 需確認
    r = chat(long_video, 1)
    assert r.get('options') == CONFIRM_OPTIONS, r
    r = chat('取消', 2)
    assert r['reply_text'] == '好，已取消。' and r['provider'] == 'none', r
    r = chat(long_video, 3)
    assert r.get('options') == CONFIRM_OPTIONS, r
    r = chat('不好', 4)  # 不能被當成同意
    assert 'Big Buck Bunny' not in r['reply_text'] and not r.get('options'), r
    print('e2e: options attached; 取消 short-circuits; 不好 does not resume')


if __name__ == '__main__':
    unit()
    if '--e2e' in sys.argv:
        e2e()
    print('ALL PASSED')
