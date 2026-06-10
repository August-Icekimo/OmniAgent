package messenger

import (
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
