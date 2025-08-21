package agent.safety

default allow = false

wholesome_intents := {"creative", "cooperative", "insightful"}
safe_domains := {"github.com", "api.github.com"}

limits := {
  "ttl": 3,
  "max_children": 5,
  "max_concurrency": 2,
  "rate_limit_per_minute": 30
}

allow if {
  input.pause_before_propagate == true
  input.intent in wholesome_intents
  input.domain in safe_domains
  within_limits
}

within_limits if {
  input.ttl <= limits.ttl
  input.children <= limits.max_children
  input.concurrency <= limits.max_concurrency
  input.rate <= limits.rate_limit_per_minute
}
