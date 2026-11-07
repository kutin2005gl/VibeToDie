package render

// Labels shared with the web. Each one is copied from the frontend file named beside it, so a
// room reads the same in Slack and on the web; labels_test.go compares the two.

// agentNames mirrors frontend/src/mocks/agentCatalog.ts (`name`).
var agentNames = map[string]string{
	"coordinator":      "Điều phối",
	"customer_service": "Chăm sóc khách hàng",
	"orders":           "Đơn hàng",
	"knowledge":        "Tra cứu quy trình",
	"executive":        "Điều hành",
	"it_support":       "Hỗ trợ IT",
	"factory":          "Xưởng agent",
}

// AgentName is the name staff know an agent by; an agent missing from the catalog keeps its id.
func AgentName(id string) string {
	if name, ok := agentNames[id]; ok {
		return name
	}
	return id
}

// The constants and tables below mirror frontend/src/api/sessions.ts.
const (
	notDone   = "Chưa hoàn thành phần việc này."
	routing   = "Đang chọn agent phù hợp…"
	replanned = "Một phần chưa làm được, lập lại kế hoạch cho phần còn lại."
	stopped   = "run stopped by staff"
)

// reviewed says what the Coordinator decided on a step when it wrote no note.
var reviewed = map[string]string{
	"accept":  "Đã duyệt.",
	"retry":   "Cần làm lại phần này.",
	"replan":  "Phần này cần lập lại kế hoạch.",
	"clarify": "Cần hỏi thêm bạn trước khi làm tiếp.",
}

// failedText retells the reasons the server itself writes when a run ends (ai/app/store/sessions.py).
var failedText = map[string]string{
	stopped:                                 "Bạn đã dừng lượt chạy này.",
	"run interrupted: ai-service restarted": "Lượt chạy bị ngắt vì hệ thống khởi động lại. Gửi lại yêu cầu.",
	"run ended without saving its result":   "Lượt chạy kết thúc nhưng không lưu được kết quả. Gửi lại yêu cầu.",
}

func reviewText(decision string) string {
	if t, ok := reviewed[decision]; ok {
		return t
	}
	return reviewed["accept"]
}
