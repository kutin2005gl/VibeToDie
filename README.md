# BOA — Multi-agent CSKH cho cửa hàng điện thoại

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `gateway/` | API gateway Go (Gin): xác thực JWT, rate limit, timeout/retry, proxy tới user, orders, ai |
| `user-service/` | Go API (`net/http` + pgx): tài khoản, đăng nhập, phòng ban, ký access token cho gateway |
| `order-service/` | Go API: đơn hàng, sản phẩm, tồn kho (HTTP qua gateway, gRPC cho ai-service) |
| `ai-service/` | Python FastAPI: Jev (định tuyến), agent, Coordinator, session/room, gọi Anthropic/OpenAI/DeepSeek |
| `slack/` | Bot Slack cho nhân viên (Socket Mode), xem [slack/README.md](slack/README.md) |
| `frontend/` | Giao diện Next.js (App Router), server Next làm BFF giữ token trong cookie HttpOnly |
| `proto/` | Contract gRPC giữa ai-service và order-service |

## Chạy

```bash
cp .env.example .env        # điền ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY, và JWT_SECRET (≥ 32 ký tự, bắt buộc)
docker compose up --build
```

Thử luồng chính:

```bash
# /api/sessions cần token: đăng nhập bằng tài khoản BOOTSTRAP_ADMIN_* (hoặc tài khoản đã được cấp phòng ban)
TOKEN=$(curl -s -X POST localhost:8080/api/users/login -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"..."}' | jq -r .access_token)
# Tạo session (room): trả 201 status "running", lượt chạy tiếp tục ở nền
curl -X POST localhost:8080/api/sessions -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Khách mua iPhone 3 ngày đã lỗi màn hình, muốn hoàn tiền"}'
# Theo dõi tiến độ (SSE) tới khi hết "running"; kết quả nằm trong session
curl -N localhost:8080/api/sessions/<id>/events -H "Authorization: Bearer $TOKEN" -H "Accept: text/event-stream"
# Khi session "waiting" với item approval: duyệt hoặc từ chối hành động đề xuất
curl -X POST localhost:8080/api/sessions/<id>/decision -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"approve":true}'
```

Cổng 8080 là gateway; web (frontend) mở cổng 3000. Các service còn lại (user, order, ai, embedding, slack) không mở cổng nên không ai đi vòng qua gateway được. Nếu cổng bị chiếm: đặt `GATEWAY_PORT=18080` trong `.env`.

Provider là `anthropic`, `openai`, `deepseek` (`DEEPSEEK_API_KEY`), hoặc `fake` (offline, chỉ khi `AI_ALLOW_FAKE=1`). Mọi request chạy trên provider admin đã chọn (`PUT /api/admin/provider`, mặc định `AI_DEFAULT_PROVIDER`); `provider` trong body chỉ có tác dụng khi bật `AI_ALLOW_PROVIDER_OVERRIDE=1`.

Tìm quy định mặc định dùng BM25 trong bộ nhớ. Service `embedding` (TEI, `multilingual-e5-small`, khoảng 2 GB RAM, không mở cổng) phục vụ chế độ `AI_RETRIEVER=hybrid`; lần đầu chạy nó tải trọng số từ Hugging Face, và nếu nó không lên thì ai-service vẫn chạy bằng BM25. Nạp chunk vào Postgres: `docker compose exec ai python -m app.knowledge.ingest` (chạy lại không nhúng lại). Chi tiết ở [ai-service/README.md](ai-service/README.md).

Giao diện (web): `cd frontend && npm install && npm run dev` rồi mở http://localhost:3000. Server Next là BFF: trình duyệt chỉ gọi `/api/*` cùng origin, Next chuyển tới gateway ở `GATEWAY_URL` (mặc định `http://localhost:8080`). Đăng nhập bằng email + mật khẩu của user-service (tài khoản đầu tiên: `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD`). Token nằm trong cookie HttpOnly (`boa_at`, `boa_rt`), JS không đọc được; Next tự làm mới token, refresh thất bại thì xoá cookie và web về màn đăng nhập. Gateway thấy IP của Next, nên đặt `TRUSTED_PROXIES` là IP đó để rate limit theo IP người dùng.

## API

### gateway (`gateway/`, cổng 8080)

