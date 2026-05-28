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
# Diagnostic that pinned this down: after the package-split (commit
# 913112f) and after inlining test_data into every site (commit 286870d),
# the recursion errors persisted. The 4 `test_ttl_guard_*` tests were the
# only tests with no `with data as ...` modifier, and they were the only
# tests not in any cycle. That correlated 1:1.
#
# Policy rules are imported as `safety` and referenced via `safety.allow`,
# `safety.encoded_payload_detected`, etc.

import data.agent.safety
import rego.v1

# Test TTL guard functionality
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

# Test encoded payload detection - Base64
test_encoded_payload_base64_detected if {
	safety.encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_base64_padding if {
	safety.encoded_payload_detected with input as {"payload": "dGVzdA=="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_base64_no_padding if {
	safety.encoded_payload_detected with input as {"payload": "dGVzdGluZw"} with data.agent_limits.enforce_encoded_payload as true
}

# Test encoded payload detection - URL encoding
test_encoded_payload_url_encoded if {
	safety.encoded_payload_detected with input as {"payload": "hello%20world%21"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_url_complex if {
	safety.encoded_payload_detected with input as {"payload": "user%3Dadmin%26pass%3D123"} with data.agent_limits.enforce_encoded_payload as true
}

# Test encoded payload detection - Data URI
test_encoded_payload_data_uri if {
	safety.encoded_payload_detected with input as {"payload": "data:text/plain;base64,SGVsbG8="} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_data_uri_image if {
	safety.encoded_payload_detected with input as {"payload": "data:image/png;base64,iVBORw0KGgo="} with data.agent_limits.enforce_encoded_payload as true
}

# Test plain text (should not be detected as encoded)
test_encoded_payload_plain_text if {
	not safety.encoded_payload_detected with input as {"payload": "hello world"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_simple_string if {
	not safety.encoded_payload_detected with input as {"payload": "test123"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_json if {
	not safety.encoded_payload_detected with input as {"payload": "{\"key\": \"value\"}"} with data.agent_limits.enforce_encoded_payload as true
}

# Test encoded payload detection when flag is disabled
test_encoded_payload_flag_disabled if {
	not safety.encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data.agent_limits.enforce_encoded_payload as false
}

# Test main allow rule - valid cases
test_allow_valid_request if {
	safety.allow with input as {
		"ttl": 300,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

test_allow_valid_no_payload if {
	safety.allow with input as {
		"ttl": 300,
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Test main allow rule - invalid cases (TTL)
test_allow_invalid_ttl_zero if {
	not safety.allow with input as {
		"ttl": 0,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

test_allow_invalid_ttl_negative if {
	not safety.allow with input as {
		"ttl": -100,
		"payload": "hello world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Test main allow rule - invalid cases (encoded payload)
test_allow_invalid_base64_payload if {
	not safety.allow with input as {
		"ttl": 300,
		"payload": "SGVsbG8gV29ybGQ=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

test_allow_invalid_url_encoded_payload if {
	not safety.allow with input as {
		"ttl": 300,
		"payload": "hello%20world",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

test_allow_invalid_data_uri_payload if {
	not safety.allow with input as {
		"ttl": 300,
		"payload": "data:text/plain;base64,SGVsbG8=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Test edge cases
test_allow_empty_payload if {
	safety.allow with input as {
		"ttl": 300,
		"payload": "",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

test_allow_whitespace_payload if {
	safety.allow with input as {
		"ttl": 300,
		"payload": "   ",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}

# Test with encoded payload detection disabled
test_allow_base64_when_flag_disabled if {
	safety.allow with input as {
		"ttl": 300,
		"payload": "SGVsbG8gV29ybGQ=",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as false
}

# Test boundary conditions for Base64 detection
test_encoded_payload_short_base64 if {
	not safety.encoded_payload_detected with input as {"payload": "abc"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_minimum_base64 if {
	safety.encoded_payload_detected with input as {"payload": "abcd"} with data.agent_limits.enforce_encoded_payload as true
}

# Test mixed content
test_encoded_payload_mixed_content if {
	safety.encoded_payload_detected with input as {"payload": "Hello SGVsbG8gV29ybGQ= World"} with data.agent_limits.enforce_encoded_payload as true
}

test_encoded_payload_url_in_text if {
	safety.encoded_payload_detected with input as {"payload": "Visit https://example.com%2Fpath for more info"} with data.agent_limits.enforce_encoded_payload as true
}
