export interface PromptSection {
  /** Tên thẻ XML (`role`, `procedure`, `output_schema`…), hoặc `text` cho phần nằm ngoài mọi thẻ */
  tag: string
  body: string
}

// Thẻ XML đứng riêng một dòng ở đầu dòng (mandate dẫn tên thẻ giữa câu bằng `<role>` nên không bị tách nhầm)
const BLOCK = /^<([a-z_]+)>\n([\s\S]*?)\n<\/\1>[ \t]*$/gm
// Dòng tiêu đề `# Role` đứng trước mỗi thẻ: tên thẻ đã thay nó
const HEADING = /^#{1,2} .*$/gm

/** Tách system prompt của mandate (Markdown trộn thẻ XML) thành các khối theo thứ tự xuất hiện. */
export function parsePrompt(prompt: string): PromptSection[] {
  const sections: PromptSection[] = []
  const loose = (text: string) => {
    const body = text.replace(HEADING, '').trim()
    if (body) sections.push({ tag: 'text', body })
  }
  let last = 0
  for (const m of prompt.matchAll(BLOCK)) {
    loose(prompt.slice(last, m.index))
    sections.push({ tag: m[1], body: m[2].trim() })
    last = m.index + m[0].length
  }
  loose(prompt.slice(last))
  return sections
}

/** Nhãn tiếng Việt của các thẻ đã biết; thẻ lạ hiện tên thẻ. */
const labels: Record<string, string> = {
  system_context: 'Bối cảnh hệ thống',
  invariants: 'Quy tắc bất biến',
  role: 'Vai trò',
  capabilities: 'Khả năng',
  procedure: 'Quy trình',
  business_rules: 'Quy tắc nghiệp vụ',
  output_schema: 'Định dạng kết quả',
  trust_boundary: 'Ranh giới tin cậy',
  permissions: 'Quyền hạn',
  grounding: 'Căn cứ dữ liệu',
  side_effects: 'Tác động ra ngoài',
  language: 'Ngôn ngữ',
  staff_writing: 'Cách viết cho nhân viên',
  output_contract: 'Hợp đồng đầu ra',
  result_contract: 'Hợp đồng kết quả',
  department_scope: 'Phạm vi phòng ban',
  consult_policy: 'Chính sách hỏi ý kiến',
  input_contract: 'Hợp đồng đầu vào',
  plan_phase: 'Giai đoạn lập kế hoạch',
  review_phase: 'Giai đoạn duyệt',
  finalize_phase: 'Giai đoạn tổng hợp',
  coordination_rules: 'Quy tắc điều phối',
  deliverable_writing: 'Cách viết kết quả',
  task_writing: 'Cách viết việc giao',
  final_response_style: 'Văn phong câu trả lời cuối',
  decision_table: 'Bảng quyết định',
  writing_style: 'Văn phong',
  agent_design_rules: 'Quy tắc thiết kế agent',
  self_check: 'Tự kiểm tra',
  text: 'Ghi chú',
}

export const sectionLabel = (tag: string) => labels[tag] ?? tag