Mọi client gọi qua gateway. Bảng route ở [gateway/configs/routes.yaml](gateway/configs/routes.yaml); prefix bị cắt trước khi chuyển tiếp (`/api/ai/run` → `/run`), trừ `/api/orders`, `/api/products`, `/api/sessions` và `/api/admin` (giữ prefix).

| Prefix | Upstream (env) | Xác thực | Timeout | Rate limit |
| --- | --- | --- | --- | --- |
| `/api/users` | user-service (`USER_SERVICE`) | optional | 5s | 60/phút |
| `/api/slack-links/redeem` | user-service `/slack-links/redeem` | none | 5s | 60/phút |
| `/api/orders` | order-service (`ORDERS_SERVICE`, giữ prefix) | required | 5s | 30/phút |
| `/api/products` | order-service (`ORDERS_SERVICE`, giữ prefix) | required | 5s | 30/phút |
| `/api/ai` | ai-service (`AI_SERVICE`) | required | 180s (SSE: 10 phút) | 10/phút |
| `/api/sessions` | ai-service (`AI_SERVICE`, giữ prefix) | required | 15s (SSE: 10 phút) | 60/phút |
| `/api/admin` | ai-service (`AI_SERVICE`, giữ prefix) | required | 15s | 60/phút |

- Access token: JWT HS256 do user-service ký bằng `JWT_SECRET` (ít nhất 32 ký tự, gateway không chạy nếu ngắn hơn), `iss` = `JWT_ISSUER`, bắt buộc `exp`. Claims: `sub` (user id), `email`, `departments` (mảng, ví dụ `["cskh"]`).
- Token hợp lệ: gateway xoá header `Authorization: Bearer`, gửi xuống `X-User-Id`, `X-User-Email`, `X-User-Departments` (nối bằng dấu phẩy). Các header `X-User-*` do client tự gửi luôn bị xoá, ở mọi route. Không có token (route optional): upstream không nhận header `X-User-*` nào.
- Body mỗi request tối đa 1 MiB (đổi theo route bằng `max_body`, tính bằng byte).
- Lỗi do gateway trả: 401 thiếu/sai token, 413 body quá lớn, 429 vượt rate limit (kèm `Retry-After`), 502 upstream không gọi được, 503 circuit breaker đang mở, 504 quá timeout. Body `{"error": "..."}`.
- SSE (`/api/ai/run`): request có `Accept: text/event-stream` được giới hạn bằng `stream_timeout` (10 phút) thay cho `timeout`, và từng event được đẩy ngay tới client. Nếu ai-service rớt giữa chừng, gateway cắt kết nối để client thấy stream bị đứt, không phải kết thúc bình thường. Client phải dùng `fetch` đọc stream (POST, gửi được header `Authorization`), không dùng `EventSource` (chỉ hỗ trợ GET, không gửi được header).
- Chỉ GET/HEAD/OPTIONS được thử lại; POST chỉ gửi một lần. Mọi response có `X-Request-Id`, được chuyển tiếp xuống upstream.
- `GET /healthz` → `{status: ok|degraded, upstreams: {user, slack-redeem, orders, products, ai, sessions, admin: ok|down}}`, luôn 200.
- Lấy token: `POST /api/users/login` (xem user-service). Token dev không cần DB: `cd gateway && JWT_SECRET=<giá trị trong .env> JWT_ISSUER=nexus go run ./cmd/devtoken -departments cskh`. `JWT_ISSUER` mặc định `nexus` (đổi trong `.env` thì khởi tạo lại container gateway và user-service để hai bên cùng giá trị).

### order-service (`order-service/`, sau gateway ở `/api/orders` và `/api/products`, không mở cổng ra ngoài)

| Method | Path | Xác thực | Ghi chú |
| --- | --- | --- | --- |
| GET | `/healthz` | | kiểm tra DB |
| GET | `/api/orders/{order_id}` | `cskh`, `executive` | object đơn hàng phẳng, có `customer_email` (`null` nếu đơn chưa có email); 400 nếu sai regex `^DH\d+$`, 404 nếu không có |
| GET | `/api/products/{product_id}` | `cskh`, `executive` | object sản phẩm phẳng, 400 nếu sai regex `^P\d+$`, 404 nếu không có |
| GET | `/api/products?q={tên}&limit=5` | `cskh`, `executive` | `{"items":[{"product_id","name","price"}]}`, tìm không phân biệt dấu, 400 nếu `q` < 2 ký tự |
| GET | `/api/products/{product_id}/stock` | `cskh`, `executive` | `{"product_id":"P001","stock_total":14,"by_store":{"CN Quận 1":8,...}}` |

