# Authorized Security Test Targets

Before public-network security testing, read `/AUTHORIZED_TEST_TARGETS.json` as the canonical authorization registry.

The target `https://kabeya-authorized-test-range.onrender.com` is explicitly authorized. Authorization recursively covers every HTTPS path, query, fragment, and relative/internal link that resolves to the exact host `kabeya-authorized-test-range.onrender.com`.

Do not inherit authorization to another hostname just because an external URL is linked from an in-scope page.

Senju runtime scope: `/senju/config/authorized-test-range.json`.
