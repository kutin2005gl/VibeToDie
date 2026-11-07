package store

import (
	"strings"
)

// Unaccent lowercases and strips Vietnamese diacritics, replacing 'đ' with 'd'.
func Unaccent(s string) string {
	s = strings.ToLower(s)
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		switch r {
		case 'đ':
			b.WriteRune('d')
		case 'à', 'á', 'ả', 'ã', 'ạ', 'ă', 'ằ', 'ắ', 'ẳ', 'ẵ', 'ặ', 'â', 'ầ', 'ấ', 'ẩ', 'ẫ', 'ậ':
			b.WriteRune('a')
		case 'è', 'é', 'ẻ', 'ẽ', 'ẹ', 'ê', 'ề', 'ế', 'ể', 'ễ', 'ệ':
			b.WriteRune('e')
		case 'ì', 'í', 'ỉ', 'ĩ', 'ị':
			b.WriteRune('i')
		case 'ò', 'ó', 'ỏ', 'õ', 'ọ', 'ô', 'ồ', 'ố', 'ổ', 'ỗ', 'ộ', 'ơ', 'ờ', 'ớ', 'ở', 'ỡ', 'ợ':
			b.WriteRune('o')
		case 'ù', 'ú', 'ủ', 'ũ', 'ụ', 'ư', 'ừ', 'ứ', 'ử', 'ữ', 'ự':
			b.WriteRune('u')
		case 'ỳ', 'ý', 'ỷ', 'ỹ', 'ỵ':
			b.WriteRune('y')
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}