#### gRPC nội bộ (ai-service → order-service, chỉ đọc, không qua gateway)

Contract ở [proto/orders/v1/orders.proto](proto/orders/v1/orders.proto): `GetOrder`, `GetProduct`, `SearchProducts`, `GetStock`; tên trường trùng JSON của HTTP nên `claims.ref.path` của agent không đổi. Mã Python sinh vào `ai-service/app/pb/` bằng `cd ai && .venv/Scripts/python scripts/gen_proto.py` (commit cả file sinh ra).

- ai-service dùng gRPC khi có cả `ORDERS_GRPC_ADDR` (ví dụ `order-service:9090`) và `INTERNAL_TOKEN`; thiếu một trong hai thì dùng HTTP (`ORDERS_SERVICE_URL`), rồi stub.
- Metadata mỗi call: `x-internal-token` (bí mật chung), `x-user-id`, `x-user-departments` (phân tách bằng dấu phẩy, cần `cskh` hoặc `executive`). Deadline 3s.
- Mã lỗi: `NOT_FOUND`, `INVALID_ARGUMENT` (sai định dạng id, `query` < 2 ký tự), `UNAUTHENTICATED` (sai token hoặc thiếu `x-user-id`), `PERMISSION_DENIED` (sai phòng ban), `UNAVAILABLE`.


### user-service (`user-service/`, sau gateway ở `/api/users`, không mở cổng ra ngoài)

Gateway cắt prefix: `/api/users/login` → `/login`. Route private đọc `X-User-Id` do gateway đặt; vì vậy service không được mở cổng ra ngoài.

| Method | Path | Xác thực | Ghi chú |
| --- | --- | --- | --- |
| GET | `/healthz` | | kiểm tra DB |
| POST | `/register` | | `{email, password, name}` → 201 user, chưa có phòng ban; 409 email đã có |
| POST | `/login` | | `{email, password}` → session; 401 sai email hoặc mật khẩu (cùng một thông báo) |
| POST | `/refresh` | | `{refresh_token}` → session mới, token cũ hết dùng; dùng lại token cũ thì cả phiên bị thu hồi (401) |
| POST | `/logout` | | `{refresh_token}` → 204, thu hồi phiên |
| GET | `/me` | token | user hiện tại |
| POST | `/slack-links` | token | → 201 `{code, expires_at}`: mã dùng một lần (10 ký tự, hạn 10 phút) để liên kết tài khoản Slack; chỉ lưu hash |
| GET | `/slack-links` | token | → `{linked, linked_at?, links}`: có phiên Slack còn sống hay không; `linked_at` là lúc đổi mã của liên kết cũ nhất; `links` = `[{linked_at, account?: {slack_user_id, user_name?, real_name?, team_id?, team_domain?}}]`, cũ trước, `account` do bot báo lúc đổi mã (không có ở liên kết cũ), chỉ để hiển thị |
| DELETE | `/slack-links` | token | → 204: thu hồi mọi phiên Slack của user (bot nhận 401 ở lần refresh kế và bỏ liên kết); phiên web giữ nguyên; gọi lại vẫn 204 |
| POST | `/slack-links/redeem` | | `{code, slack?: {slack_user_id, user_name?, real_name?, team_id?, team_domain?}}` → session mới (cùng dạng `/login`, họ refresh token riêng, `departments` tính lúc đổi); 401 mã sai, hết hạn hoặc đã dùng (cùng một thông báo); `slack` sai dạng → 400 và mã chưa bị dùng. Gateway phục vụ ở `/api/slack-links/redeem` (không qua `/api/users`), không cần token, giới hạn 60/phút |
| GET | `/users` | `executive` | danh sách user |
| PUT | `/users/{id}/departments` | `executive` | `{departments: [...]}` thuộc `cskh`, `executive`, `it`; không tự bỏ `executive` của chính mình (409) |

- User: `{id, email, name, departments, created_at}`. Session: `{access_token, token_type: "Bearer", expires_in, refresh_token, user}`.
- Access token sống 15 phút (`ACCESS_TOKEN_TTL`), refresh token 7 ngày (`REFRESH_TOKEN_TTL`). Đổi phòng ban có hiệu lực ở gateway từ lần refresh kế tiếp; quyền admin thì kiểm tra theo DB ngay.
- Admin đầu tiên: đặt `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` trong `.env`, service tạo tài khoản `executive` khi khởi động nếu email chưa có.
- Schema ở `user-service/internal/store/schema.sql`, service tự áp dụng mỗi lần khởi động (cả với volume DB đã có).
- DB: mặc định là container `db`; đặt `USER_DATABASE_URL` trong `.env` để dùng Postgres khác (ví dụ Neon, `sslmode=require`).

