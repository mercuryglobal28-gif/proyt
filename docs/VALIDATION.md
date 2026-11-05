# Validation record

- 10 unit tests passed locally (parser exclusions, source failure/deduplication, median latency, speed failure, redirect/body/TLS rejection, empty output freshness, ordering, explicit curl routing).
- Live bounded run: 7,109 distinct public candidates gathered; random sample of 24 tested with 6 workers and 5-second per-request timeout; 0 passed. This is not proof that all candidates fail. No working endpoints or speeds were invented.
- A separate direct YouTube baseline returned curl exit 6 (DNS resolution failure) in the local environment. Current code records a direct baseline in each run to help distinguish measurement-environment problems. It does not require direct connectivity to accept a successfully proxied request.
- No Android app changes, physical TV use, or ADB.
- Hosted workflow execution and live successful-proxy throughput still require verification on GitHub.
