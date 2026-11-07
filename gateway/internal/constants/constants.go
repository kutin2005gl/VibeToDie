// Package constants names the headers and context keys shared by middleware and proxy.
package constants

const (
	HeaderRequestID = "X-Request-Id"

	// Identity the gateway derives from a verified token. Services behind it trust these and
	// nothing else, so any client-supplied copy is deleted first.
	HeaderUserID          = "X-User-Id"
	HeaderUserEmail       = "X-User-Email"
	HeaderUserDepartments = "X-User-Departments"

	ContextClaims    = "claims"
	ContextRequestID = "request_id"
)

// IdentityHeaders are stripped from every inbound request before the gateway sets its own.
var IdentityHeaders = []string{HeaderUserID, HeaderUserEmail, HeaderUserDepartments}