### ai-service (`ai-service/`, cổng 8000 trong mạng compose, không mở ra ngoài)

| Method | Path | Ghi chú |
| --- | --- | --- |
| GET | `/healthz` | `{status, providers}`: profile trong `ai-service/app/models.json` đã có key, cộng `fake` nếu bật |
| POST | `/run` | `{task_id, text, provider?, agent?, clarifications?}` (`provider` chỉ có tác dụng khi `AI_ALLOW_PROVIDER_OVERRIDE=1`, còn lại dùng provider admin đã chọn) → Jev chọn nhánh, rồi chạy một agent hoặc Coordinator |
| GET | `/api/sessions` | session của người gọi (theo `X-User-Id`), mới nhất trước, tối đa 50 |
| GET | `/api/sessions/agents` | agent riêng đã duyệt của người gọi (Factory soạn, cũ nhất trước): `[{id, name, description, role, tools, approved_at}]`; người khác không thấy |
| GET | `/api/sessions/{id}` | một session; của người khác → 404 |
| POST | `/api/sessions/{id}/stop` | dừng lượt chạy đang diễn ra (huỷ cả lượt gọi model đang dở) → 202; session được lưu `failed` với item `failed` `{body: "run stopped by staff"}` ngay sau đó; không chạy → 409 |
| DELETE | `/api/sessions/{id}` | ẩn session khỏi nhân viên → 204 (admin vẫn thấy cùng chi phí và trace); của người khác → 404; còn `running` → 409 |
| GET | `/api/sessions/{id}/events` | SSE (`text/event-stream`): theo dõi lượt chạy đang diễn ra (bên dưới); của người khác → 404 |
| POST | `/api/sessions` | `{text, origin?}` → 201 session `running` ngay; `origin` do client ngoài web gửi (bot Slack): `{kind: "slack", channel, thread_ts, permalink?}` (`channel` chữ hoa/số ≤ 32 ký tự, `thread_ts` dạng `1730700000.123456`, `permalink` chỉ nhận `https://*.slack.com/…` ≤ 500 ký tự, thừa trường → 422), có thì `source` là `kind`, không có thì `web`; chạy trên provider admin đã chọn (xem `/api/admin/provider`), `provider` trong body bị bỏ qua trừ khi bật `AI_ALLOW_PROVIDER_OVERRIDE=1`; luồng `/run` chạy nền rồi lưu kết quả. Provider không dùng được → 422/503, không lưu gì |
| POST | `/api/sessions/{id}/answer` | `{answer}` cho câu `clarify` đang chờ → 200 session `running`, chạy lại nền kèm mọi `clarifications`; không chờ trả lời → 409 |
| POST | `/api/sessions/{id}/messages` | `{text}`: yêu cầu mới trong room có lượt trước đã xong (`done`/`failed`) → 200 session `running`, chạy nền như `/api/sessions` và đọc room context của các lượt trước; đang `running`/`waiting` → 409; đủ 20 lượt → 409 `room is full` |
| POST | `/api/sessions/{id}/decision` | `{approve}` cho `approval` đang chờ → session `done`. Đồng ý thì chạy từng hành động một lần với quyền người duyệt, không tự thử lại; mỗi `actions[i]` thêm `status` (`done` \| `failed`, kèm `error`) và `at`; `sending` còn lại nghĩa là service dừng giữa chừng, chưa rõ kết quả. Với `agent_proposal` đang chờ: đồng ý thì agent thành `active` (chỉ của người này) và session `running`, Điều phối lập lại plan với agent đó (không qua Jev); từ chối thì agent `rejected`, session `done`. Không chờ duyệt, hoặc đã quyết định rồi → 409 |
| GET | `/api/admin/usage` | admin: chi phí theo phòng ban `[{department, sessions, input_tokens, output_tokens, cost_usd, unpriced_calls}]`, nhiều nhất trước |
| GET | `/api/admin/usage/{department}` | admin: cùng dạng, theo `user_id` trong phòng ban đó |
| GET | `/api/admin/provider` | admin: `{provider, available}`; `provider` là provider mọi request đang chạy trên đó (mặc định `deepseek`, đổi bằng `AI_DEFAULT_PROVIDER` tới khi admin chọn), `available` là các profile trong `ai-service/app/models.json` đã có key, cộng `fake` nếu bật |
| PUT | `/api/admin/provider` | admin: `{provider}` → như GET; provider không nằm trong `available` → 422. Áp dụng cho mọi lượt chạy bắt đầu sau đó, kể cả câu trả lời clarify và request tiếp theo trong room cũ (`provider` của room ghi theo lượt chạy mới nhất) |
| GET | `/api/admin/agents` | admin: mọi agent theo file mandate `[{name, description, tools, includes, departments, model_tier, effort, models, prompt}]`; `models` là id model config theo từng provider profile của `model_tier` (`ai-service/app/models.json`); `prompt` là system prompt đầy đủ (`_base` + phần dùng chung + mandate); `departments` rỗng là agent nội bộ, `["*"]` là mọi phòng ban |
| GET | `/api/admin/analytics?days=N` | admin: báo cáo N ngày gần nhất (`days` 1–366, mặc định 7; ngày cắt theo giờ Việt Nam, hôm nay tính là ngày cuối), cộng từ trace các lượt chạy: `{days, stats: {agents, rooms, runs, models, llm_calls, tool_calls, errors, input_tokens, output_tokens, cost_usd, unpriced_calls}, per_day: [{day: "MM-DD", runs, events, by_agent, by_type, <usage>}], per_agent: [{agent, sessions, llm_calls, tool_calls, errors, last, <usage>}], per_model: [{model, calls, <usage>}], per_room: [{id, title, runs, last, <usage>}], top_tools: [{name, count}]}`; `events` là các event `llm_call`, `tool_call`, `tool_result`, `run_failed`; `errors` là `tool_result` lỗi và `run_failed`; các bảng xếp theo `cost_usd` giảm dần |
| GET | `/api/admin/users/{user_id}/sessions?source=` | admin: mọi session của user, kể cả đã xóa; `source` (`web` \| `slack`, không bắt buộc) lọc theo nơi mở room, giá trị khác → 422. `[{id, title, provider, status, departments, source, origin, created_at, updated_at, deleted_at, runs, input_tokens, output_tokens, cost_usd, unpriced_calls}]` (chi phí cả session, không chia) |
| GET | `/api/admin/sessions/{id}` | admin: session (như trên, thêm `deleted_at`) cùng `runs: [{run, started_at, trace, input_tokens, output_tokens, cost_usd, unpriced_calls}]`; không có → 404 |

