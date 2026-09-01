# Source this file, then `claude` in THIS shell goes through the proxy (nothing else affected).
TAP_PORT="${TAP_PORT:-8080}"
export HTTPS_PROXY="http://127.0.0.1:$TAP_PORT"
export HTTP_PROXY="http://127.0.0.1:$TAP_PORT"
export NODE_EXTRA_CA_CERTS="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
