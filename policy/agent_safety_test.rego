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

# Whole-payload contract (issue #157 — contract locked in code; the issue's
# disposition remains a separate decision): base64 detection is INTENTIONALLY
# whole-payload. The anchored regex means a base64-form token embedded in
# ordinary prose is NOT treated as an encoded payload — embedded
# arbitrary-text substring scanning is out of scope, because the
# false-positive surface of scanning ordinary prose is not justified by
# current evidence. No decoder, entropy heuristic, tokenizer, or broader
# payload scanner. URL-encoding detection remains deliberately unanchored
# (see test_encoded_payload_url_in_text); data-URI detection remains
# prefix-based.

# Regression: mixed natural text containing a harmless base64-form token is
# NOT detected as an encoded payload, even with enforcement enabled.
test_encoded_payload_mixed_text_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "Hello SGVsbG8gV29ybGQ= World"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# Whole-payload contract — REJECTION boundary (issue #157)
#
# The cases below pin the anchoring itself. Each payload contains a
# well-formed base64 token that an embedded/substring scanner WOULD flag;
# under the whole-payload contract none of them is an encoded payload. They
# are what makes the contract executable rather than merely commented: an
# unanchored regex, a tokenizer, or an entropy scan added to is_base64_like
# would turn every one of these red.
# ---------------------------------------------------------------------------

# Command-like content wrapped in ordinary words — the obfuscation shape the
# issue raised. Deliberately NOT detected: the token is embedded, not whole.
test_encoded_payload_embedded_command_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "run dGVzdGluZw== now"} with data.agent_limits.enforce_encoded_payload as true
}

# Trailing punctuation breaks the whole-payload match ($ anchor).
test_encoded_payload_trailing_punctuation_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "SGVsbG8gV29ybGQ=."} with data.agent_limits.enforce_encoded_payload as true
}

# Surrounding brackets break the whole-payload match (^ and $ anchors).
test_encoded_payload_bracketed_token_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "(SGVsbG8gV29ybGQ=)"} with data.agent_limits.enforce_encoded_payload as true
}

# Non-ASCII text around an ASCII base64 token still fails the anchors; the
# regex is byte/rune-agnostic here because the anchors do the work.
test_encoded_payload_unicode_surrounded_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "héllo SGVsbG8gV29ybGQ= wörld"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# Whole-payload contract — MALFORMED candidates (issue #157)
#
# '=' is not a member of the character class, so padding is only ever legal
# as the 0-2 trailing characters. These pin that padding placement is not
# merely conventional but structurally enforced.
# ---------------------------------------------------------------------------

# Padding in an interior position: the leading run is too short to satisfy {4,}.
test_encoded_payload_interior_padding_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "dGV=zdA="} with data.agent_limits.enforce_encoded_payload as true
}

# Leading padding: '^' requires the alphabet run to start the payload.
test_encoded_payload_leading_padding_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "=dGVzdA="} with data.agent_limits.enforce_encoded_payload as true
}

# Three padding characters exceed the {0,2} bound.
test_encoded_payload_triple_padding_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "dGVzdA==="} with data.agent_limits.enforce_encoded_payload as true
}

# Padding with no alphabet run at all.
test_encoded_payload_padding_only_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "===="} with data.agent_limits.enforce_encoded_payload as true
}

# Interior whitespace breaks the run.
test_encoded_payload_internal_space_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "dGVzd A=="} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# Length floor — the boundary is exactly 8 (issue #157)
# ---------------------------------------------------------------------------

# 4 chars: matches the regex but is below the count floor.
test_encoded_payload_four_char_token_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "abcd"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# CHARACTERIZATION — the retained over-inclusive surface (issue #157)
#
# These assert what the policy DOES today, not what is ideal. The length
# floor bounds the false-positive surface by length only, so any whole
# payload of 8+ characters drawn entirely from [A-Za-z0-9+/] is classified
# base64-like — including ordinary words, hex hashes and slash-separated
# paths. That is retained deliberately: detection means denial, so the bias
# is fail-closed, and the rule is gated behind a flag that is not set
# anywhere in this repository.
#
# They are NOT an endorsement. If a future decision narrows the matcher
# (entropy, decode-and-verify, dictionary rejection), these tests must be
# updated deliberately — which is the point of pinning them.
# ---------------------------------------------------------------------------

# An ordinary 8-letter English word is currently classified base64-like.
test_encoded_payload_plain_word_is_currently_detected if {
	safety.encoded_payload_detected with input as {"payload": "password"} with data.agent_limits.enforce_encoded_payload as true
}

# A hex digest is currently classified base64-like.
test_encoded_payload_hex_hash_is_currently_detected if {
	safety.encoded_payload_detected with input as {"payload": "deadbeefdeadbeef"} with data.agent_limits.enforce_encoded_payload as true
}

# '/' is a base64 alphabet member, so a bare path is currently classified
# base64-like.
test_encoded_payload_path_segment_is_currently_detected if {
	safety.encoded_payload_detected with input as {"payload": "usr/local/bin"} with data.agent_limits.enforce_encoded_payload as true
}

# A hyphen is NOT in the alphabet, so slugs are not classified — this is the
# other side of the same boundary.
test_encoded_payload_hyphenated_slug_not_detected if {
	not safety.encoded_payload_detected with input as {"payload": "my-blog-post-title"} with data.agent_limits.enforce_encoded_payload as true
}

# ---------------------------------------------------------------------------
# URL-encoding boundary — lowercase hex digits (issue #157 matrix gap)
# ---------------------------------------------------------------------------

# The %XX class accepts lowercase hex; pins that the detector is not
# uppercase-only and remains unanchored.
test_encoded_payload_url_lowercase_hex if {
	safety.encoded_payload_detected with input as {"payload": "a%2fb"} with data.agent_limits.enforce_encoded_payload as true
}

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

# Allow-level regression for the whole-payload contract (issue #157): an
# otherwise fully valid request whose payload is ordinary prose containing a
# base64-form token stays ALLOWED while encoded-payload enforcement is
# enabled.
test_allow_mixed_text_payload_with_enforcement if {
	safety.allow with input as {
		"pause_before_propagate": true,
		"intent": "creative",
		"domain": "github.com",
		"ttl": 3,
		"children": 5,
		"concurrency": 2,
		"rate": 30,
		"payload": "Hello SGVsbG8gV29ybGQ= World",
		"action": "read",
	} with data.agent_limits.enforce_encoded_payload as true
}
