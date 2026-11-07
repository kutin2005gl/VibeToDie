package slackio

import (
	"testing"

	"github.com/slack-go/slack/slackevents"
)

func TestPlainText(t *testing.T) {
	cases := []struct{ in, want string }{
		{"email <mailto:a@b.vn|a@b.vn>.", "email a@b.vn."},
		{"xem <https://boa.vn/x|boa.vn/x>", "xem boa.vn/x"},
		{"xem <https://boa.vn>", "xem https://boa.vn"},
		{"xem <https://boa.vn/q|quy định>", "xem quy định (https://boa.vn/q)"},
		{"gọi <tel:0901|0901>", "gọi 0901"},
		{"<@UBOT> tra đơn 5", "tra đơn 5"},
		{"tra đơn <@UBOT> DH1001", "tra đơn DH1001"},
		{"<!here> kho Q1", "kho Q1"},
		{"báo <!subteam^S1|@cskh>", "báo @cskh"},
		{"đăng ở <#C1|cskh>", "đăng ở #cskh"},
		{"giá &lt; 10tr &amp; &gt; 5tr", "giá < 10tr & > 5tr"},
		{"&amp;lt; giữ nguyên", "&lt; giữ nguyên"},
		{"dòng 1\ndòng 2", "dòng 1\ndòng 2"},
		{"link ABC123", "link ABC123"},
	}
	for _, c := range cases {
		if got := PlainText(c.in); got != c.want {
			t.Errorf("PlainText(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

// The same request typed in Slack (session 140) and on the web (session 141) must reach the gateway
// as the same bytes.
func TestPlainTextMatchesWeb(t *testing.T) {
	const tail = ". Số tiền hoàn 9.432.000 ₫ (đã thanh toán 11.790.000 ₫, trừ phí khấu hao 20% là 2.358.000 ₫), sản phẩm OPPO Reno 12 256GB. Soạn thư và gửi ngay cho khách."
	slack := "Gửi email thông báo hoàn tiền đơn DH1014 cho khách Huỳnh Phúc Hoàng Nhật, địa chỉ email <mailto:nhattin1425@gmail.com|nhattin1425@gmail.com>" + tail
	web := "Gửi email thông báo hoàn tiền đơn DH1014 cho khách Huỳnh Phúc Hoàng Nhật, địa chỉ email nhattin1425@gmail.com" + tail
	if got := PlainText(slack); got != web {
		t.Fatalf("got  %q\nwant %q", got, web)
	}
}

func TestToMessageCleansDirectMessages(t *testing.T) {
	im := slackevents.EventsAPIEvent{InnerEvent: slackevents.EventsAPIInnerEvent{Data: &slackevents.MessageEvent{
		ChannelType: "im", Channel: "D1", User: "U1", Text: "<@UBOT> gửi <mailto:a@b.vn|a@b.vn>", TimeStamp: "1.1"}}}
	m, ok := toMessage(im)
	if !ok || m.Text != "gửi a@b.vn" {
		t.Fatalf("im: %+v %v", m, ok)
	}
}
