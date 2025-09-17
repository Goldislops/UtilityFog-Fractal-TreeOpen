package agent.safety

import rego.v1

# Test data for various scenarios
test_data := {
    "agent_limits": {
        "enforce_encoded_payload": true,
        "max_ttl": 3600,
        "allowed_actions": ["read", "write", "execute"]
    }
}

# Test TTL guard functionality
test_ttl_guard_positive if {
    ttl_guard with input as {"ttl": 300}
}

test_ttl_guard_zero if {
    not ttl_guard with input as {"ttl": 0}
}

test_ttl_guard_negative if {
    not ttl_guard with input as {"ttl": -100}
}

test_ttl_guard_missing if {
    not ttl_guard with input as {}
}

# Test encoded payload detection - Base64
test_encoded_payload_base64_detected if {
    encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data as test_data
}

test_encoded_payload_base64_padding if {
    encoded_payload_detected with input as {"payload": "dGVzdA=="} with data as test_data
}

test_encoded_payload_base64_no_padding if {
    encoded_payload_detected with input as {"payload": "dGVzdGluZw"} with data as test_data
}

# Test encoded payload detection - URL encoding
test_encoded_payload_url_encoded if {
    encoded_payload_detected with input as {"payload": "hello%20world%21"} with data as test_data
}

test_encoded_payload_url_complex if {
    encoded_payload_detected with input as {"payload": "user%3Dadmin%26pass%3D123"} with data as test_data
}

# Test encoded payload detection - Data URI
test_encoded_payload_data_uri if {
    encoded_payload_detected with input as {"payload": "data:text/plain;base64,SGVsbG8="} with data as test_data
}

test_encoded_payload_data_uri_image if {
    encoded_payload_detected with input as {"payload": "data:image/png;base64,iVBORw0KGgo="} with data as test_data
}

# Test plain text (should not be detected as encoded)
test_encoded_payload_plain_text if {
    not encoded_payload_detected with input as {"payload": "hello world"} with data as test_data
}

test_encoded_payload_simple_string if {
    not encoded_payload_detected with input as {"payload": "test123"} with data as test_data
}

test_encoded_payload_json if {
    not encoded_payload_detected with input as {"payload": "{\"key\": \"value\"}"} with data as test_data
}

# Test encoded payload detection when flag is disabled
test_encoded_payload_flag_disabled if {
    not encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ="} with data as {"agent_limits": {"enforce_encoded_payload": false}}
}

# Test main allow rule - valid cases
test_allow_valid_request if {
    allow with input as {
        "ttl": 300,
        "payload": "hello world",
        "action": "read"
    } with data as test_data
}

test_allow_valid_no_payload if {
    allow with input as {
        "ttl": 300,
        "action": "read"
    } with data as test_data
}

# Test main allow rule - invalid cases (TTL)
test_allow_invalid_ttl_zero if {
    not allow with input as {
        "ttl": 0,
        "payload": "hello world",
        "action": "read"
    } with data as test_data
}

test_allow_invalid_ttl_negative if {
    not allow with input as {
        "ttl": -100,
        "payload": "hello world",
        "action": "read"
    } with data as test_data
}

# Test main allow rule - invalid cases (encoded payload)
test_allow_invalid_base64_payload if {
    not allow with input as {
        "ttl": 300,
        "payload": "SGVsbG8gV29ybGQ=",
        "action": "read"
    } with data as test_data
}

test_allow_invalid_url_encoded_payload if {
    not allow with input as {
        "ttl": 300,
        "payload": "hello%20world",
        "action": "read"
    } with data as test_data
}

test_allow_invalid_data_uri_payload if {
    not allow with input as {
        "ttl": 300,
        "payload": "data:text/plain;base64,SGVsbG8=",
        "action": "read"
    } with data as test_data
}

# Test edge cases
test_allow_empty_payload if {
    allow with input as {
        "ttl": 300,
        "payload": "",
        "action": "read"
    } with data as test_data
}

test_allow_whitespace_payload if {
    allow with input as {
        "ttl": 300,
        "payload": "   ",
        "action": "read"
    } with data as test_data
}

# Test with encoded payload detection disabled
test_allow_base64_when_flag_disabled if {
    allow with input as {
        "ttl": 300,
        "payload": "SGVsbG8gV29ybGQ=",
        "action": "read"
    } with data as {"agent_limits": {"enforce_encoded_payload": false}}
}

# Test boundary conditions for Base64 detection
test_encoded_payload_short_base64 if {
    not encoded_payload_detected with input as {"payload": "abc"} with data as test_data
}

test_encoded_payload_minimum_base64 if {
    encoded_payload_detected with input as {"payload": "abcd"} with data as test_data
}

# Test mixed content
test_encoded_payload_mixed_content if {
    encoded_payload_detected with input as {"payload": "Hello SGVsbG8gV29ybGQ= World"} with data as test_data
}

test_encoded_payload_url_in_text if {
    encoded_payload_detected with input as {"payload": "Visit https://example.com%2Fpath for more info"} with data as test_data
}
