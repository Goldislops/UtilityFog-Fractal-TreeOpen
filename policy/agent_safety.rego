package agent.safety

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
}

within_limits {
  input.ttl        <= limits.ttl
  input.children   <= limits.max_children
  input.concurrency <= limits.max_concurrency
  input.rate       <= limits.rate_limit_per_minute
}
package agent.safety
import rego.v1

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