**Admin** (`/api/admin/*`, gateway giữ nguyên đường dẫn): chỉ người thuộc phòng ban `ADMIN_DEPARTMENT` (mặc định `executive`, như user-service), không phải → 403. Mỗi lượt chạy của session (yêu cầu đầu `run: 0`, mỗi yêu cầu mới hoặc câu trả lời clarify sau đó thêm 1) được lưu `trace` đầy đủ: mọi event SSE bên dưới kèm `event` và `at`, cộng thêm phần chỉ admin thấy: `llm_call` `{agent, step, model, prompt_tokens, completion_tokens, cost_usd, duration_ms, attempts, finish_reason, text}`, `agent_finished` `{agent, status, reason, steps, prompt_tokens, completion_tokens}`, `arguments` trên `tool_call`, `content` trên `tool_result` (`text`, `arguments`, `content` cắt ở 4000 ký tự), và `run_failed` `{body}` khi lượt chạy thất bại. Session do chính admin tạo nhận luôn phần chỉ admin thấy này trên SSE `/api/sessions/{id}/events` trong lúc chạy. `cost_usd` tính theo giá trong `ai-service/app/models.json` lúc gọi (`peak`: giá giờ cao điểm), `null` nếu model chưa có giá (đếm vào `unpriced_calls`); token cache tính theo giá input thường. Chi phí một session chia đều cho các phòng ban của người tạo lúc tạo; session cũ chưa ghi phòng ban vào phòng `-`.

