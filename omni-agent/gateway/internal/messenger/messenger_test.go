package messenger

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestChunkText(t *testing.T) {
	cases := []struct {
		name      string
		text      string
		size      int
		wantParts int
		wantLast  string
	}{
		{"短文不切", "hello", 4500, 1, "hello"},
		{"剛好等於上限", strings.Repeat("a", 10), 10, 1, strings.Repeat("a", 10)},
		{"超過一字切兩段", strings.Repeat("a", 11), 10, 2, "a"},
		{"中文以 rune 計數", strings.Repeat("家", 12), 10, 2, strings.Repeat("家", 2)},
		{"三段", strings.Repeat("x", 25), 10, 3, strings.Repeat("x", 5)},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := chunkText(c.text, c.size)
			if len(got) != c.wantParts {
				t.Fatalf("段數 = %d, 預期 %d", len(got), c.wantParts)
			}
			if got[len(got)-1] != c.wantLast {
				t.Errorf("末段 = %q, 預期 %q", got[len(got)-1], c.wantLast)
			}
			if strings.Join(got, "") != c.text {
				t.Errorf("重組後與原文不符")
			}
		})
	}
}

func TestChunkTextUTF16(t *testing.T) {
	cases := []struct {
		name      string
		text      string
		size      int
		wantParts int
	}{
		{"短文不切", "hello", 10, 1},
		{"BMP 中文每字 1 unit", strings.Repeat("家", 12), 10, 2},
		{"emoji 每個 2 units", strings.Repeat("😀", 6), 10, 2},
		{"剛好等於上限", strings.Repeat("a", 10), 10, 1},
		{"空字串", "", 10, 1},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := chunkTextUTF16(c.text, c.size)
			if len(got) != c.wantParts {
				t.Fatalf("段數 = %d, 預期 %d (%q)", len(got), c.wantParts, got)
			}
			if strings.Join(got, "") != c.text {
				t.Errorf("重組後與原文不符")
			}
		})
	}
}

func TestReplyTokenUsable(t *testing.T) {
	now := time.Now().Unix()
	cases := []struct {
		name string
		opts *SendOptions
		want bool
	}{
		{"nil opts", nil, false},
		{"無 token", &SendOptions{ReplyTokenExpiresAt: now + 50}, false},
		{"已過期", &SendOptions{ReplyToken: "t", ReplyTokenExpiresAt: now - 1}, false},
		{"零值過期時間", &SendOptions{ReplyToken: "t"}, false},
		{"有效", &SendOptions{ReplyToken: "t", ReplyTokenExpiresAt: now + 50}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := c.opts.replyTokenUsable(); got != c.want {
				t.Errorf("replyTokenUsable() = %v, 預期 %v", got, c.want)
			}
		})
	}
}

// --- reply-quick-options ---

var confirmOpts = []ReplyOption{{Label: "好，繼續", Text: "好"}, {Label: "取消", Text: "取消"}}

func TestParseReplyOptions(t *testing.T) {
	if got := ParseReplyOptions(nil); got != nil {
		t.Fatalf("nil → %v", got)
	}
	if got := ParseReplyOptions([]byte(`not json`)); got != nil {
		t.Fatalf("bad json → %v", got)
	}
	got := ParseReplyOptions([]byte(`[{"label":"好，繼續","text":"好"},{"label":"","text":"x"},{"label":"取消","text":"取消"}]`))
	if len(got) != 2 || got[0].Text != "好" || got[1].Label != "取消" {
		t.Fatalf("parse → %+v", got)
	}
}

func TestBuildLineMessagesQuickReplyOnLastOnly(t *testing.T) {
	long := strings.Repeat("字", lineChunkSize*7+10) // 8 段 → 跨兩批
	msgs := buildLineMessages(long, &SendOptions{QuoteToken: "q", QuickReplies: confirmOpts})
	if len(msgs) != 8 {
		t.Fatalf("want 8 chunks, got %d", len(msgs))
	}
	for i, m := range msgs[:len(msgs)-1] {
		if m.QuickReply != nil {
			t.Fatalf("chunk %d should not carry quick reply", i)
		}
	}
	last := msgs[len(msgs)-1]
	if last.QuickReply == nil || len(last.QuickReply.Items) != 2 {
		t.Fatalf("last chunk quick reply missing: %+v", last.QuickReply)
	}
	a := last.QuickReply.Items[0].Action
	if last.QuickReply.Items[0].Type != "action" || a.Type != "message" || a.Label != "好，繼續" || a.Text != "好" || a.Data != "" {
		t.Fatalf("bad action: %+v", a)
	}
	if msgs[0].QuoteToken != "q" || msgs[1].QuoteToken != "" {
		t.Fatal("quote token should be on first chunk only")
	}
	// JSON：message action 不帶 data 欄位
	b, _ := json.Marshal(last)
	if strings.Contains(string(b), `"data"`) || !strings.Contains(string(b), `"quickReply"`) {
		t.Fatalf("unexpected json: %s", b)
	}
}

func TestBuildLineMessagesNoOptions(t *testing.T) {
	msgs := buildLineMessages("hi", &SendOptions{})
	b, _ := json.Marshal(msgs)
	if strings.Contains(string(b), "quickReply") {
		t.Fatalf("no options should omit quickReply: %s", b)
	}
	if msgs := buildLineMessages("hi", nil); len(msgs) != 1 {
		t.Fatal("nil opts")
	}
}

func TestBuildLineQuickReplyLimits(t *testing.T) {
	var many []ReplyOption
	for i := 0; i < 20; i++ {
		many = append(many, ReplyOption{Label: strings.Repeat("長", 30), Text: "x"})
	}
	qr := buildLineQuickReply(many)
	if len(qr.Items) != lineQuickReplyMaxItems {
		t.Fatalf("items %d", len(qr.Items))
	}
	if n := len([]rune(qr.Items[0].Action.Label)); n != lineQuickReplyMaxLabel {
		t.Fatalf("label len %d", n)
	}
}

func TestBuildTelegramPayloadsKeyboardOnLastOnly(t *testing.T) {
	long := strings.Repeat("a", telegramChunkSize*2+5) // 3 段
	ps := buildTelegramPayloads("123", long, &SendOptions{ReplyToMessageID: "42", QuickReplies: confirmOpts})
	if len(ps) != 3 {
		t.Fatalf("want 3 chunks, got %d", len(ps))
	}
	if _, ok := ps[0]["reply_parameters"]; !ok {
		t.Fatal("first chunk should reply-to")
	}
	if _, ok := ps[1]["reply_parameters"]; ok {
		t.Fatal("only first chunk reply-to")
	}
	for i := 0; i < 2; i++ {
		if _, ok := ps[i]["reply_markup"]; ok {
			t.Fatalf("chunk %d should not carry keyboard", i)
		}
	}
	b, _ := json.Marshal(ps[2]["reply_markup"])
	want := `{"inline_keyboard":[[{"callback_data":"好","text":"好，繼續"},{"callback_data":"取消","text":"取消"}]]}`
	if string(b) != want {
		t.Fatalf("keyboard json\n got %s\nwant %s", b, want)
	}
}

func TestTelegramCallbackDataLimit(t *testing.T) {
	kb := buildTelegramInlineKeyboard([]ReplyOption{{Label: "長", Text: strings.Repeat("字", 30)}}) // 90 bytes
	if kb != nil {
		t.Fatalf("oversized callback_data should be skipped: %v", kb)
	}
	if ps := buildTelegramPayloads("1", "hi", &SendOptions{}); ps[0]["reply_markup"] != nil {
		t.Fatal("no options → no keyboard")
	}
}
