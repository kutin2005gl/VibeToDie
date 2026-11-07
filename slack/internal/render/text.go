package render

// Fixed messages. Everything staff read is Vietnamese; the bot is called Trợ lý BOA.
const (
	Working = "⏳ Đang xử lý…"

	NotLinked = "Bạn chưa liên kết tài khoản BOA, nên mình chưa trả lời được.\n" +
		"1. Đăng nhập web BOA → Cài đặt → Tài khoản → *Liên kết Slack* để lấy mã.\n" +
		"2. Gửi vào đây: `/boa link <mã>`"

	DMOnly = "Mình chỉ trả lời trong tin nhắn riêng, để dữ liệu (đơn hàng, email khách…) không lộ cho người khác trong channel. " +
		"Hãy nhắn riêng cho *Trợ lý BOA* (mục Apps trên Slack) và gửi lại câu hỏi ở đó."

	Relink = "Phiên liên kết của bạn đã hết hạn hoặc bị thu hồi. Hãy lấy mã mới trên web BOA (Cài đặt → Tài khoản → " +
		"*Liên kết Slack*) rồi gửi `/boa link <mã>`."

	Busy = "Mình vẫn đang xử lý lượt trước trong thread này. Đợi mình trả lời xong rồi hỏi tiếp nhé."

	OthersThread = "Thread này đang dùng cho yêu cầu của người khác. Hãy bắt đầu một thread mới hoặc nhắn riêng cho mình."

	RoomFull = "Cuộc trò chuyện trước đã đủ dài nên mình mở một phiên mới cho câu hỏi này."

	GoneSession = "Phiên cũ không còn nữa nên mình mở một phiên mới cho câu hỏi này."

	TooSlow = "Yêu cầu này đang chạy lâu hơn dự kiến. Bạn xem kết quả trên web BOA nhé."

	Failure = "⚠️ Có lỗi khi xử lý. Bạn thử gửi lại sau ít phút nhé."

	ApprovalNotice = "🔒 Yêu cầu này đang chờ duyệt. Bấm *Duyệt* hoặc *Từ chối* trên thẻ phía trên (hoặc mở web BOA)."

	// Answers to a click on the card, shown only to the person who clicked.
	AlreadyDecided  = "Yêu cầu này đã được xử lý rồi, mình không thực hiện lại."
	NotYourApproval = "Mình không tìm thấy yêu cầu này trong tài khoản của bạn, nên bạn không duyệt được. Chỉ người đã gửi yêu cầu mới duyệt hoặc từ chối được."

	Help = "*Trợ lý BOA* giúp bạn tra cứu đơn hàng, quy định và các việc CSKH từ Slack, với đúng quyền của bạn trên web.\n" +
		"• Nhắn riêng cho mình để đặt câu hỏi (trong channel mình không trả lời). Mỗi thread là một cuộc trò chuyện.\n" +
		"• `/boa link <mã>`: liên kết tài khoản (lấy mã ở web BOA → Cài đặt → Tài khoản)\n" +
		"• `/boa unlink`: huỷ liên kết\n" +
		"• `/boa status`: xem đã liên kết chưa\n" +
		"• `/boa help`: xem hướng dẫn này"

	LinkUsage       = "Cú pháp: `/boa link <mã>`. Lấy mã ở web BOA → Cài đặt → Tài khoản → *Liên kết Slack*."
	InvalidCode     = "Mã không đúng, đã hết hạn hoặc đã được dùng. Hãy tạo mã mới trên web BOA và thử lại."
	LinkFailed      = "Chưa liên kết được do lỗi hệ thống. Bạn thử lại sau ít phút nhé."
	NotLinkedStatus = "Bạn chưa liên kết tài khoản BOA. Gửi `/boa link <mã>` để bắt đầu (xem `/boa help`)."
	Unlinked        = "Đã huỷ liên kết. Mình sẽ không trả lời bạn cho tới khi bạn liên kết lại."
	UnlinkedPartial = "Đã huỷ liên kết ở Slack, nhưng chưa thu hồi được phiên trên máy chủ (phiên sẽ tự hết hạn)."
)

// Linked is the answer to a good `/boa link`.
func Linked(who string) string {
	return "✅ Đã liên kết với tài khoản BOA *" + Mrkdwn(who) + "*. Giờ bạn có thể nhắn riêng để đặt câu hỏi."
}

// LinkedStatus is the answer to `/boa status` for a linked person.
func LinkedStatus() string {
	return "✅ Bạn đã liên kết tài khoản BOA. Mình trả lời với quyền của tài khoản đó."
}