**Session** (màn nhân viên): `{id, user_id, title, provider, status, items, clarifications, created_at, updated_at, departments, turns, context, source, origin}`. `source`: nơi mở room, `web` \| `slack`; `origin`: `{}` với web, với Slack là `{kind, channel, thread_ts, permalink?}` client gửi lúc tạo (không đối chiếu với Slack, chỉ để admin lọc và mở lại thread). Một session là một room gồm nhiều lượt: mỗi item `request` bắt đầu một lượt; `clarifications` chỉ thuộc lượt hiện tại. `status`: `running` \| `waiting` (có câu `clarify`, `approval` hoặc `agent_proposal` chờ nhân viên) \| `done` \| `failed`. `items` là thread theo thứ tự, mỗi item `{id, kind, at, ...}`: `request`/`reply` `{body}`, `route` `{agent, branch}`, `clarify` `{question, answer?}`, `result` `{agent, output, result, trace}`, `approval` `{actions, decision?}`, `agent_proposal` `{agent_id, name, description, tools, summary, decision?}` (agent Factory soạn khi Điều phối trả `request_agent`; đã qua kiểm tra của code, chưa chạy trước khi được đồng ý), `failed` `{body, trace}`; `trace` là các công cụ lượt chạy đã gọi `[{agent, name, id, ok}]` (`ok: false` khi công cụ trả lỗi). Service còn lưu `checkpoint` của lượt vừa lỗi ở Coordinator (plan, step đã xong, câu trả lời chờ duyệt) để "làm lại" chạy tiếp; không response nào trả nó về client. Run chạy nền nên client theo dõi `GET /api/sessions/{id}/events` tới khi hết `running`. Khởi động lại ai-service thì session còn `running` thành `failed` (giả định chỉ chạy một instance); session `running` mà tiến trình không còn lượt chạy nào (lưu kết quả bị lỗi) cũng thành `failed` khi có client theo dõi nó. Lưu kết quả được thử lại một lần nếu kết nối DB bị đóng giữa chừng. Lưu ở Postgres theo `AI_DATABASE_URL` (ví dụ Neon), service tự tạo bảng khi khởi động; để trống thì lưu trong bộ nhớ.

**Room context** (`ai-service/app/core/compaction.py`): mỗi lượt xong để lại một digest trong `turns`: `{turn, request, agent, outcome, summary, facts, open_questions}`.
- Digest do code tạo từ kết quả đã qua kiểm tra, không có tool trace. `request` và `summary` bị cắt bớt, `facts` là các claim `fact` dạng `key: value`, bỏ fact trích từ request và chuỗi dài hơn 200 ký tự (đoạn trích tài liệu, lượt sau tra lại). `outcome` là `done`, `failed`, `awaiting_approval`, `approved` hoặc `rejected`.
- Từ lượt 2 trở đi, Jev và mọi agent (worker, các phase plan/finalize của Coordinator, worker trong step) đọc block `<room_context>`.
- Jev nhận state `{earlier_in_room, request}`. Lượt 1 vẫn gửi text như cũ.
- Agent trích fact của lượt trước bằng `ref {call_id: "room:t<turn>", path: <key>}`; verifier kiểm như `step:<id>`.
- Room context giới hạn khoảng 2000 token (ước tính). Vượt mức đó thì mandate `compactor` (tier cheap) gộp các lượt cũ hơn 3 lượt gần nhất vào một bản tóm tắt cuộn. Code kiểm từng fact được giữ lại, rồi tóm tắt được lưu vào `context` `{through_turn, summary, facts, open_questions}`.
- Gộp lỗi hoặc không làm room nhỏ đi thì bỏ bớt digest cũ nhất (luôn giữ lượt mới nhất). Lượt chạy không fail vì compaction; model call của compactor nằm trong trace và chi phí của lượt đó.

**SSE của `GET /api/sessions/{id}/events`**: gửi `Accept: text/event-stream` để gateway giữ stream tới 10 phút. Event của lượt chạy được giữ tới khi lượt đó xong, nên client kết nối muộn hoặc kết nối lại (tải lại trang) nhận lại từ đầu. Đóng stream không dừng lượt chạy; event chỉ có ở tiến trình đang chạy nó (một instance).

| Event | `data` |
| --- | --- |
| `route`, `step`, `tool_call`, `tool_result`, `phase`, `plan`, `step_started`, `step_accepted`, `step_failed`, `step_skipped` | như SSE của `/run`, từ đầu lượt chạy hiện tại; mỗi `data` có thêm `at` (ISO, lúc máy chủ phát event) |
| `: ping` (comment) | sau mỗi 15 giây không có event |
| `session` | session đã lưu khi lượt chạy xong, hoặc ngay khi session không còn `running`; event cuối |

