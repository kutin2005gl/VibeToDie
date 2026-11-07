export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

let baseUrl = ''

// Web và desktop (Wails) cùng gọi API này; mỗi app gọi setApiBase một lần lúc khởi động.
export function setApiBase(url: string) {
  baseUrl = url.replace(/\/+$/, '')
}

export function apiUrl(path: string) {
  return baseUrl + path
}
