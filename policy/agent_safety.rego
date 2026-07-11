package agent.safety

import future.keywords.in

default allow = false

wholesome_intents := {"creative", "cooperative", "insightful"}
safe_domains      := {"github.com", "api.github.com"}

limits := {
  "ttl": 3,
  "max_children": 5,
  "max_concurrency": 2,
  "rate_limit_per_minute": 30
}

allow {
  input.pause_before_propagate == true
  input.intent in wholesome_intents
  input.domain in safe_domains
  within_limits
  ttl_guard
  not encoded_payload_detected
}

within_limits {
  input.ttl        <= limits.ttl
  input.children   <= limits.max_children
  input.concurrency <= limits.max_concurrency
  input.rate       <= limits.rate_limit_per_minute
}

# TTL must be greater than 0
ttl_guard {
  input.ttl > 0
}

# Encoded payload detection (behind feature flag)
encoded_payload_detected {
  data.agent_limits.enforce_encoded_payload == true
  input.payload
  is_encoded_payload(input.payload)
}

# Check if payload contains encoded content
is_encoded_payload(payload) {
  is_base64_like(payload)
}

is_encoded_payload(payload) {
  is_url_encoded(payload)
}

is_encoded_payload(payload) {
  is_data_uri(payload)
}

# Base64 detection: 8+ total chars, alphanumeric + / + = optional padding.
# Length floor of 8 rejects short alphanumeric strings like "test123" that
# happen to match the base64 alphabet but aren't actually encoded content.
# 8 is the smallest meaningful base64 output length (encodes 4-6 raw bytes
# with padding), so this floor preserves detection of genuine short base64
# while eliminating the false-positive class of plain words and identifiers.
#
# CONTRACT (issue #157): base64 detection is intentionally WHOLE-PAYLOAD —
# the regex is anchored (^…$) on purpose. A base64-form token embedded
# inside ordinary prose is NOT an encoded payload for this policy; embedded
# arbitrary-text substring scanning is out of scope (the false-positive
# surface of scanning ordinary prose — plain words, identifiers, hashes
# quoted in text — is not justified by current evidence). Do not add a
# decoder, entropy heuristic, tokenizer, or broader payload scanner here
# without a new recorded decision. URL-encoding detection below remains
# deliberately unanchored; data-URI detection remains prefix-based.
is_base64_like(payload) {
  regex.match(`^[A-Za-z0-9+/]{4,}={0,2}$`, payload)
  count(payload) >= 8
}

# URL encoding detection: contains %XX patterns
is_url_encoded(payload) {
  regex.match(`%[0-9A-Fa-f]{2}`, payload)
}

# Data URI detection: starts with data:
is_data_uri(payload) {
  startswith(payload, "data:")
}

# Happy-path allow (baseline within limits)
test_allow_creative_github_within_limits {
  allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}

# Encoded payload feature-flag OFF (default): allow benign base64/url/data-URI
test_allow_base64_when_flag_false {
  allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30,
    "payload": "aGVsbG8gd29ybGQ="  # "hello world"
  }
}

test_allow_urlencoded_when_flag_false {
  allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30,
    "payload": "test%20string"
  }
}

test_allow_datauri_when_flag_false {
  allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30,
    "payload": "data:text/plain;base64,SGk="
  }
}

# Encoded payload feature-flag ON: deny encoded payloads
test_deny_base64_when_flag_true {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30,
    "payload": "aGVsbG8gd29ybGQ="
  } with data.agent_limits.enforce_encoded_payload as true
}

test_deny_urlencoded_when_flag_true {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30,
    "payload": "cmd%20%2Fbin%2Fbash"
  } with data.agent_limits.enforce_encoded_payload as true
}

# TTL boundaries
test_deny_ttl_zero {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 0,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}

test_deny_ttl_negative {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": -1,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}

# Resource limit boundaries (config: children<=5, concurrency<=2, rate<=30)
test_deny_children_over_limit {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 6,
    "concurrency": 2,
    "rate": 30
  }
}

test_deny_concurrency_over_limit {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 3,
    "rate": 30
  }
}

test_deny_rate_over_limit {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 31
  }
}

# Unicode/IDN domains should be denied (not in allowlist)
test_deny_unicode_domain_cyrillic_tld {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "github.com.рф",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}

test_deny_idn_domain_umlaut {
  not allow with input as {
    "pause_before_propagate": true,
    "intent": "creative",
    "domain": "githüb.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}

# Intent: include "insightful" in wholesome intents
test_allow_intent_insightful {
  allow with input as {
    "pause_before_propagate": true,
    "intent": "insightful",
    "domain": "github.com",
    "ttl": 3,
    "children": 5,
    "concurrency": 2,
    "rate": 30
  }
}