`/run` trả `{provider, model, output, input_tokens, output_tokens}` như trước, thêm `agent`, `steps`, `result` (JSON `final_answer` của mandate, gồm `status` và `claims`) và `pending_actions` (hành động chờ duyệt, chưa chạy). Lỗi: 422 agent/provider không hợp lệ, 503 thiếu key hoặc model, 502 agent chạy không xong. Model theo hạng của mandate (`strong`/`standard`/`cheap`) cấu hình trong `ai-service/app/models.json`. Header `X-User-Id`, `X-User-Departments` chỉ được tin khi `AI_TRUST_IDENTITY_HEADERS=1` (sau gateway Go).

**Nhánh `procedure`** (câu hỏi quy định, agent `knowledge`): ai-service tìm trong `ai-service/app/knowledge/sop/` trước, chỉ trên tài liệu người hỏi được xem. Không đoạn nào đủ liên quan thì không gọi model: 200 với `output` = "Không tìm thấy quy định liên quan trong tài liệu bạn được xem.", `result.status` = `blocked`, `steps` và token đều 0. Có đoạn liên quan thì agent nhận chúng sẵn và trả lời như nhánh `single`; mỗi `fact` trích tài liệu có `ref = {call_id: "retrieved" | "search_sop"…, path: "<DOC-ID>#<khoản>"}` (ví dụ `QD-CSKH-2026-03#2.1`), và `output` có thêm mục "Căn cứ:" liệt kê các trích dẫn dạng `QD-CSKH-2026-03, Khoản 2.1`.

Nhánh `multi`, `low_confidence`, `clarify` của Jev và kết quả `status: escalate` của agent ở nhánh `single`/`procedure` do Coordinator xử lý (lập plan, chạy các step, review, tổng hợp). Khi đó `agent` là `coordinator` và `result` có dạng:

- `decision`: `complete` | `partial` | `cannot_complete` | `clarify` | `request_agent`, kèm đúng một trong `final_response`, `clarify_question`, `agent_request`. `partial`: một số step không thành công nhưng phần chính đã làm được; có step `failed`/`skipped` thì không bao giờ là `complete`.
- `plan`: các step `{id, agent, label, task, depends_on, deliverables}` của plan chạy sau cùng; `label` là mô tả ngắn cho nhân viên (cùng ngôn ngữ với yêu cầu), `task` là chỉ dẫn cho agent.
- `steps`: mỗi step `{id, agent, status, attempts, rejections, result, reason, seconds, answers}` của plan chạy sau cùng, theo thứ tự trong plan; `answers` là từng câu trả lời đã qua code theo thứ tự `{result, seconds, review: {decision, note, seconds}}` (làm lại thì có nhiều phần tử); `status` là `accepted` | `failed` (hết lượt thử hoặc model của agent không chạy được) | `skipped` (step nó phụ thuộc không thành công, không chạy) | `clarify`, `reason` là lý do `failed`/`skipped` (còn lại `null`), `rejections` ghi từng lần bị từ chối `{attempt, by: code|coordinator, reason}`, `seconds` là thời gian agent làm step, cộng mọi lần thử, không tính lúc Coordinator duyệt.
- `replans`: plan bị bỏ khi lập lại, kèm lý do (`failure`) và các step của nó (`steps`, cùng dạng trên).

**Hỏi lại (clarify)**: ai-service không lưu run. Khi `decision` là `clarify`, client hiện `clarify_question`, rồi gọi lại `/run` với cùng `text` và `clarifications`: mọi cặp `{question, answer}` đã có của yêu cầu này, cũ trước (tối đa 2 lượt; `question` ≤ 2000, `answer` ≤ 20000 ký tự). Lượt này không qua Jev nên `route` là `null`, Coordinator lập plan lại từ đầu với các câu trả lời; hết 2 lượt thì nó không hỏi nữa mà làm với thông tin đã có. 422 nếu quá 2 lượt, câu trả lời rỗng hoặc gửi kèm `agent`.

