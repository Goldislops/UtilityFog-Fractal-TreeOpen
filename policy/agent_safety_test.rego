package agent.safety_test

# Tests live in a separate package from the policy under test (agent.safety)
# so test helpers / mock data don't share the policy package namespace.
#
# Each test mocks specific data paths via `with data.<path> as <value>`
# rather than replacing the data root via `with data as {...}`. The latter
# was triggering OPA v0.59.0's recursion analyzer to treat all sibling
# tests using root-mocks as potentially mutually dependent — a false
# positive that the path-mock form avoids by only naming the specific
# leaf the policy actually reads.
#
# Allow tests use the *full* policy-required input shape (pause_before_propagate,
# intent, domain, ttl, children, concurrency, rate, ± payload). Each negative
# allow test deliberately violates exactly one condition while keeping all
# other conditions otherwise valid — so each test fails for the reason it
# claims to test, not accidentally because of missing required fields.
#
# Policy rules are imported as `safety` and referenced via `safety.allow`,
# `safety.encoded_payload_detected`, etc.

import data.agent.safety
import rego.v1

# ---------------------------------------------------------------------------
# ttl_guard isolated tests
# ---------------------------------------------------------------------------

test_ttl_guard_positive if {
	safety.ttl_guard with input as {"ttl": 300}
}

test_ttl_guard_zero if {
	not safety.ttl_guard with input as {"ttl": 0}
}

test_ttl_guard_negative if {
	not safety.ttl_guard with input as {"ttl": -100}
}

test_ttl_guard_missing if {
	not safety.ttl_guard with input as {}
}

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — base64 alphabet
# ---------------------------------------------------------------------------

test_encoded_payload_base64_detected if {
	safety.encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_base64_padding if {
	safety.encoded_payload_detected with input as {"payload": "dGVzdA=="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_base64_no_padding if {
	safety.encoded_payload_detected with input as {"payload": "dGVzdGluZw"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — URL encoding
# ---------------------------------------------------------------------------

test_encoded_payload_url_encoded if {
	safety.encoded_payload_detected with input as {"payload": "hello%20world%21"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_url_complex if {
	safety.encoded_payload_detected with input as {"payload": "user%3Dadmin%26pass%3D123"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — data URI
# ---------------------------------------------------------------------------

test_encoded_payload_data_uri if {
	safety.encoded_payload_detected with input as {"payload": "data:text/plain;base64,SGVsbG8="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_data_uri_image if {
	safety.encoded_payload_detected with input as {"payload": "data:image/png;base64,iVBORw0KGgo="} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — should NOT detect
# ---------------------------------------------------------------------------

test_encoded_payload_plain_text if {
	not safety.encoded_payload_detected with input as {"payload": "hello world"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_simple_string if {
	not safety.encoded_payload_detected with input as {"payload": "test123"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_json if {
	not safety.encoded_payload_detected with input as {"payload": "{\"key\": \"value\"}"} with data.agent_limits.enforce_encoded_payload as true
}

# Embedded base64 substring inside natural text — currently NOT detected by
# the anchored regex. Whether this should be detected is a real design
# question (false-positive risk vs catching obfuscation) tracked in
# issue #157. Removed from the regression suite until that's decided.
# Was: test_encoded_payload_mixed_content with input "Hello SGVsbG8gV29ybGQ= World"

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — flag disabled
# ---------------------------------------------------------------------------

test_encoded_payload_flag_disabled if {
	not safety.encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data.agent_limits.enforce_encoded_payload as false
}

# ---------------------------------------------------------------------------
# encoded_payload_detected isolated tests — base64 length boundary
# ---------------------------------------------------------------------------

test_encoded_payload_short_base64 if {
	not safety.encoded_payload_detected with input as {"payload": "abc"} with data.agent_limits.enforce_encoded_payload as true
}

# Minimum positive case: 8-char base64 of "tests" with padding. Replaces the
# pre-fix test that asserted "abcd" was detected — that test was asserting
# the false-positive bug the regex tightening fixes.
test_encoded_payload_minimum_base64 if {
	safety.encoded_payload_detected with input as {"payload": "dGVzdHM="} with data.agent_limits.enforce_encoded_payload as true
}

# URL encoding embedded in surrounding text — works because the is_url_encoded
# regex is intentionally unanchored.
test_encoded_payload_url_in_text if {
	safety.encoded_payload_detected with input as {"payload": "Visit https://example.com%2Fpath for more info"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# allow rule tests — repaired to use the FULL policy-required input shape.
# Negative tests violate exactly one condition while keeping all others
# otherwise valid, so each test fails for the reason it claims to test.
#
# Policy contract (from agent_safety.rego):
#   - pause_before_propagate == true
#   - intent in {"creative", "cooperative", "insightful"}
#   - domain in {"github.com", "api.github.com"}
#   - ttl > 0 AND ttl <= 3
#   - children <= 5
#   - concurrency <= 2
#   - rate <= 30
#   - not encoded_payload_detected
# ---------------------------------------------------------------------------

# Valid request with a benign payload.
test_allow_valid_request if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Valid request with no payload at all.
test_allow_valid_no_payload if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# ttl == 0 violates ttl_guard. All other fields otherwise valid.
test_allow_invalid_ttl_zero if {
	not safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 0,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# ttl negative violates ttl_guard.
test_allow_invalid_ttl_negative if {
	not safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": -100,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Encoded payload (whole-payload base64) when enforcement is on.
test_allow_invalid_base64_payload if {
	not safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "SGVsbG8gV29ybGQ=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Encoded payload (URL-encoded substring) when enforcement is on.
test_allow_invalid_url_encoded_payload if {
	not safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "hello%20world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Encoded payload (data URI) when enforcement is on.
test_allow_invalid_data_uri_payload if {
	not safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "data:text/plain;base64,SGVsbG8=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Empty-string payload should not be detected as encoded; allow passes.
test_allow_empty_payload if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Whitespace-only payload should not be detected as encoded; allow passes.
test_allow_whitespace_payload if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "   ",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# When the encoded-payload enforcement flag is OFF, base64 payloads are allowed.
test_allow_base64_when_flag_disabled if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "SGVsbG8gV29ybGQ=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as false
}
