export const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`

export const tokens = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(Math.round(n))

export const when = (iso: string) => new Date(iso).toLocaleString('vi-VN')

/** Màu của series thứ i, quay vòng trong 7 màu của theme. */
export const seriesColor = (i: number) => `var(--series-${(i % 7) + 1})`