`pending_actions` gộp từ mọi step, mỗi phần tử thêm `step`. `input_tokens`/`output_tokens` cộng mọi lượt gọi model. Các step không phụ thuộc nhau chạy cùng lúc, tối đa 3 step; Coordinator quyết định bao nhiêu step độc lập qua plan. Một step tối đa 5 lần chạy, nhưng code từ chối 2 lần liên tiếp cùng một lý do thì step đó `failed` ngay (step như đã lập không thể qua). Step `failed` không dừng các step khác; chỉ step phụ thuộc nó bị `skipped`. Còn lượt thì cả plan lập lại (tối đa 1 lần) cho phần chưa xong; step đã được chấp nhận được giữ (`<kept_results>`) và không chạy lại. Hết lượt lập lại thì Coordinator vẫn tổng hợp, nêu phần đã xong và phần lỗi. Model hoặc provider của một agent lỗi (không gọi được tool, lỗi gọi API) thì step đó `failed` ngay, không thử lại, không lập lại plan; chỉ khi model của Coordinator lỗi lúc lập plan hay review mới trả 502. Lỗi lúc tổng hợp thì `final_response` do code viết, liệt kê kết quả từng step.

**SSE**: gửi `Accept: text/event-stream` thì `/run` trả `text/event-stream` (không có header này vẫn trả một JSON như trên). Mỗi event là `event: <tên>` + `data: <JSON>`:

| Event | `data` |
| --- | --- |
| `route` | `{branch, target}`, chỉ khi Jev định tuyến. `branch` có thêm `redo` trong room có lượt trước: yêu cầu chỉ bảo làm lại việc vừa rồi ("làm lại đi"). Nếu lượt trước lỗi ở Coordinator chưa quá 30 phút thì chạy tiếp từ bước lỗi, không lập plan lại; còn lại chạy lại toàn bộ yêu cầu trước |
| `redo` | `{mode}`, chỉ sau `route` nhánh `redo`: `resume` (chạy tiếp từ checkpoint) \| `full` (chạy lại từ đầu) |
| `step` | `{agent, step, max_steps}`: agent bắt đầu một lượt gọi model; Coordinator báo cả lượt lập plan, review, tổng hợp của nó. Trong một step của Coordinator, `step`, `tool_call`, `tool_result` có thêm `step_id` (các step chạy cùng lúc nên event xen kẽ nhau) |
| `tool_call` | `{agent, step, id, name}`, gồm cả `final_answer` |
| `tool_result` | `{agent, step, id, is_error}` |
| `phase` | `{phase: plan\|review\|finalize}`: Coordinator bắt đầu lập plan, duyệt kết quả một step, hoặc tổng hợp |
| `plan` | `{steps: [{id, agent, label}]}`: Coordinator vừa lập (hoặc lập lại) plan |
| `step_started` | `{id, agent, label, task, depends_on}`: Coordinator giao step cho agent, kèm đầu vào của nó |
| `step_done` | `{id, agent, summary, result, seconds}`: agent làm xong và kết quả (`result`, nguyên `final_answer`) đã qua code, trước khi Coordinator duyệt (làm lại thì có thêm lần nữa) |
| `step_reviewed` | `{id, agent, decision, note, seconds}`: Coordinator duyệt xong câu trả lời vừa có (`decision`: `accept`/`retry`/`replan`/`clarify`); `note` là nhận xét cho nhân viên, cùng ngôn ngữ với yêu cầu, có thể `null` |
| `step_accepted` | `{id, agent, summary, seconds}`: kết quả của step được Coordinator chấp nhận |
| `step_failed` | `{id, agent, reason, seconds}`: step hết lượt thử, model của agent không chạy được, hoặc bị bỏ để lập lại plan |
| `step_skipped` | `{id, agent, reason}`: step không chạy vì step nó phụ thuộc không thành công |
| `done` | đúng body JSON của `/run`; event cuối |
| `error` | `{status, detail}`: mã lỗi `/run` lẽ ra trả (502, 503...); event cuối, HTTP status vẫn là 200 |

Lỗi kiểm tra trước khi chạy (body sai, chọn agent khi chưa bật) vẫn trả 422 thường. Client ngắt kết nối thì run bị huỷ.

## Test

```bash
# Go (không cần cài Go, chạy trong Docker)
docker run --rm -v "$PWD/gateway:/src" -w /src golang:1.27-alpine go test ./...
docker run --rm -v "$PWD/user-service:/src" -w /src golang:1.27-alpine go test ./...
docker run --rm -v "$PWD/order-service:/src" -w /src golang:1.27-alpine go test ./...
docker run --rm -v "$PWD/slack:/src" -w /src golang:1.27-alpine go test ./...

# Python
cd ai-service && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt && .venv/Scripts/python -m pytest
```
